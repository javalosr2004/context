from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

import httpx

from enrichment.config import settings

USER_AGENT = "enrichment-layer/0.1 (+https://example.local)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    http_status: int
    html: bytes
    content_hash: str


async def fan_out_fetch(urls: list[str]) -> list[FetchResult]:
    sem = asyncio.Semaphore(settings.fetch_concurrency)
    seen: set[str] = set()
    unique = [u for u in urls if not (u in seen or seen.add(u))]

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        async def one(url: str) -> FetchResult | None:
            async with sem:
                return await _fetch(client, url)

        results = await asyncio.gather(*(one(u) for u in unique), return_exceptions=True)

    return [r for r in results if isinstance(r, FetchResult)]


async def _fetch(client: httpx.AsyncClient, url: str) -> FetchResult | None:
    try:
        resp = await client.get(url)
    except httpx.HTTPError:
        return None
    html = resp.content
    return FetchResult(
        url=url,
        final_url=str(resp.url),
        http_status=resp.status_code,
        html=html,
        content_hash=hashlib.sha256(html).hexdigest(),
    )
