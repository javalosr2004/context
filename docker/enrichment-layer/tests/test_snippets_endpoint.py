import pytest
from fastapi.testclient import TestClient

from enrichment import app as app_mod
from enrichment import snippets as snippets_mod
from enrichment.app import app
from enrichment.fetch import FetchResult
from enrichment.models import MultimodalQueryPlan, SearchHit


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
        # Return hits for every query so multi-query callers see fan-out.
        hits: list[SearchHit] = []
        for q in queries:
            for i in range(3):
                hits.append(
                    SearchHit(
                        query=q,
                        url=f"https://a{i}.example.com/figma?q={q.replace(' ', '_')}",
                        title=f"T{i}-{q[:4]}",
                        rank=i,
                    )
                )
        return hits

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
            data={
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
    assert body["queries_used"] == ["how to export png in figma"]
    assert body["goal_facets"] == []
    assert body["environment"] is None


def test_snippets_endpoint_respects_num_sources(stub_pipeline, isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post(
            "/snippets",
            data={"query": "figma png", "num_sources": 1},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["snippets"]) <= 1


def test_snippets_endpoint_rejects_blank_query(isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post("/snippets", data={"query": "   "})
    assert resp.status_code == 422


def test_snippets_endpoint_returns_503_on_pipeline_error(monkeypatch, isolated_data_dir):
    async def boom(_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(snippets_mod, "fan_out_search", boom)

    with TestClient(app) as client:
        resp = client.post("/snippets", data={"query": "x"})
    assert resp.status_code == 503


def test_snippets_endpoint_uses_multimodal_planner_when_image_attached(
    stub_pipeline, monkeypatch, isolated_data_dir
):
    captured: dict[str, object] = {}

    def fake_planner(raw_request, *, image_bytes=None, image_mime=None):
        captured["raw_request"] = raw_request
        captured["image_bytes_len"] = len(image_bytes or b"")
        captured["image_mime"] = image_mime
        return MultimodalQueryPlan(
            application="Figma",
            environment="macOS Sequoia, Figma desktop",
            goal_facets=["export selected frame as PNG", "batch export frames"],
            queries=["Figma help center export PNG", "how to batch export Figma frames"],
        )

    monkeypatch.setattr(app_mod, "generate_multimodal_query_plan", fake_planner)

    with TestClient(app) as client:
        resp = client.post(
            "/snippets",
            data={"query": "export this", "num_sources": 4},
            files={"image": ("screen.png", b"\x89PNG\r\nfake", "image/png")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queries_used"] == [
        "Figma help center export PNG",
        "how to batch export Figma frames",
    ]
    assert body["application"] == "Figma"
    assert body["environment"] == "macOS Sequoia, Figma desktop"
    assert body["goal_facets"] == [
        "export selected frame as PNG",
        "batch export frames",
    ]
    assert captured["raw_request"] == "export this"
    assert captured["image_bytes_len"] > 0
    assert captured["image_mime"] == "image/png"


def test_snippets_endpoint_returns_503_when_multimodal_planner_fails(
    monkeypatch, isolated_data_dir
):
    def boom(*_args, **_kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(app_mod, "generate_multimodal_query_plan", boom)

    with TestClient(app) as client:
        resp = client.post(
            "/snippets",
            data={"query": "x"},
            files={"image": ("s.png", b"\x89PNG", "image/png")},
        )
    assert resp.status_code == 503
