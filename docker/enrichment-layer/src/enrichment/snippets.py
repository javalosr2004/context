"""Hot-path snippet pipeline.

Synchronous Tavily-shaped grounding: take 1+ pre-refined queries, fan
out search + fetch + extract, summarize the top candidate pages in
parallel, and return short snippets. No persistence, no per-page
DraftPlan parse, no aggregate stage — those live in the slow /query
path.

When multiple queries are supplied (the multimodal path), URL dedup
runs across the merged hit list so the aggregator sees coverage across
facets rather than the same page surfacing from each query.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from pydantic import BaseModel

from enrichment.cache import l4_page, l5_summary
from enrichment.config import settings
from enrichment.extract import extract
from enrichment.fetch import fan_out_fetch
from enrichment.models import ExtractedPage
from enrichment.parse import is_parse_candidate
from enrichment.search import fan_out_search
from enrichment.summarize import summarize_page_for_goal

logger = logging.getLogger(__name__)

DEFAULT_NUM_SOURCES = 5
# Fetch a bit more than we need so heuristic ranking has something to discard.
FETCH_OVERSAMPLE = 2


class Snippet(BaseModel):
    title: str
    url: str
    content: str


@dataclass(frozen=True)
class SnippetResult:
    snippets: list[Snippet]
    source_count: int
    elapsed_ms: float
    # Provenance: which input query each snippet's source URL surfaced
    # from. A URL discovered by multiple queries appears under each. The
    # backend uses this to populate its per-query cache from a single
    # multimodal /snippets call.
    snippets_by_query: dict[str, list[Snippet]] | None = None


async def run_snippet_pipeline(
    queries: list[str],
    application: str | None,
    goal: str | None,
    num_sources: int = DEFAULT_NUM_SOURCES,
) -> SnippetResult:
    start = time.perf_counter()
    num_sources = max(1, min(num_sources, 10))
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries:
        return SnippetResult(
            snippets=[], source_count=0, elapsed_ms=0.0,
            snippets_by_query={},
        )

    hits = await fan_out_search(queries)
    urls: list[str] = []
    seen: set[str] = set()
    url_to_queries: dict[str, list[str]] = {}
    for h in hits:
        if not h.url:
            continue
        if h.url not in seen:
            seen.add(h.url)
            urls.append(h.url)
            url_to_queries[h.url] = []
        if h.query not in url_to_queries[h.url]:
            url_to_queries[h.url].append(h.query)
    # Scale the URL budget with the number of queries so each facet has
    # a fair shot at contributing a candidate page.
    urls = urls[: num_sources * FETCH_OVERSAMPLE * max(1, len(queries))]

    extractions, missing_urls = _l4_split(urls, application or "", goal or "")
    if missing_urls:
        fetches = await fan_out_fetch(missing_urls)
        for f in fetches:
            page = extract(f, application or "", goal or "")
            _l4_put(f.url, page)
            extractions.append(page)

    candidates = [e for e in extractions if is_parse_candidate(e)]
    if not candidates:
        candidates = sorted(extractions, key=lambda e: e.text_length, reverse=True)
    else:
        candidates.sort(
            key=lambda e: (e.ordered_list_items, e.imperative_verb_density),
            reverse=True,
        )
    candidates = candidates[:num_sources]

    sem = asyncio.Semaphore(settings.fetch_concurrency)

    async def one(page):
        cached = l5_summary.get(page.content_hash, goal, application)
        if cached is not None:
            return page, cached
        async with sem:
            content = await asyncio.to_thread(
                summarize_page_for_goal, page, application, goal,
            )
        if content:
            l5_summary.put(page.content_hash, goal, application, content)
        return page, content

    summarized = await asyncio.gather(
        *(one(p) for p in candidates), return_exceptions=True,
    )

    snippets: list[Snippet] = []
    snippets_by_query: dict[str, list[Snippet]] = {q: [] for q in queries}
    for entry in summarized:
        if isinstance(entry, BaseException):
            logger.warning("snippet summarization raised: %s", entry)
            continue
        page, content = entry
        if not content:
            continue
        snippet = Snippet(title=page.title or "", url=page.url, content=content)
        snippets.append(snippet)
        for q in url_to_queries.get(page.url, []):
            snippets_by_query.setdefault(q, []).append(snippet)

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return SnippetResult(
        snippets=snippets,
        source_count=len(snippets),
        elapsed_ms=elapsed_ms,
        snippets_by_query=snippets_by_query,
    )


# ---- L4 (per-URL fetch+extract cache) helpers --------------------------
#
# Cached value is the "page-pure" subset of ExtractedPage: structural
# features that don't depend on the caller's app/goal. On retrieval we
# recompute `application_term_present` and `goal_term_present` against
# the current call's app/goal so `is_parse_candidate` still gates
# correctly per request.

_PAGE_CORE_FIELDS = (
    "url", "content_hash", "http_status", "title", "text",
    "text_length", "ordered_list_items", "imperative_verb_density",
    "image_count",
)


def _l4_split(
    urls: list[str], application: str, goal: str,
) -> tuple[list[ExtractedPage], list[str]]:
    hits: list[ExtractedPage] = []
    missing: list[str] = []
    for url in urls:
        cached = None
        try:
            cached = l4_page.get(url)
        except Exception:
            cached = None
        if cached:
            hits.append(_hydrate_page(cached, application, goal))
        else:
            missing.append(url)
    return hits, missing


def _l4_put(url: str, page: ExtractedPage) -> None:
    try:
        l4_page.put(url, {k: getattr(page, k) for k in _PAGE_CORE_FIELDS})
    except Exception:
        pass


def _hydrate_page(core: dict, application: str, goal: str) -> ExtractedPage:
    text_lower = (core.get("text") or "").lower()
    return ExtractedPage(
        **{k: core.get(k) for k in _PAGE_CORE_FIELDS},
        application_term_present=(
            bool(application) and application.lower() in text_lower
        ),
        goal_term_present=any(
            tok in text_lower for tok in (goal or "").lower().split() if len(tok) > 3
        ),
    )
