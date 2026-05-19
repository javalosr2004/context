from __future__ import annotations

import math

from backend.cached_enrichment_client import CachedEnrichmentSnippetsProducer
from backend.enrichment_client import (
    EnrichmentSnippetsProducer,
    MultimodalGroundResult,
)
from backend.grounding_cache import (
    NegativeCache,
    QueryCache,
)
from backend.images import UploadedImage
from backend.web_ground import WebGroundSnippet


# ---- Test doubles ----------------------------------------------------------

class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class ManualEmbeddings:
    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}

    def stage(self, text: str, vector: list[float]) -> None:
        self.vectors[text] = vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(t, [0.0]) for t in texts]


class StubInner(EnrichmentSnippetsProducer):
    """A fake EnrichmentSnippetsProducer that records calls and returns
    canned responses."""

    def __init__(
        self,
        *,
        ground_response: list[WebGroundSnippet] | None = None,
        multimodal_response: MultimodalGroundResult | None = None,
    ) -> None:
        # Skip the parent __init__'s URL validation by setting the
        # attributes it would set directly.
        self._endpoint = "http://fake/snippets"
        self._num_sources = 5
        self._timeout = 8.0
        self._multimodal_timeout = 25.0
        self._client = None
        self.ground_calls: list[tuple[str, int]] = []
        self.multimodal_calls: list[tuple[str, int]] = []
        self._ground_response = ground_response or []
        self._multimodal_response = multimodal_response or MultimodalGroundResult(
            snippets=[], queries_used=[], application=None,
            environment=None, goal_facets=[],
        )

    def ground(self, query, *, max_results=5):
        self.ground_calls.append((query, max_results))
        return list(self._ground_response)

    def ground_multimodal(self, request_text, image, *, max_results=5):
        self.multimodal_calls.append((request_text, max_results))
        return self._multimodal_response


# ---- Fixtures --------------------------------------------------------------

