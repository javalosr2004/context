from __future__ import annotations

import time

from enrichment.cache import l3_search, l4_page, l5_summary
from enrichment.cache.grounding_cache import _Layer
from enrichment.cache.storage import InMemoryStorage


def test_in_memory_storage_get_put_hit_miss():
    s: InMemoryStorage[str, int] = InMemoryStorage(max_size=4)
    assert s.get("k") is None
    s.put("k", 1)
    assert s.get("k") == 1
    stats = s.stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.size == 1


def test_in_memory_storage_ttl_expires():
    s: InMemoryStorage[str, int] = InMemoryStorage(max_size=4)
    s.put("k", 1, ttl_seconds=0.01)
    time.sleep(0.05)
    assert s.get("k") is None  # expired


def test_in_memory_storage_lru_evicts():
    s: InMemoryStorage[str, int] = InMemoryStorage(max_size=2)
    s.put("a", 1)
    s.put("b", 2)
    s.put("c", 3)  # evicts "a"
    assert s.get("a") is None
    assert s.get("b") == 2
    assert s.get("c") == 3
    assert s.stats().evictions == 1


def test_layer_log_path_does_not_crash():
    layer = _Layer[int]("Ltest", max_size=4, default_ttl=10.0)
    layer.put("x", 7)
    assert layer.get("x") == 7
    assert layer.get("absent") is None


def test_l3_normalizes_whitespace_and_case():
    l3_search.layer._storage.clear()
    payload = [{"query": "Foo Bar", "url": "http://a", "title": "", "snippet": "", "rank": 0}]
    l3_search.put("Foo  BAR", payload)
    assert l3_search.get("foo bar") == payload
    assert l3_search.get("foo bar") == payload  # second hit


def test_l5_keys_on_content_hash_goal_application():
    l5_summary.layer._storage.clear()
    l5_summary.put("hash1", "goal x", "appA", "snip-1")
    assert l5_summary.get("hash1", "GOAL X", "appA") == "snip-1"  # case-insensitive
    assert l5_summary.get("hash1", "goal y", "appA") is None      # different goal
    assert l5_summary.get("hash1", "goal x", "appB") is None      # different app


def test_l4_caches_dict_payload_by_url():
    l4_page.layer._storage.clear()
    l4_page.put("http://x", {"url": "http://x", "text": "hello"})
    assert l4_page.get("http://x") == {"url": "http://x", "text": "hello"}
    assert l4_page.get("http://other") is None


# ---------- L1 / L2 (embedding-based) ----------


def _stub_embeddings(monkeypatch, mapping: dict[str, list[float]]):
    """Force deterministic embeddings so cosine math is predictable."""
    from enrichment.cache import embeddings as emb_mod

    def fake_embed(text: str) -> list[float] | None:
        return mapping.get(text)

    monkeypatch.setattr(emb_mod, "embed", fake_embed)
    # The grounding_cache module imports embed lazily — also patch its
    # local lookup namespace.
    from enrichment.cache import grounding_cache as gc_mod
    monkeypatch.setattr(
        "enrichment.cache.embeddings.embed", fake_embed, raising=True,
    )
    return emb_mod, gc_mod


def test_l1_paraphrase_hit(monkeypatch):
    from enrichment.cache import l1_plan
    l1_plan._data.clear()
    # Two nearly-parallel vectors (cosine ≈ 1.0) — should hit.
    _stub_embeddings(monkeypatch, {
        "deploy to cloud run": [1.0, 0.0, 0.0],
        "ship to cloud run": [0.99, 0.01, 0.0],
        "make a pancake": [0.0, 1.0, 0.0],
    })
    l1_plan.put("part-A", "deploy to cloud run", {"queries": ["a", "b"]})
    hit = l1_plan.get("part-A", "ship to cloud run")
    assert hit == {"queries": ["a", "b"]}
    # Cross-partition: same text, different partition → miss.
    assert l1_plan.get("part-B", "ship to cloud run") is None
    # Orthogonal text → miss even in correct partition.
    assert l1_plan.get("part-A", "make a pancake") is None


def test_cache_stats_endpoint_returns_per_layer():
    from fastapi.testclient import TestClient

    from enrichment.app import app
    with TestClient(app) as client:
        resp = client.get("/cache/stats")
    assert resp.status_code == 200
    body = resp.json()
    for name in ("L1", "L2", "L3", "L4", "L5"):
        assert name in body
        assert "hits" in body[name]
        assert "misses" in body[name]


def test_l2_partition_and_text_helpers():
    from enrichment.cache import (
        l2_partition_for_context, l2_text_for_queries,
    )
    p1 = l2_partition_for_context("Figma", "macOS")
    p2 = l2_partition_for_context("figma", "MACOS")
    assert p1 == p2  # normalized
    p3 = l2_partition_for_context("Slack", "macOS")
    assert p3 != p1

    assert l2_text_for_queries(["B  q", "a Q"]) == l2_text_for_queries(["a q", "b q"])
