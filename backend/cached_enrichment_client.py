"""Cache wrapper for the enrichment-layer snippets producer.

Sits between ``tutorial_session`` and ``EnrichmentSnippetsProducer``.
Same duck-typed surface (``ground`` / ``ground_multimodal``) so the
session never has to know caching exists.

The MULTIMODAL path is no longer cached here — the enrichment-layer
owns L1 (multimodal plan) and L2 (final snippets) inside
``/plan_queries`` and ``/snippets_for``. ``ground_multimodal`` just
delegates.

The SINGLE-QUERY path still caches here:

1. **NegativeCache** — short-TTL memo of "we tried this and got
   nothing." First check on the read path.
2. **QueryCache** — semantic match on the query text within an
   application partition.
3. **Upstream** — the real ``EnrichmentSnippetsProducer``.

Failure isolation: any unexpected exception in the cache layer is
logged and treated as a miss. A broken cache must never break grounding.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict

from backend.enrichment_client import (
    EnrichmentSnippetsProducer,
    MultimodalGroundResult,
)
from backend.grounding_cache import (
    AppPartition,
    CacheStats,
    NegativeCache,
    QueryCache,
)
from backend.images import UploadedImage
from backend.web_ground import DEFAULT_MAX_RESULTS, WebGroundSnippet


logger = logging.getLogger(__name__)


class CachedEnrichmentSnippetsProducer(EnrichmentSnippetsProducer):
    """``EnrichmentSnippetsProducer`` with positive + negative caching.

    Inherits from the concrete producer so callers (and the
    ``isinstance`` check in ``tutorial_session``) treat it identically.
    Initialisation does NOT re-run the parent constructor: we wrap a
    pre-built inner producer to keep config in one place.
    """

    def __init__(
        self,
        inner: EnrichmentSnippetsProducer,
        *,
        query_cache: QueryCache,
        negative_cache: NegativeCache,
        stats: CacheStats | None = None,
    ) -> None:
        self._inner = inner
        self._query_cache = query_cache
        self._negative_cache = negative_cache
        self._stats = stats
        # Mirror inner's public configuration so any introspection works
        # the same way as on the raw producer.
        self._endpoint = inner._endpoint
        self._num_sources = inner._num_sources
        self._timeout = inner._timeout
        self._multimodal_timeout = inner._multimodal_timeout
        self._client = inner._client

    # ---- ground (single-query) --------------------------------------------

    def ground(
        self,
        query: str,
        *,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> list[WebGroundSnippet]:
        normalized = query.strip()
        if not normalized:
            return []

        session_id = _session_id_for_logs()
        partition = AppPartition.unknown()

        # 1) Negative cache: did we just try this and get nothing?
        if self._safely(
            self._negative_cache.is_known_miss,
            partition, normalized, session_id=session_id,
        ):
            logger.info(
                "[cache] grounding short-circuited by negative cache",
                extra={
                    "session_id": session_id, "layer": "negative",
                    "key_preview": normalized[:60],
                },
            )
            return []

        # 2) Positive cache: a paraphrase we've grounded recently.
        cached = self._safely(
            self._query_cache.get,
            partition, normalized, session_id=session_id,
        )
        if cached is not None:
            return _snippets_from_cache_value(cached)

        # 3) Upstream call.
        started = time.perf_counter()
        snippets = self._inner.ground(normalized, max_results=max_results)
        upstream_ms = round((time.perf_counter() - started) * 1000, 2)

        if snippets:
            self._safely(
                self._query_cache.put,
                partition, normalized,
                _snippets_to_cache_value(snippets),
                session_id=session_id,
                upstream_ms=upstream_ms,
            )
        else:
            self._safely(
                self._negative_cache.record_miss,
                partition, normalized,
                session_id=session_id,
                upstream_ms=upstream_ms,
            )
        return snippets

    # ---- ground_multimodal -------------------------------------------------
    #
    # The enrichment-layer now owns the multimodal cache path (L1 + L2,
    # see docker/enrichment-layer/src/enrichment/cache/grounding_cache.py).
    # The backend just delegates — no per-query population, no partition
    # tracking, no provenance fan-out. Leaving the override here so the
    # method-resolution order keeps backend logs consistent.

    def ground_multimodal(
        self,
        request_text: str,
        image: UploadedImage,
        *,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> MultimodalGroundResult:
        return self._inner.ground_multimodal(
            request_text, image, max_results=max_results,
        )

    # ---- session lifecycle -------------------------------------------------

    def emit_session_summary(self, *, session_id: str) -> None:
        self._safely(self._query_cache.emit_session_summary, session_id=session_id)
        self._safely(self._negative_cache.emit_session_summary, session_id=session_id)

    # ---- internals --------------------------------------------------------

    def _safely(self, fn, *args, **kwargs):
        """Run a cache method, swallowing exceptions so a broken cache
        layer can never break grounding."""
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "[cache] wrapper swallowed exception",
                extra={"fn": getattr(fn, "__qualname__", repr(fn))},
            )
            return None


def _snippets_to_cache_value(
    snippets: list[WebGroundSnippet],
) -> list[dict]:
    """Cache stores plain dicts so it stays JSON-clean and never holds
    references to live objects."""
    return [asdict(s) for s in snippets]


def _snippets_from_cache_value(value: list) -> list[WebGroundSnippet]:
    out: list[WebGroundSnippet] = []
    for item in value:
        if isinstance(item, WebGroundSnippet):
            out.append(item)
        elif isinstance(item, dict):
            out.append(
                WebGroundSnippet(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                )
            )
    return out


def _session_id_for_logs() -> str:
    """The cache layer logs need a session id, but the producer surface
    doesn't carry one. The caller in ``tutorial_session`` already logs
    its own session id around every grounding call, so threading a real
    id through would mean changing the duck-typed surface for every
    producer in the project. ``unknown`` keeps the log schema uniform
    until that refactor lands."""
    return "unknown"
