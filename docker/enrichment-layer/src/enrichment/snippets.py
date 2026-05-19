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

from enrichment.config import settings
from enrichment.extract import extract
from enrichment.fetch import fan_out_fetch
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
        return SnippetResult(snippets=[], source_count=0, elapsed_ms=0.0)

    hits = await fan_out_search(queries)
    urls: list[str] = []
    seen: set[str] = set()
    for h in hits:
        if h.url and h.url not in seen:
            seen.add(h.url)
            urls.append(h.url)
    # Scale the URL budget with the number of queries so each facet has
    # a fair shot at contributing a candidate page.
    urls = urls[: num_sources * FETCH_OVERSAMPLE * max(1, len(queries))]

    fetches = await fan_out_fetch(urls)
    extractions = [
        extract(f, application or "", goal or "")
        for f in fetches
    ]

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
        async with sem:
            return page, await asyncio.to_thread(
                summarize_page_for_goal, page, application, goal,
            )

    summarized = await asyncio.gather(
        *(one(p) for p in candidates), return_exceptions=True,
    )

    snippets: list[Snippet] = []
    for entry in summarized:
        if isinstance(entry, BaseException):
            logger.warning("snippet summarization raised: %s", entry)
            continue
        page, content = entry
        if not content:
            continue
        snippets.append(
            Snippet(title=page.title or "", url=page.url, content=content)
        )

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return SnippetResult(
        snippets=snippets,
        source_count=len(snippets),
        elapsed_ms=elapsed_ms,
    )
