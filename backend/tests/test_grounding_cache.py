from __future__ import annotations

import logging
import math

import pytest

from backend.grounding_cache import (
    AppPartition,
    CacheStats,
    DEFAULT_QUERY_SIMILARITY_THRESHOLD,
    NEAR_MISS_MARGIN,
    QueryCache,
    _preview,
    _slugify,
)


# ---- Test doubles ----------------------------------------------------------

class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class StubEmbeddings:
    """Maps each unique input string to a unit vector along a fresh axis.

    Identical inputs return cosine == 1.0; distinct inputs return 0.0.
    Useful for deterministic miss vs hit tests where we don't care about
    semantic similarity beyond exact match.
    """

    def __init__(self) -> None:
        self._axis_by_text: dict[str, int] = {}
        self.calls: list[list[str]] = []
        self.dim = 64

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        out: list[list[float]] = []
        for text in texts:
            axis = self._axis_by_text.setdefault(text, len(self._axis_by_text))
            vec = [0.0] * self.dim
            if axis < self.dim:
                vec[axis] = 1.0
            out.append(vec)
        return out


class ManualEmbeddings:
    """Returns exactly the vectors the test prepared. Lets a test stage
    paraphrase-style similarities by hand."""

    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.calls: list[list[str]] = []

    def stage(self, text: str, vector: list[float]) -> None:
        self.vectors[text] = vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vectors[t] for t in texts]


class FailingEmbeddings:
    def __init__(self, *, raise_exc: bool = False) -> None:
        self.raise_exc = raise_exc
        self.calls = 0

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        del texts
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("embedder down")
        return []


# ---- Helpers ---------------------------------------------------------------

def _partition(app: str = "Google Colab", os_: str = "macOS") -> AppPartition:
    return AppPartition.from_enrichment(app, os_)


def _unit(angle_rad: float) -> list[float]:
    return [math.cos(angle_rad), math.sin(angle_rad)]


# ---- AppPartition ----------------------------------------------------------

class TestAppPartition:
    def test_slugifies_application_and_environment(self) -> None:
        p = AppPartition.from_enrichment("Google Colab", "macOS Ventura")
        assert p.app_slug == "google-colab"
        assert p.os_slug == "macos-ventura"
        assert p.slug() == "google-colab:macos-ventura"

    def test_none_inputs_become_unknown_slug(self) -> None:
        p = AppPartition.from_enrichment(None, None)
        assert p.slug() == "unknown:unknown"
        assert p == AppPartition.unknown()

    def test_whitespace_only_becomes_unknown(self) -> None:
        p = AppPartition.from_enrichment("   ", "")
        assert p == AppPartition.unknown()

    def test_partition_equality_isolates_namespaces(self) -> None:
        assert _partition("Colab") != _partition("VS Code")

    def test_slugify_collapses_internal_whitespace(self) -> None:
        assert _slugify("Google   Cloud   Run") == "google-cloud-run"


# ---- Preview ---------------------------------------------------------------

class TestPreview:
    def test_short_text_returned_verbatim(self) -> None:
        assert _preview("hello") == "hello"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        long = "x" * 200
        out = _preview(long)
        assert out.endswith("…")
        assert len(out) <= 60

    def test_whitespace_stripped(self) -> None:
        assert _preview("  hi  ") == "hi"


# ---- QueryCache: construction validation ----------------------------------

class TestQueryCacheConstruction:
    def test_rejects_zero_ttl(self) -> None:
        with pytest.raises(ValueError):
            QueryCache(embeddings=StubEmbeddings(), ttl_seconds=0)

    def test_rejects_threshold_above_one(self) -> None:
        with pytest.raises(ValueError):
            QueryCache(embeddings=StubEmbeddings(), similarity_threshold=1.5)

    def test_rejects_zero_max_entries(self) -> None:
        with pytest.raises(ValueError):
            QueryCache(embeddings=StubEmbeddings(), max_entries=0)


# ---- QueryCache: basic hit/miss -------------------------------------------

