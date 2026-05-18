from __future__ import annotations

import asyncio
from collections import defaultdict

from enrichment.extract import extract
from enrichment.fetch import fan_out_fetch
from enrichment.models import RunResult
from enrichment.queries import generate_queries
from enrichment.search import fan_out_search
from enrichment.storage import save_run


async def run_enrichment(raw_request: str) -> RunResult:
    plan = await asyncio.to_thread(generate_queries, raw_request)

    hits = await fan_out_search(plan.queries)

    hits_by_query: dict[str, list] = defaultdict(list)
    for h in hits:
        hits_by_query[h.query].append(h)

    urls = list({h.url for h in hits})
    fetches = await fan_out_fetch(urls)

    extractions = [extract(f, plan.application, plan.goal) for f in fetches]

    run_id = await asyncio.to_thread(
        save_run, raw_request, plan, dict(hits_by_query), fetches, extractions,
    )

    return RunResult(
        run_id=run_id,
        plan=plan,
        hit_count=len(hits),
        page_count=len(extractions),
    )
