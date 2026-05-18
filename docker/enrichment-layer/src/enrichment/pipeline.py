from __future__ import annotations

import asyncio
from collections import defaultdict

from enrichment.aggregate import aggregate_drafts
from enrichment.config import settings
from enrichment.extract import extract
from enrichment.fetch import fan_out_fetch
from enrichment.models import RunResult
from enrichment.parse import EnrichedDraft, is_parse_candidate, parse_to_draft
from enrichment.queries import generate_queries
from enrichment.quick import QuickGuide, synthesize_quick_guide
from enrichment.search import fan_out_search
from enrichment.storage import save_quick_guide, save_run

MAX_PARSE_CANDIDATES = 8
MAX_QUICK_CANDIDATES = 8


async def run_enrichment(raw_request: str) -> RunResult:
    plan = await asyncio.to_thread(generate_queries, raw_request)

    hits = await fan_out_search(plan.queries)

    hits_by_query: dict[str, list] = defaultdict(list)
    for h in hits:
        hits_by_query[h.query].append(h)

    urls = list({h.url for h in hits})
    fetches = await fan_out_fetch(urls)

    extractions = [extract(f, plan.application, plan.goal) for f in fetches]

    candidates = sorted(
        (e for e in extractions if is_parse_candidate(e)),
        key=lambda e: (e.ordered_list_items, e.imperative_verb_density),
        reverse=True,
    )[:MAX_PARSE_CANDIDATES]

    drafts = await _parse_candidates(candidates, plan.application, plan.goal)

    aggregate = await asyncio.to_thread(
        aggregate_drafts, drafts, plan.application, plan.goal,
    )

    aggregates = [aggregate] if aggregate else []
    run_id = await asyncio.to_thread(
        save_run,
        raw_request, plan, dict(hits_by_query), fetches, extractions, drafts, aggregates,
    )

    return RunResult(
        run_id=run_id,
        plan=plan,
        hit_count=len(hits),
        page_count=len(extractions),
        parsed_plan_count=len(drafts),
        aggregate_step_count=len(aggregate.steps) if aggregate else 0,
        aggregate_plan_count=1 if aggregate else 0,
    )


async def run_quick_guide(raw_request: str) -> dict:
    """Cheap path: search → fetch → extract → ONE LLM call → markdown guide.

    Skips per-page parsing and structured aggregation. Persists the result
    under a new run_id reachable at GET /runs/{run_id}/quick_guide.
    """
    plan = await asyncio.to_thread(generate_queries, raw_request)
    hits = await fan_out_search(plan.queries)
    urls = list({h.url for h in hits})
    fetches = await fan_out_fetch(urls)
    extractions = [extract(f, plan.application, plan.goal) for f in fetches]

    candidates = sorted(
        (e for e in extractions if is_parse_candidate(e)),
        key=lambda e: (e.ordered_list_items, e.imperative_verb_density),
        reverse=True,
    )[:MAX_QUICK_CANDIDATES]

    guide: QuickGuide | None = await asyncio.to_thread(
        synthesize_quick_guide, candidates, plan.application, plan.goal,
    )

    run_id = await asyncio.to_thread(
        save_quick_guide, raw_request, plan, fetches, extractions, guide,
    )

    return {
        "run_id": run_id,
        "application": plan.application,
        "goal": plan.goal,
        "candidate_count": len(candidates),
        "guide_markdown": guide.guide_markdown if guide else "",
        "source_count": guide.source_count if guide else 0,
    }


async def _parse_candidates(
    candidates: list,
    application: str,
    goal: str,
) -> list[EnrichedDraft]:
    sem = asyncio.Semaphore(settings.fetch_concurrency)

    async def one(page):
        async with sem:
            return await asyncio.to_thread(parse_to_draft, page, application, goal)

    results = await asyncio.gather(*(one(p) for p in candidates), return_exceptions=True)
    return [r for r in results if isinstance(r, EnrichedDraft)]