class TestQueryCacheBasic:
    def test_empty_cache_misses(self) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        assert cache.get(_partition(), "deploy app", session_id="s1") is None

    def test_put_then_get_exact_hits(self) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        cache.put(_partition(), "deploy app", ["https://a"], session_id="s1")
        assert cache.get(_partition(), "deploy app", session_id="s1") == ["https://a"]

    def test_returned_list_is_a_copy_not_internal_reference(self) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        cache.put(_partition(), "q", ["https://a"], session_id="s1")
        got = cache.get(_partition(), "q", session_id="s1")
        assert got is not None
        got.append("https://mutated")
        again = cache.get(_partition(), "q", session_id="s1")
        assert again == ["https://a"]

    def test_empty_query_misses_without_calling_embedder(self) -> None:
        emb = StubEmbeddings()
        cache = QueryCache(embeddings=emb, clock=FakeClock())
        assert cache.get(_partition(), "   ", session_id="s1") is None
        assert emb.calls == []

    def test_put_with_empty_urls_is_noop(self) -> None:
        emb = StubEmbeddings()
        cache = QueryCache(embeddings=emb, clock=FakeClock())
        cache.put(_partition(), "q", [], session_id="s1")
        assert cache.get(_partition(), "q", session_id="s1") is None


# ---- QueryCache: partition isolation --------------------------------------

class TestQueryCachePartitions:
    def test_same_query_different_partition_misses(self) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        cache.put(_partition("Colab"), "deploy", ["url1"], session_id="s1")
        assert cache.get(_partition("VS Code"), "deploy", session_id="s1") is None

    def test_unknown_partition_isolated_from_known(self) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        cache.put(AppPartition.unknown(), "q", ["u"], session_id="s1")
        assert cache.get(_partition("Colab"), "q", session_id="s1") is None


# ---- QueryCache: semantic threshold ---------------------------------------

class TestQueryCacheSemantic:
    def test_above_threshold_paraphrase_hits(self) -> None:
        emb = ManualEmbeddings()
        # Two vectors with cosine == cos(0.1 rad) ≈ 0.995, above default 0.88.
        emb.stage("stored", _unit(0.0))
        emb.stage("paraphrase", _unit(0.1))
        cache = QueryCache(embeddings=emb, clock=FakeClock(),
                           similarity_threshold=0.88)
        cache.put(_partition(), "stored", ["url1"], session_id="s1")
        got = cache.get(_partition(), "paraphrase", session_id="s1")
        assert got == ["url1"]

    def test_below_threshold_misses(self) -> None:
        emb = ManualEmbeddings()
        # cosine ≈ 0.707; below default 0.88.
        emb.stage("a", _unit(0.0))
        emb.stage("b", _unit(math.pi / 4))
        cache = QueryCache(embeddings=emb, clock=FakeClock(),
                           similarity_threshold=0.88)
        cache.put(_partition(), "a", ["url1"], session_id="s1")
        assert cache.get(_partition(), "b", session_id="s1") is None

    def test_near_miss_logged_but_returns_none(self, caplog) -> None:
        emb = ManualEmbeddings()
        # cosine ≈ 0.866, just below 0.88 but within the near-miss margin.
        emb.stage("a", _unit(0.0))
        emb.stage("b", _unit(math.pi / 6))
        cache = QueryCache(embeddings=emb, clock=FakeClock(),
                           similarity_threshold=0.88)
        cache.put(_partition(), "a", ["url1"], session_id="s1")
        with caplog.at_level(logging.DEBUG, logger="backend.grounding_cache"):
            assert cache.get(_partition(), "b", session_id="s1") is None
        near_miss_records = [
            r for r in caplog.records
            if getattr(r, "event", None) == "near_miss"
        ]
        assert len(near_miss_records) == 1


# ---- QueryCache: TTL & eviction -------------------------------------------

class TestQueryCacheTtl:
    def test_entry_expires_after_ttl(self) -> None:
        clock = FakeClock(t=1000.0)
        cache = QueryCache(embeddings=StubEmbeddings(), clock=clock,
                           ttl_seconds=60)
        cache.put(_partition(), "q", ["u"], session_id="s1")
        clock.advance(59)
        assert cache.get(_partition(), "q", session_id="s1") == ["u"]
        clock.advance(2)
        assert cache.get(_partition(), "q", session_id="s1") is None

    def test_expired_entry_evicted_and_logged(self, caplog) -> None:
        clock = FakeClock(t=0.0)
        cache = QueryCache(embeddings=StubEmbeddings(), clock=clock,
                           ttl_seconds=10)
        cache.put(_partition(), "q", ["u"], session_id="s1")
        clock.advance(100)
        with caplog.at_level(logging.INFO, logger="backend.grounding_cache"):
            cache.get(_partition(), "q", session_id="s1")
        evict_records = [
            r for r in caplog.records
            if getattr(r, "event", None) == "evict"
            and getattr(r, "reason", None) == "ttl"
        ]
        assert len(evict_records) == 1


