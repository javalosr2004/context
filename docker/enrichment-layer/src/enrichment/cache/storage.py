"""Generic key/value storage abstraction for grounding caches.

The Protocol is intentionally domain-agnostic — it knows nothing about
queries, URLs, embeddings, or TTLs-by-domain. Layer-specific behavior
(key normalization, paraphrase matching, negative caching) lives in the
wrappers in ``grounding_cache.py``.

Storage is in-memory only for the MVP. Swapping in Redis / SQLite is a
single-file change because nothing leaks out of this module.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Generic, Hashable, Protocol, TypeVar

K = TypeVar("K", bound=Hashable, contravariant=True)
V = TypeVar("V")
# A non-contravariant alias for the concrete in-memory implementation,
# which (unlike the Protocol) both reads and writes K.
_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


@dataclass
class StorageStats:
    hits: int = 0
    misses: int = 0
    puts: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0
    extra: dict[str, int] = field(default_factory=dict)


class StorageProvider(Protocol, Generic[K, V]):
    def get(self, key: K) -> V | None: ...
    def put(self, key: K, value: V, *, ttl_seconds: float | None = None) -> None: ...
    def delete(self, key: K) -> None: ...
    def stats(self) -> StorageStats: ...


@dataclass
class _Entry(Generic[_V]):
    value: _V
    expires_at: float | None  # None = never expires


class InMemoryStorage(Generic[_K, _V]):
    """TTL + max-size LRU eviction. Process-local. Thread-safe."""

    def __init__(self, *, max_size: int = 1024, default_ttl_seconds: float | None = None) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._data: OrderedDict[_K, _Entry[_V]] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = StorageStats(max_size=max_size)

    def get(self, key: _K) -> _V | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            if entry.expires_at is not None and entry.expires_at < time.monotonic():
                self._data.pop(key, None)
                self._stats.size = len(self._data)
                self._stats.misses += 1
                return None
            self._data.move_to_end(key)
            self._stats.hits += 1
            return entry.value

    def put(self, key: _K, value: _V, *, ttl_seconds: float | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = time.monotonic() + ttl if ttl is not None else None
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = _Entry(value=value, expires_at=expires_at)
            self._stats.puts += 1
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)
                self._stats.evictions += 1
            self._stats.size = len(self._data)

    def delete(self, key: _K) -> None:
        with self._lock:
            if self._data.pop(key, None) is not None:
                self._stats.size = len(self._data)

    def stats(self) -> StorageStats:
        with self._lock:
            return StorageStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                puts=self._stats.puts,
                evictions=self._stats.evictions,
                size=len(self._data),
                max_size=self._max_size,
                extra=dict(self._stats.extra),
            )

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._stats.size = 0
