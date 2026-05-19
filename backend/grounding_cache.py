"""Semantic cache for web-grounding results.

First slice: the query-level cache. The enrichment layer normalizes
free-form user goals into a small set of canonical search queries; this
cache keys on the embedding of each query (plus an application partition)
so paraphrased goals reuse prior grounding work.

Strictly additive: every code path catches its own failures and degrades
to "cache miss." A broken cache must never break grounding.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from backend.embeddings_client import EmbeddingsClient, cosine


logger = logging.getLogger(__name__)


# ---- Time injection (so tests don't sleep) --------------------------------

class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


# ---- Application partition -------------------------------------------------

@dataclass(frozen=True)
class AppPartition:
    """Coarse environment fingerprint used to isolate cache namespaces.

    A snippet for "deploy to cloud run" on Colab is not interchangeable
    with the same query on VS Code, so the partition is part of the key.
    """

    app_slug: str | None
    os_slug: str | None

    @classmethod
    def from_enrichment(
        cls, application: str | None, environment: str | None
    ) -> "AppPartition":
        return cls(_slugify(application), _slugify(environment))

    @classmethod
    def unknown(cls) -> "AppPartition":
        return cls(None, None)

    def slug(self) -> str:
        app = self.app_slug or "unknown"
        os_ = self.os_slug or "unknown"
        return f"{app}:{os_}"


def _slugify(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    return "-".join(cleaned.split())


# ---- Entry -----------------------------------------------------------------

V = TypeVar("V")


@dataclass
class _Entry(Generic[V]):
    partition: AppPartition
    key_preview: str
    embedding: tuple[float, ...]
    value: V
    stored_at: float
    ttl_seconds: float

    def is_fresh(self, now: float) -> bool:
        return (now - self.stored_at) < self.ttl_seconds

    def remaining_ttl(self, now: float) -> float:
        return max(0.0, self.ttl_seconds - (now - self.stored_at))


# ---- Aggregate stats (for session_summary rollup) -------------------------

@dataclass
class LayerStats:
    hits: int = 0
    misses: int = 0
    near_misses: int = 0
    stores: int = 0
    evictions: int = 0
    errors: int = 0
    upstream_ms_saved_estimate: float = 0.0


@dataclass
class CacheStats:
    by_layer: dict[str, LayerStats] = field(default_factory=dict)

    def layer(self, name: str) -> LayerStats:
        if name not in self.by_layer:
            self.by_layer[name] = LayerStats()
        return self.by_layer[name]


# ---- Query cache -----------------------------------------------------------

DEFAULT_QUERY_TTL_SECONDS = 24 * 60 * 60
DEFAULT_QUERY_SIMILARITY_THRESHOLD = 0.88
DEFAULT_MAX_QUERY_ENTRIES = 2048
KEY_PREVIEW_MAX_LEN = 60
NEAR_MISS_MARGIN = 0.05  # log a near_miss when within this much of threshold


class QueryCache:
    """Semantic cache: (partition, embedding(query)) -> ranked URL list.

    Lookups embed the incoming query, scan entries in the same partition,
    and return the value of the top match if cosine similarity meets the
    threshold. Below-threshold matches close to the bar are logged as
    near-misses (DEBUG) to support tuning from real data.

    Eviction is opportunistic: expired entries are dropped on access, and
    LRU when ``max_entries`` is exceeded on store.
    """

    LAYER_NAME = "query"

    def __init__(
        self,
        *,
        embeddings: EmbeddingsClient,
        clock: Clock | None = None,
        stats: CacheStats | None = None,
        ttl_seconds: float = DEFAULT_QUERY_TTL_SECONDS,
        similarity_threshold: float = DEFAULT_QUERY_SIMILARITY_THRESHOLD,
        max_entries: int = DEFAULT_MAX_QUERY_ENTRIES,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not 0.0 < similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be in (0, 1]")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._embeddings = embeddings
        self._clock = clock or SystemClock()
        self._stats = stats or CacheStats()
        self._ttl = ttl_seconds
        self._threshold = similarity_threshold
        self._max_entries = max_entries
        # MRU at end. Brute-force scan is fine at this scale; swap for an
        # ANN index when the entry count justifies the dependency.
        self._entries: list[_Entry[list[str]]] = []

    # ---- Public API --------------------------------------------------------

    def get(
        self,
        partition: AppPartition,
        query: str,
        *,
        session_id: str,
    ) -> list[str] | None:
        normalized = query.strip()
        if not normalized:
            self._log_miss(partition, normalized, session_id, elapsed_ms=0.0,
                          reason="empty_query")
            return None

        started = time.perf_counter()
        embedding = self._embed(normalized, session_id=session_id)
        if embedding is None:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            self._stats.layer(self.LAYER_NAME).errors += 1
            self._stats.layer(self.LAYER_NAME).misses += 1
            logger.warning(
                "[cache] query error",
                extra={
                    "layer": self.LAYER_NAME, "event": "error",
                    "session_id": session_id, "partition": partition.slug(),
                    "key_preview": _preview(normalized),
                    "reason": "embedder_failed",
                    "fallback": "treated_as_miss",
                    "elapsed_ms": elapsed_ms,
                },
            )
            return None

        now = self._clock.now()
        self._evict_expired(now)

        candidates: list[tuple[_Entry[list[str]], float]] = []
        for entry in self._entries:
            if entry.partition != partition:
                continue
            sim = cosine(list(embedding), list(entry.embedding))
            candidates.append((entry, sim))

        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

        if not candidates:
            self._log_miss(partition, normalized, session_id,
                          elapsed_ms=elapsed_ms, reason="cold_partition")
            return None

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        best_entry, best_sim = candidates[0]

        if best_sim >= self._threshold:
            self._touch(best_entry)
            self._stats.layer(self.LAYER_NAME).hits += 1
            logger.info(
                "[cache] query hit",
                extra={
                    "layer": self.LAYER_NAME, "event": "hit",
                    "session_id": session_id, "partition": partition.slug(),
                    "key_preview": _preview(normalized),
                    "matched_key_preview": best_entry.key_preview,
                    "similarity": round(best_sim, 4),
                    "threshold": self._threshold,
                    "entry_age_seconds": round(now - best_entry.stored_at, 2),
                    "ttl_remaining_seconds": round(best_entry.remaining_ttl(now), 2),
                    "elapsed_ms": elapsed_ms,
                    "cache_size": len(self._entries),
                },
            )
            return list(best_entry.value)

        # Below threshold. Log near-miss at DEBUG with top candidates so
        # threshold tuning can happen from logs alone.
        if best_sim >= self._threshold - NEAR_MISS_MARGIN:
            self._stats.layer(self.LAYER_NAME).near_misses += 1
            logger.debug(
                "[cache] query near_miss",
                extra={
                    "layer": self.LAYER_NAME, "event": "near_miss",
                    "session_id": session_id, "partition": partition.slug(),
                    "key_preview": _preview(normalized),
                    "top_candidates": [
                        (e.key_preview, round(s, 4)) for e, s in candidates[:3]
                    ],
                    "threshold": self._threshold,
                    "elapsed_ms": elapsed_ms,
                },
            )

        self._log_miss(partition, normalized, session_id,
                      elapsed_ms=elapsed_ms, reason="below_threshold",
                      best_similarity=round(best_sim, 4))
        return None

    def put(
        self,
        partition: AppPartition,
        query: str,
        urls: list[str],
        *,
        session_id: str,
        upstream_ms: float | None = None,
    ) -> None:
        normalized = query.strip()
        if not normalized or not urls:
            return
        embedding = self._embed(normalized, session_id=session_id)
        if embedding is None:
            return  # already logged as error in _embed path

        now = self._clock.now()
        self._evict_expired(now)

        entry: _Entry[list[str]] = _Entry(
            partition=partition,
            key_preview=_preview(normalized),
            embedding=embedding,
            value=list(urls),
            stored_at=now,
            ttl_seconds=self._ttl,
        )
        self._entries.append(entry)
        self._stats.layer(self.LAYER_NAME).stores += 1
        if upstream_ms is not None:
            self._stats.layer(
                self.LAYER_NAME
            ).upstream_ms_saved_estimate += upstream_ms  # estimate for next hit

        logger.info(
            "[cache] query store",
            extra={
                "layer": self.LAYER_NAME, "event": "store",
                "session_id": session_id, "partition": partition.slug(),
                "key_preview": entry.key_preview,
                "url_count": len(urls),
                "cache_size": len(self._entries),
            },
        )

        if len(self._entries) > self._max_entries:
            evicted = self._entries.pop(0)  # LRU (oldest accessed)
            self._stats.layer(self.LAYER_NAME).evictions += 1
            logger.info(
                "[cache] query evict",
                extra={
                    "layer": self.LAYER_NAME, "event": "evict",
                    "session_id": session_id,
                    "partition": evicted.partition.slug(),
                    "key_preview": evicted.key_preview,
                    "entry_age_seconds": round(now - evicted.stored_at, 2),
                    "reason": "lru",
                    "cache_size": len(self._entries),
                },
            )

    def emit_session_summary(self, *, session_id: str) -> None:
        layer = self._stats.layer(self.LAYER_NAME)
        logger.info(
            "[cache] session_summary",
            extra={
                "layer": self.LAYER_NAME, "event": "session_summary",
                "session_id": session_id,
                "hits": layer.hits, "misses": layer.misses,
                "near_misses": layer.near_misses,
                "stores": layer.stores, "evictions": layer.evictions,
                "errors": layer.errors,
                "upstream_ms_saved_estimate": round(
                    layer.upstream_ms_saved_estimate, 2
                ),
                "cache_size": len(self._entries),
            },
        )

    # ---- Internals ---------------------------------------------------------

    def _embed(self, text: str, *, session_id: str) -> tuple[float, ...] | None:
        try:
            vectors = self._embeddings.embed_batch([text])
        except Exception:
            logger.exception(
                "[cache] query embedder_raised",
                extra={
                    "layer": self.LAYER_NAME, "session_id": session_id,
                    "key_preview": _preview(text),
                },
            )
            return None
        if not vectors or len(vectors) != 1 or not vectors[0]:
            return None
        return tuple(vectors[0])

    def _evict_expired(self, now: float) -> None:
        fresh: list[_Entry[list[str]]] = []
        for entry in self._entries:
            if entry.is_fresh(now):
                fresh.append(entry)
            else:
                self._stats.layer(self.LAYER_NAME).evictions += 1
                logger.info(
                    "[cache] query evict",
                    extra={
                        "layer": self.LAYER_NAME, "event": "evict",
                        "partition": entry.partition.slug(),
                        "key_preview": entry.key_preview,
                        "entry_age_seconds": round(now - entry.stored_at, 2),
                        "reason": "ttl",
                    },
                )
        self._entries = fresh

    def _touch(self, entry: _Entry[list[str]]) -> None:
        try:
            self._entries.remove(entry)
        except ValueError:
            return
        self._entries.append(entry)

    def _log_miss(
        self,
        partition: AppPartition,
        query: str,
        session_id: str,
        *,
        elapsed_ms: float,
        reason: str,
        best_similarity: float | None = None,
    ) -> None:
        self._stats.layer(self.LAYER_NAME).misses += 1
        extra = {
            "layer": self.LAYER_NAME, "event": "miss",
            "session_id": session_id, "partition": partition.slug(),
            "key_preview": _preview(query),
            "reason": reason,
            "elapsed_ms": elapsed_ms,
            "cache_size": len(self._entries),
        }
        if best_similarity is not None:
            extra["best_similarity"] = best_similarity
            extra["threshold"] = self._threshold
        logger.info("[cache] query miss", extra=extra)


def _preview(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= KEY_PREVIEW_MAX_LEN:
        return cleaned
    return cleaned[: KEY_PREVIEW_MAX_LEN - 1] + "…"