class TestQueryCacheLru:
    def test_lru_eviction_on_overflow(self) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock(),
                           max_entries=2)
        cache.put(_partition(), "a", ["ua"], session_id="s1")
        cache.put(_partition(), "b", ["ub"], session_id="s1")
        # Touch 'a' so 'b' becomes least-recently-used.
        assert cache.get(_partition(), "a", session_id="s1") == ["ua"]
        cache.put(_partition(), "c", ["uc"], session_id="s1")
        # 'b' should have been evicted; 'a' and 'c' remain.
        assert cache.get(_partition(), "b", session_id="s1") is None
        assert cache.get(_partition(), "a", session_id="s1") == ["ua"]
        assert cache.get(_partition(), "c", session_id="s1") == ["uc"]


# ---- QueryCache: failure isolation ----------------------------------------

class TestQueryCacheFailureIsolation:
    def test_empty_embedding_response_treated_as_miss(self, caplog) -> None:
        cache = QueryCache(embeddings=FailingEmbeddings(), clock=FakeClock())
        with caplog.at_level(logging.WARNING, logger="backend.grounding_cache"):
            assert cache.get(_partition(), "q", session_id="s1") is None
        error_records = [
            r for r in caplog.records
            if getattr(r, "event", None) == "error"
        ]
        assert len(error_records) == 1

    def test_embedder_exception_does_not_propagate(self) -> None:
        cache = QueryCache(embeddings=FailingEmbeddings(raise_exc=True),
                           clock=FakeClock())
        assert cache.get(_partition(), "q", session_id="s1") is None

    def test_put_with_failing_embedder_silently_drops(self) -> None:
        cache = QueryCache(embeddings=FailingEmbeddings(raise_exc=True),
                           clock=FakeClock())
        cache.put(_partition(), "q", ["u"], session_id="s1")
        # Nothing stored; get returns None as expected.
        cache_size = len(cache._entries)
        assert cache_size == 0


# ---- QueryCache: logging contract -----------------------------------------

class TestQueryCacheLogging:
    def test_hit_emits_structured_fields(self, caplog) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        cache.put(_partition(), "q", ["u"], session_id="s1")
        with caplog.at_level(logging.INFO, logger="backend.grounding_cache"):
            cache.get(_partition(), "q", session_id="s1")
        hits = [r for r in caplog.records if getattr(r, "event", None) == "hit"]
        assert len(hits) == 1
        r = hits[0]
        assert r.layer == "query"
        assert r.partition == "google-colab:macos"
        assert r.session_id == "s1"
        assert r.similarity == pytest.approx(1.0)
        assert r.threshold == DEFAULT_QUERY_SIMILARITY_THRESHOLD
        assert r.entry_age_seconds == 0.0
        assert "elapsed_ms" in r.__dict__

    def test_session_summary_aggregates_counts(self, caplog) -> None:
        stats = CacheStats()
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock(),
                           stats=stats)
        cache.put(_partition(), "a", ["u1"], session_id="s1")
        cache.get(_partition(), "a", session_id="s1")            # hit
        cache.get(_partition(), "missing", session_id="s1")       # miss
        with caplog.at_level(logging.INFO, logger="backend.grounding_cache"):
            cache.emit_session_summary(session_id="s1")
        summary = [
            r for r in caplog.records
            if getattr(r, "event", None) == "session_summary"
        ]
        assert len(summary) == 1
        r = summary[0]
        assert r.hits == 1
        assert r.misses == 1
        assert r.stores == 1

    def test_key_preview_never_exceeds_cap(self, caplog) -> None:
        cache = QueryCache(embeddings=StubEmbeddings(), clock=FakeClock())
        long_query = "deploy " * 200
        with caplog.at_level(logging.INFO, logger="backend.grounding_cache"):
            cache.get(_partition(), long_query, session_id="s1")
        miss = [r for r in caplog.records if getattr(r, "event", None) == "miss"]
        assert miss
        assert len(miss[0].key_preview) <= 60


# ---- QueryCache: sanity on margin constant --------------------------------

class TestNearMissMarginSanity:
    def test_near_miss_margin_is_positive_and_small(self) -> None:
        assert 0 < NEAR_MISS_MARGIN < 0.2
