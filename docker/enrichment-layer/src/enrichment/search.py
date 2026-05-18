from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from enrichment.config import settings
from enrichment.models import SearchHit

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


async def fan_out_search(queries: list[str]) -> list[SearchHit]:
    """Run all queries concurrently, return flattened hits."""
    sem = asyncio.Semaphore(settings.brave_concurrency)

    async with httpx.AsyncClient(timeout=20.0) as client:
        async def one(q: str) -> list[SearchHit]:
            async with sem:
                return await _search(client, q)

        results = await asyncio.gather(*(one(q) for q in queries), return_exceptions=True)

    hits: list[SearchHit] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        hits.extend(r)
    return hits


async def _search(client: httpx.AsyncClient, query: str) -> list[SearchHit]:
    if not settings.brave_api_key:
        return _load_fixture(query)

    resp = await client.get(
        BRAVE_ENDPOINT,
        params={"q": query, "count": 10},
        headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    return _parse_brave(query, data)


def _parse_brave(query: str, data: dict) -> list[SearchHit]:
    web = (data.get("web") or {}).get("results") or []
    return [
        SearchHit(
            query=query,
            url=item.get("url", ""),
            title=item.get("title", ""),
            snippet=item.get("description", ""),
            rank=i,
        )
        for i, item in enumerate(web)
        if item.get("url")
    ]


def _load_fixture(query: str) -> list[SearchHit]:
    """Fallback for local dev: load from tests/fixtures/brave/<slug>.json if present."""
    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "brave"
    slug = "".join(c if c.isalnum() else "_" for c in query.lower())[:60]
    path = fixtures / f"{slug}.json"
    if path.exists():
        return _parse_brave(query, json.loads(path.read_text()))
    return []
