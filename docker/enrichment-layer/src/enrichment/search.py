from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from enrichment.cache import l3_search
from enrichment.config import settings
from enrichment.models import SearchHit

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


async def fan_out_search(queries: list[str]) -> list[SearchHit]:
    """Run all queries concurrently, return flattened hits.

    L3 cache (per-query, exact-string after lowercase/whitespace normalize)
    wraps every query. Cache failures fall through to a live Brave call.
    """
    sem = asyncio.Semaphore(settings.brave_concurrency)

    async with httpx.AsyncClient(timeout=20.0) as client:
        async def one(q: str) -> list[SearchHit]:
            cached = _l3_get(q)
            if cached is not None:
                return cached
            async with sem:
                fresh = await _search(client, q)
            _l3_put(q, fresh)
            return fresh

        results = await asyncio.gather(*(one(q) for q in queries), return_exceptions=True)

    hits: list[SearchHit] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        hits.extend(r)
    return hits


def _l3_get(query: str) -> list[SearchHit] | None:
    try:
        raw = l3_search.get(query)
    except Exception:
        return None
    if raw is None:
        return None
    return [SearchHit(**d) for d in raw]


def _l3_put(query: str, hits: list[SearchHit]) -> None:
    try:
        l3_search.put(query, [h.model_dump() for h in hits])
    except Exception:
        pass


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
