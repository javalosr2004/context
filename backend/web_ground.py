"""Web grounding for the planner.

The planner produces a coarse hypothesis plan from the user's goal. Without
external context it relies entirely on the model's pretraining, which goes
stale and hallucinates labels. ``WebGroundProducer`` is a thin abstraction
over "fetch a few short, citeable snippets for this query" so the planner
can call a search backend without knowing which one.

The default implementation hits Tavily's ``/search`` endpoint; a null
producer is provided for tests and for environments without an API key.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx


logger = logging.getLogger(__name__)


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT_SECONDS = 6.0


@dataclass(frozen=True)
class WebGroundSnippet:
    title: str
    url: str
    content: str


class WebGroundProducer(Protocol):
    def ground(self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS) -> list[WebGroundSnippet]:
        ...


class NullWebGroundProducer:
    """No-op producer. Use when grounding is disabled or unconfigured."""

    def ground(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> list[WebGroundSnippet]:
        return []


class TavilyWebGroundProducer:
    """Grounds a query via Tavily's search API.

    Failures are swallowed and logged: grounding is a soft enhancement,
    never a hard dependency of the planner.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = TAVILY_SEARCH_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        search_depth: str = "basic",
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("TavilyWebGroundProducer requires a non-empty api_key")
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout_seconds
        self._search_depth = search_depth
        self._client = client

    def ground(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> list[WebGroundSnippet]:
        query = query.strip()
        if not query:
            return []

        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": self._search_depth,
            "max_results": max_results,
        }

        try:
            response = self._post(payload)
        except httpx.HTTPError as error:
            logger.warning(
                "Tavily grounding request failed",
                extra={"error": str(error), "query_chars": len(query)},
            )
            return []

        if response.status_code >= 400:
            logger.warning(
                "Tavily grounding non-2xx",
                extra={
                    "status_code": response.status_code,
                    "body": response.text[:300],
                },
            )
            return []

        try:
            body = response.json()
        except ValueError:
            logger.warning("Tavily grounding returned non-JSON body")
            return []

        return parse_tavily_results(body)

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        if self._client is not None:
            return self._client.post(self._endpoint, json=payload, timeout=self._timeout)
        return httpx.post(self._endpoint, json=payload, timeout=self._timeout)


def parse_tavily_results(body: object) -> list[WebGroundSnippet]:
    if not isinstance(body, dict):
        return []
    raw_results = body.get("results")
    if not isinstance(raw_results, list):
        return []
    snippets: list[WebGroundSnippet] = []
    for item in raw_results:
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


def format_snippets_for_prompt(snippets: list[WebGroundSnippet]) -> str:
    """Render snippets as a compact bulleted block for the LLM prompt.

    Returns the empty string when there is nothing to add, so callers can
    concatenate unconditionally.
    """
    if not snippets:
        return ""
    lines = ["Web context (use as factual grounding, ignore if irrelevant):"]
    for index, snippet in enumerate(snippets, start=1):
        header = snippet.title or snippet.url or f"source {index}"
        lines.append(f"[{index}] {header}")
        if snippet.url:
            lines.append(f"    url: {snippet.url}")
        if snippet.content:
            lines.append(f"    {snippet.content}")
    return "\n".join(lines)


def web_ground_producer_from_environment(
    environment: Mapping[str, str] | None = None,
) -> WebGroundProducer:
    env = environment if environment is not None else os.environ

    enrichment_url = env.get("ENRICHMENT_LAYER_URL", "").strip()
    if enrichment_url:
        from backend.enrichment_client import EnrichmentSnippetsProducer

        try:
            num_sources = int(env.get("ENRICHMENT_NUM_SOURCES", "5"))
        except ValueError:
            num_sources = 5
        inner = EnrichmentSnippetsProducer(
            base_url=enrichment_url, num_sources=num_sources,
        )
        return _maybe_wrap_with_cache(inner, env)

    api_key = env.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return NullWebGroundProducer()
    search_depth = env.get("TAVILY_SEARCH_DEPTH", "basic").strip() or "basic"
    return TavilyWebGroundProducer(api_key=api_key, search_depth=search_depth)


def _maybe_wrap_with_cache(
    inner: WebGroundProducer,
    env: Mapping[str, str],
) -> WebGroundProducer:
    """Wrap the enrichment producer with a semantic cache if the
    feature flag is on AND embedding credentials are available.

    Failure-isolated: any setup error returns the raw producer so a
    misconfigured cache cannot break grounding.
    """
    if env.get("ENRICHMENT_CACHE_ENABLED", "").strip().lower() not in (
        "1", "true", "yes", "on",
    ):
        return inner

    openai_key = (
        env.get("EMBEDDINGS_API_KEY", "").strip()
        or env.get("OPENAI_API_KEY", "").strip()
    )
    if not openai_key:
        logger.info(
            "[cache] disabled — ENRICHMENT_CACHE_ENABLED set but no "
            "EMBEDDINGS_API_KEY/OPENAI_API_KEY found; running uncached",
        )
        return inner

    try:
        from backend.cached_enrichment_client import (
            CachedEnrichmentSnippetsProducer,
        )
        from backend.embeddings_client import OpenAIEmbeddingsClient
        from backend.grounding_cache import (
            CacheStats, NegativeCache, QueryCache,
        )

        embeddings = OpenAIEmbeddingsClient(api_key=openai_key)
        stats = CacheStats()
        query_cache = QueryCache(
            embeddings=embeddings,
            stats=stats,
            ttl_seconds=_float_env(env, "ENRICHMENT_CACHE_QUERY_TTL", 24 * 3600),
            similarity_threshold=_float_env(
                env, "ENRICHMENT_CACHE_SIMILARITY", 0.88,
            ),
        )
        negative_cache = NegativeCache(
            embeddings=embeddings,
            stats=stats,
            ttl_seconds=_float_env(env, "ENRICHMENT_CACHE_NEG_TTL", 600),
        )
        wrapped = CachedEnrichmentSnippetsProducer(
            inner=inner,
            query_cache=query_cache,
            negative_cache=negative_cache,
            stats=stats,
        )
        logger.info("[cache] enrichment grounding wrapped with semantic cache")
        return wrapped
    except Exception:
        logger.exception(
            "[cache] failed to construct cache wrapper; falling back to raw "
            "enrichment producer",
        )
        return inner


def _float_env(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "[cache] ignoring non-numeric env value",
            extra={"key": key, "value": raw, "fallback": default},
        )
        return default
