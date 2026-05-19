"""Layer-specific wrappers around generic key/value storage.

Each wrapper owns its key shape, TTL, and (in Phase 2) embedding
threshold. Storage stays domain-agnostic — this module is where the
cache becomes opinionated about grounding.

Phase 1: L3 (search hits), L4 (fetch+extract page core), L5 (page
summary). All deterministic, exact-key.

Phase 2: L1 (multimodal plan) and L2 (final snippets) will be added
here with embedding-based paraphrase lookup.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
from dataclasses import dataclass
from typing import Generic, TypeVar

from enrichment.cache.storage import InMemoryStorage

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------- per-request hit tracking (for X-Cache-L* response headers) -----
#
# A request handler calls ``reset_request_cache_state()`` on entry, then
# the layer wrappers call ``_record_hit("L3")`` / ``_record_miss("L3")``
# as they fire. The handler reads ``snapshot_request_cache_state()`` at
# the end to emit headers.

_request_state: contextvars.ContextVar[dict[str, dict[str, int]] | None] = (
    contextvars.ContextVar("enrichment_cache_request_state", default=None)
)


def reset_request_cache_state() -> None:
    _request_state.set({})


def snapshot_request_cache_state() -> dict[str, dict[str, int]]:
    return dict(_request_state.get() or {})


def _record(layer: str, kind: str) -> None:
    state = _request_state.get()
    if state is None:
        return
    bucket = state.setdefault(layer, {"hit": 0, "miss": 0})
    bucket[kind] = bucket.get(kind, 0) + 1

# Sentinel for negative caching: an empty-but-valid result that should
# not be retried for a (shorter) TTL. The cache value is the empty
# payload itself; we tag with a marker so logs can distinguish.
_NEGATIVE_TTL_SECONDS = 60 * 60  # 1h

# TTLs (per the migration plan).
_L3_TTL = 60 * 60 * 24       # 24h
_L4_TTL = 60 * 60 * 24 * 7   # 7d
_L5_TTL = 60 * 60 * 24 * 30  # 30d


# ---------- shared util ----------


def _preview(key: str, n: int = 48) -> str:
    return key if len(key) <= n else key[: n - 1] + "…"


def _norm_query(q: str) -> str:
    return " ".join((q or "").lower().split())


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()


# ---------- layer base ----------


class _Layer(Generic[T]):
    """Thin wrapper that adds [cache] logging and a layer name."""

    def __init__(
        self,
        name: str,
        *,
        max_size: int,
        default_ttl: float,
        negative_ttl: float = _NEGATIVE_TTL_SECONDS,
    ) -> None:
        self.name = name
        self._neg_ttl = negative_ttl
        self._storage: InMemoryStorage[str, T] = InMemoryStorage(
            max_size=max_size, default_ttl_seconds=default_ttl,
        )

    def get(self, key: str) -> T | None:
        value = self._storage.get(key)
        stats = self._storage.stats()
        if value is None:
            _record(self.name, "miss")
            logger.info(
                "[cache] miss layer=%s key=%s size=%d hits=%d misses=%d",
                self.name, _preview(key), stats.size, stats.hits, stats.misses,
            )
            return None
        _record(self.name, "hit")
        logger.info(
            "[cache] hit  layer=%s key=%s size=%d hits=%d misses=%d",
            self.name, _preview(key), stats.size, stats.hits, stats.misses,
        )
        return value

    def put(self, key: str, value: T, *, negative: bool = False) -> None:
        ttl = self._neg_ttl if negative else None  # None => use default
        self._storage.put(key, value, ttl_seconds=ttl)
        stats = self._storage.stats()
        logger.info(
            "[cache] put  layer=%s key=%s neg=%s size=%d puts=%d evictions=%d",
            self.name, _preview(key), negative, stats.size,
            stats.puts, stats.evictions,
        )

    def stats(self):
        return self._storage.stats()


# ---------- L3 — search hits, per query ----------

# Stored as list[dict] to stay storage-agnostic (decoupled from
# SearchHit's pydantic model). The L3 wrapper converts at the boundary.

@dataclass(frozen=True)
class _L3Cache:
    layer: _Layer[list[dict]]

    def get(self, query: str) -> list[dict] | None:
        return self.layer.get(_norm_query(query))

    def put(self, query: str, hits: list[dict]) -> None:
        self.layer.put(_norm_query(query), hits, negative=not hits)


# ---------- L4 — fetched+extracted page core, per URL ----------

@dataclass(frozen=True)
class _L4Cache:
    layer: _Layer[dict]  # serialized PageCore

    def get(self, url: str) -> dict | None:
        return self.layer.get(url)

    def put(self, url: str, page_core: dict) -> None:
        self.layer.put(url, page_core, negative=not page_core)


# ---------- L5 — page summary, per (content_hash, goal, application) ----------

@dataclass(frozen=True)
class _L5Cache:
    layer: _Layer[str]

    @staticmethod
    def _key(content_hash: str, goal: str | None, application: str | None) -> str:
        return _sha(
            content_hash or "",
            _norm_query(goal or ""),
            _norm_query(application or ""),
        )

    def get(self, content_hash: str, goal: str | None, application: str | None) -> str | None:
        if not content_hash:
            return None
        return self.layer.get(self._key(content_hash, goal, application))

    def put(self, content_hash: str, goal: str | None, application: str | None, snippet: str) -> None:
        if not content_hash:
            return
        self.layer.put(
            self._key(content_hash, goal, application),
            snippet,
            negative=not snippet,
        )


# ---------- module-scope singletons ----------

l3_search = _L3Cache(layer=_Layer("L3", max_size=4096, default_ttl=_L3_TTL))
l4_page = _L4Cache(layer=_Layer("L4", max_size=4096, default_ttl=_L4_TTL))
l5_summary = _L5Cache(layer=_Layer("L5", max_size=8192, default_ttl=_L5_TTL))


# ---------- embedding-based paraphrase cache (L1 + L2) ----------

_L1_TTL = 60 * 60 * 24 * 7        # 7d
_L2_TTL = 60 * 60 * 24            # 24h
_DEFAULT_COSINE_THRESHOLD = 0.92


@dataclass
class _EmbeddingEntry:
    embedding: list[float]
    value: dict
    expires_at: float | None


class _EmbeddingPartitionCache:
    """Partitioned embedding-similarity cache.

    Layout: ``{partition_key: [_EmbeddingEntry, ...]}``. Lookup embeds
    the incoming key, scans the partition, returns the value of the
    highest-cosine entry if it meets ``threshold``, otherwise miss.

    Storage is in-process; lifted to Redis later as a single replacement.
    """

    def __init__(
        self,
        name: str,
        *,
        default_ttl: float,
        threshold: float = _DEFAULT_COSINE_THRESHOLD,
        max_partitions: int = 256,
        max_entries_per_partition: int = 64,
    ) -> None:
        self.name = name
        self.default_ttl = default_ttl
        self.threshold = threshold
        self._max_partitions = max_partitions
        self._max_entries = max_entries_per_partition
        self._data: dict[str, list[_EmbeddingEntry]] = {}
        import threading
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._puts = 0

    def get(self, partition: str, text: str) -> dict | None:
        from enrichment.cache.embeddings import cosine, embed
        emb = embed(text)
        if emb is None:
            self._misses += 1
            _record(self.name, "miss")
            logger.info(
                "[cache] miss layer=%s partition=%s reason=embed_failed",
                self.name, _preview(partition),
            )
            return None
        now = _now()
        best_score = 0.0
        best_value: dict | None = None
        with self._lock:
            entries = self._data.get(partition, [])
            live = [e for e in entries if e.expires_at is None or e.expires_at > now]
            if len(live) != len(entries):
                self._data[partition] = live
            for entry in live:
                score = cosine(emb, entry.embedding)
                if score > best_score:
                    best_score = score
                    best_value = entry.value
        if best_value is not None and best_score >= self.threshold:
            self._hits += 1
            _record(self.name, "hit")
            logger.info(
                "[cache] hit  layer=%s partition=%s score=%.3f hits=%d",
                self.name, _preview(partition), best_score, self._hits,
            )
            return best_value
        self._misses += 1
        _record(self.name, "miss")
        logger.info(
            "[cache] miss layer=%s partition=%s best_score=%.3f hits=%d misses=%d",
            self.name, _preview(partition), best_score, self._hits, self._misses,
        )
        return None

    def put(self, partition: str, text: str, value: dict) -> None:
        from enrichment.cache.embeddings import embed
        emb = embed(text)
        if emb is None:
            return
        expires_at = _now() + self.default_ttl if self.default_ttl else None
        with self._lock:
            bucket = self._data.setdefault(partition, [])
            bucket.append(_EmbeddingEntry(embedding=emb, value=value, expires_at=expires_at))
            if len(bucket) > self._max_entries:
                # drop oldest
                self._data[partition] = bucket[-self._max_entries:]
            if len(self._data) > self._max_partitions:
                # drop a random partition (good enough at MVP scale)
                stale_key = next(iter(self._data))
                if stale_key != partition:
                    self._data.pop(stale_key, None)
            self._puts += 1
        logger.info(
            "[cache] put  layer=%s partition=%s puts=%d",
            self.name, _preview(partition), self._puts,
        )

    def stats(self) -> dict:
        with self._lock:
            sizes = sum(len(v) for v in self._data.values())
            return {
                "hits": self._hits,
                "misses": self._misses,
                "puts": self._puts,
                "evictions": 0,
                "size": sizes,
                "partitions": len(self._data),
                "max_size": self._max_partitions * self._max_entries,
            }


def _now() -> float:
    import time
    return time.monotonic()


# L1: multimodal plan keyed by goal text within a (perceptual-hash-of-image
# OR "no-image") partition. Cached value = MultimodalQueryPlan.model_dump().
l1_plan = _EmbeddingPartitionCache("L1", default_ttl=_L1_TTL)

# L2: final snippets keyed by sorted-joined query list within an
# (app, os) partition. Cached value = SnippetResult-shaped dict.
l2_snippets = _EmbeddingPartitionCache("L2", default_ttl=_L2_TTL)


def all_stats() -> dict[str, dict]:
    """For the Phase 4 /cache/stats endpoint and ad-hoc debugging."""
    out: dict[str, dict] = {}
    for layer in (l3_search.layer, l4_page.layer, l5_summary.layer):
        s = layer.stats()
        out[layer.name] = {
            "hits": s.hits,
            "misses": s.misses,
            "puts": s.puts,
            "evictions": s.evictions,
            "size": s.size,
            "max_size": s.max_size,
        }
    out["L1"] = l1_plan.stats()
    out["L2"] = l2_snippets.stats()
    return out


def l1_partition_for_image(image_bytes: bytes | None) -> str:
    """Cache partition derived from the screenshot.

    MVP: sha256 of raw bytes. Open question in the migration plan is
    whether to use a perceptual hash on the downscaled image instead —
    deferred until the backend's downscaler is reachable from here.
    """
    if not image_bytes:
        return "no-image"
    return hashlib.sha256(image_bytes).hexdigest()


def l2_partition_for_context(application: str | None, environment: str | None) -> str:
    return _sha(_norm_query(application or ""), _norm_query(environment or ""))


def l2_text_for_queries(queries: list[str]) -> str:
    return " | ".join(sorted(_norm_query(q) for q in queries if q and q.strip()))
