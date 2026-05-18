import pytest
from fastapi.testclient import TestClient

from enrichment import snippets as snippets_mod
from enrichment.app import app
from enrichment.fetch import FetchResult
from enrichment.models import SearchHit


FAKE_HTML = b"""
<html><head><title>How to export PNG in Figma</title></head>
<body>
  <h1>Export PNG in Figma</h1>
  <p>To export PNG files from Figma frames follow these instructions.</p>
  <ol>
    <li>Select your frame in Figma.</li>
    <li>Open the export panel and click PNG.</li>
    <li>Press Export to save the file.</li>
    <li>Choose your output directory.</li>
  </ol>
</body></html>
"""


@pytest.fixture
def stub_pipeline(monkeypatch):
    async def fake_search(queries):
        q = queries[0]
        return [
            SearchHit(query=q, url=f"https://a{i}.example.com/figma", title=f"T{i}", rank=i)
            for i in range(3)
        ]

    async def fake_fetch(urls):
        return [
            FetchResult(
                url=u, final_url=u, http_status=200, html=FAKE_HTML,
                content_hash=f"hash-{i}",
            )
            for i, u in enumerate(urls)
        ]

    def fake_summarize(page, application, goal):
        if "a1" in page.url:
            return None  # one failure to validate partial-failure tolerance
        return f"snippet for {page.url}"

    monkeypatch.setattr(snippets_mod, "fan_out_search", fake_search)
    monkeypatch.setattr(snippets_mod, "fan_out_fetch", fake_fetch)
    monkeypatch.setattr(snippets_mod, "summarize_page_for_goal", fake_summarize)


def test_snippets_endpoint_returns_tavily_shape(stub_pipeline, isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post(
            "/snippets",
            json={
                "query": "how to export png in figma",
                "application": "Figma",
                "goal": "export PNG",
                "num_sources": 5,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_count"] == len(body["snippets"])
    assert len(body["snippets"]) >= 1
    for s in body["snippets"]:
        assert set(s.keys()) == {"title", "url", "content"}
        assert s["url"].startswith("https://")
        assert s["content"]
    # The page that returned None must be filtered out
    assert not any("a1.example.com" in s["url"] for s in body["snippets"])
    assert body["elapsed_ms"] >= 0


def test_snippets_endpoint_respects_num_sources(stub_pipeline, isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post(
            "/snippets",
            json={"query": "figma png", "num_sources": 1},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["snippets"]) <= 1


def test_snippets_endpoint_rejects_blank_query(isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post("/snippets", json={"query": "   "})
    assert resp.status_code == 422


def test_snippets_endpoint_returns_503_on_pipeline_error(monkeypatch, isolated_data_dir):
    async def boom(_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(snippets_mod, "fan_out_search", boom)

    with TestClient(app) as client:
        resp = client.post("/snippets", json={"query": "x"})
    assert resp.status_code == 503