def _unit(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


def _snip(url: str, content: str = "body") -> WebGroundSnippet:
    return WebGroundSnippet(title=f"t-{url}", url=url, content=content)


def _make_wrapper(
    *,
    embeddings: ManualEmbeddings,
    inner: StubInner,
    clock: FakeClock | None = None,
) -> CachedEnrichmentSnippetsProducer:
    clock = clock or FakeClock()
    return CachedEnrichmentSnippetsProducer(
        inner=inner,
        query_cache=QueryCache(embeddings=embeddings, clock=clock),
        negative_cache=NegativeCache(embeddings=embeddings, clock=clock),
    )


def _image() -> UploadedImage:
    return UploadedImage(data=b"\x89PNG\r\nfake", mime_type="image/png",
                         filename="s.png")


# ---- ground: single-query path --------------------------------------------

class TestGroundMiss:
    def test_first_call_delegates_to_inner(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("how to deploy", _unit(0.0))
        inner = StubInner(ground_response=[_snip("https://a")])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        out = wrapper.ground("how to deploy")
        assert [s.url for s in out] == ["https://a"]
        assert inner.ground_calls == [("how to deploy", 5)]


class TestGroundCacheHit:
    def test_second_call_short_circuits(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("how to deploy", _unit(0.0))
        inner = StubInner(ground_response=[_snip("https://a")])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        wrapper.ground("how to deploy")
        out = wrapper.ground("how to deploy")
        assert [s.url for s in out] == ["https://a"]
        assert len(inner.ground_calls) == 1  # inner only hit once

    def test_paraphrased_call_hits_cache(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("how to deploy", _unit(0.0))
        emb.stage("deploy steps", _unit(0.1))  # cos ≈ 0.995
        inner = StubInner(ground_response=[_snip("https://a")])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        wrapper.ground("how to deploy")
        out = wrapper.ground("deploy steps")
        assert [s.url for s in out] == ["https://a"]
        assert len(inner.ground_calls) == 1

    def test_cache_returns_snippet_objects_not_dicts(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("q", _unit(0.0))
        inner = StubInner(ground_response=[_snip("https://a", "summary text")])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        wrapper.ground("q")
        out = wrapper.ground("q")
        assert isinstance(out[0], WebGroundSnippet)
        assert out[0].content == "summary text"


class TestGroundNegativeCache:
    def test_empty_upstream_response_stored_as_negative(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("nonsense query", _unit(0.0))
        inner = StubInner(ground_response=[])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        wrapper.ground("nonsense query")
        out = wrapper.ground("nonsense query")
        assert out == []
        assert len(inner.ground_calls) == 1  # second call short-circuited

    def test_paraphrased_negative_query_also_short_circuits(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("nonsense query", _unit(0.0))
        emb.stage("gibberish question", _unit(0.05))  # high cosine
        inner = StubInner(ground_response=[])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        wrapper.ground("nonsense query")
        wrapper.ground("gibberish question")
        assert len(inner.ground_calls) == 1

    def test_negative_entry_expires(self) -> None:
        emb = ManualEmbeddings()
        emb.stage("q", _unit(0.0))
        clock = FakeClock(t=0.0)
        inner = StubInner(ground_response=[])
        wrapper = CachedEnrichmentSnippetsProducer(
            inner=inner,
            query_cache=QueryCache(embeddings=emb, clock=clock),
            negative_cache=NegativeCache(embeddings=emb, clock=clock,
                                         ttl_seconds=60),
        )
        wrapper.ground("q")
        clock.advance(120)
        wrapper.ground("q")
        assert len(inner.ground_calls) == 2


class TestGroundEdgeCases:
    def test_blank_query_returns_empty_without_calling_inner(self) -> None:
        emb = ManualEmbeddings()
        inner = StubInner(ground_response=[_snip("https://a")])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        assert wrapper.ground("   ") == []
        assert inner.ground_calls == []


# ---- ground_multimodal ----------------------------------------------------
#
# The wrapper no longer populates per-query cache from the multimodal
# response — the enrichment-layer owns the L1 + L2 caches for that path
# now. The remaining behavioral contract is "delegate to inner without
# touching the local caches."

class TestMultimodal:
    def test_multimodal_delegates_to_inner_without_cache_writes(self) -> None:
        emb = ManualEmbeddings()
        s1 = _snip("https://q1-page")
        multi = MultimodalGroundResult(
            snippets=[s1], queries_used=["q1"],
            application="App", environment="OS", goal_facets=[],
            snippets_by_query={"q1": [s1]},
        )
        inner = StubInner(multimodal_response=multi)
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        out = wrapper.ground_multimodal("deploy this", _image())
        assert inner.multimodal_calls == [("deploy this", 5)]
        assert out.snippets == [s1]

    def test_multimodal_with_no_queries_used_returns_empty(self) -> None:
        emb = ManualEmbeddings()
        multi = MultimodalGroundResult(
            snippets=[], queries_used=[],
            application=None, environment=None, goal_facets=[],
        )
        inner = StubInner(multimodal_response=multi)
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        out = wrapper.ground_multimodal("anything", _image())
        assert out.snippets == []


# ---- Failure isolation ----------------------------------------------------

class TestFailureIsolation:
    def test_cache_exception_does_not_break_grounding(self, monkeypatch) -> None:
        emb = ManualEmbeddings()
        emb.stage("q", _unit(0.0))
        inner = StubInner(ground_response=[_snip("https://a")])
        wrapper = _make_wrapper(embeddings=emb, inner=inner)

        def boom(*a, **k):
            raise RuntimeError("cache exploded")

        monkeypatch.setattr(wrapper._negative_cache, "is_known_miss", boom)
        out = wrapper.ground("q")
        # Even with a broken negative cache, grounding still returns.
        assert [s.url for s in out] == ["https://a"]


# ---- Surface compatibility -------------------------------------------------

class TestSurfaceCompatibility:
    def test_wrapper_is_an_enrichment_producer_for_isinstance_checks(self) -> None:
        emb = ManualEmbeddings()
        inner = StubInner()
        wrapper = _make_wrapper(embeddings=emb, inner=inner)
        # The session does `isinstance(self.web_ground, EnrichmentSnippetsProducer)`
        # to gate the multimodal path — the wrapper must satisfy that.
        assert isinstance(wrapper, EnrichmentSnippetsProducer)


# ---- Parser: snippets_by_query in MultimodalGroundResult ------------------

class TestSnippetsByQueryParsing:
    def test_response_body_with_provenance_parses_into_dataclass(self) -> None:
        from backend.enrichment_client import _parse_snippets_by_query
        out = _parse_snippets_by_query({
            "q1": [{"title": "t", "url": "https://a", "content": "c"}],
            "q2": [{"title": "t2", "url": "https://b", "content": "c2"}],
        })
        assert set(out.keys()) == {"q1", "q2"}
        assert out["q1"][0].url == "https://a"
        assert out["q2"][0].title == "t2"

    def test_missing_field_yields_empty_dict(self) -> None:
        from backend.enrichment_client import _parse_snippets_by_query
        assert _parse_snippets_by_query(None) == {}
        assert _parse_snippets_by_query("not a dict") == {}
