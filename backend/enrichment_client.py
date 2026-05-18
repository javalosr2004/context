"""Web grounding via the enrichment-layer /snippets endpoint.

Drop-in replacement for ``TavilyWebGroundProducer``. Trades a small extra
latency budget (per-page summarization on cleaned text) for grounding
that actually reflects page bodies rather than meta descriptions.
"""
from __future__ import annotations

import logging

import httpx

from backend.web_ground import DEFAULT_MAX_RESULTS, WebGroundSnippet


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 8.0


class EnrichmentSnippetsProducer:
    def __init__(
        self,
        base_url: str,
        *,
        num_sources: int = 5,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("EnrichmentSnippetsProducer requires a non-empty base_url")
        self._endpoint = base_url.rstrip("/") + "/snippets"
        self._num_sources = num_sources
        self._timeout = timeout_seconds
        self._client = client

    def ground(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> list[WebGroundSnippet]:
        query = query.strip()
        if not query:
            return []

        payload = {
            "query": query,
            "num_sources": min(self._num_sources, max_results) if max_results else self._num_sources,
        }

        try:
            response = self._post(payload)
        except httpx.HTTPError as error:
            logger.warning(
                "Enrichment grounding request failed",
                extra={"error": str(error), "query_chars": len(query)},
            )
            return []

        if response.status_code >= 400:
            logger.warning(
                "Enrichment grounding non-2xx",
                extra={"status_code": response.status_code, "body": response.text[:300]},
            )
            return []

        try:
            body = response.json()
        except ValueError:
            logger.warning("Enrichment grounding returned non-JSON body")
            return []

        return parse_enrichment_results(body)

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is not None:
            return self._client.post(self._endpoint, json=payload, timeout=self._timeout)
        return httpx.post(self._endpoint, json=payload, timeout=self._timeout)


def parse_enrichment_results(body: object) -> list[WebGroundSnippet]:
    if not isinstance(body, dict):
        return []
    raw = body.get("snippets")
    if not isinstance(raw, list):
        return []
    snippets: list[WebGroundSnippet] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _as_str(item.get("title"))
        url = _as_str(item.get("url"))
        content = _as_str(item.get("content"))
        if not url and not content:
            continue
        snippets.append(WebGroundSnippet(title=title, url=url, content=content))
    return snippets


def _as_str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""
