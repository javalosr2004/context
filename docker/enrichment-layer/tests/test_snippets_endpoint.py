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
    # snippets_by_query exposes per-query provenance so callers can
    # populate a per-query cache from one multimodal call.
    sbq = body["snippets_by_query"]
    assert set(sbq.keys()) == set(body["queries_used"])
    surfaced_urls = {s["url"] for snips in sbq.values() for s in snips}
    returned_urls = {s["url"] for s in body["snippets"]}
    assert surfaced_urls == returned_urls
    assert captured["raw_request"] == "export this"
    assert captured["image_bytes_len"] > 0
    assert captured["image_mime"] == "image/png"


# ---- /extract -------------------------------------------------------------

def test_extract_endpoint_returns_page_text(monkeypatch, isolated_data_dir):
    async def fake_fetch(urls):
        return [
            FetchResult(
                url=urls[0], final_url=urls[0], http_status=200,
                html=FAKE_HTML, content_hash="hash-extract",
            )
        ]

    monkeypatch.setattr(app_mod, "fan_out_fetch", fake_fetch)
    with TestClient(app) as client:
        resp = client.post(
            "/extract",
            json={"url": "https://example.com/figma-export"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"] == "https://example.com/figma-export"
    assert body["final_url"] == body["url"]
    assert body["http_status"] == 200
    assert "Figma" in body["title"]
    assert "Select your frame" in body["text"]
    assert body["content_hash"] == "hash-extract"


def test_extract_endpoint_rejects_blank_url(isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post("/extract", json={"url": "   "})
    assert resp.status_code == 422


def test_extract_endpoint_502_when_fetch_returns_nothing(
    monkeypatch, isolated_data_dir,
):
    async def fake_fetch(urls):
        return []

    monkeypatch.setattr(app_mod, "fan_out_fetch", fake_fetch)
    with TestClient(app) as client:
        resp = client.post("/extract", json={"url": "https://example.com"})
    assert resp.status_code == 502


# ---- /summarize -----------------------------------------------------------

def test_summarize_endpoint_returns_snippet(monkeypatch, isolated_data_dir):
    captured: dict[str, object] = {}

    def fake_summarize(page, application, goal, max_chars=300):
        captured["page_url"] = page.url
        captured["page_title"] = page.title
        captured["text_chars"] = len(page.text)
        captured["application"] = application
        captured["goal"] = goal
        captured["max_chars"] = max_chars
        return "short snippet for the user"

    monkeypatch.setattr(app_mod, "summarize_page_for_goal", fake_summarize)
    with TestClient(app) as client:
        resp = client.post(
            "/summarize",
            json={
                "url": "https://example.com/p",
                "title": "Page Title",
                "text": "step 1, step 2, step 3 with enough body to summarize",
                "query": "how to do step 2",
                "application": "Figma",
                "max_chars": 200,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snippet"] == "short snippet for the user"
    assert body["url"] == "https://example.com/p"
    assert captured["page_url"] == "https://example.com/p"
    assert captured["page_title"] == "Page Title"
    assert captured["application"] == "Figma"
    # When no goal is provided, the query is used as the goal — this is
    # exactly why summaries are NOT cache-shared across queries.
    assert captured["goal"] == "how to do step 2"
    assert captured["max_chars"] == 200


def test_summarize_uses_explicit_goal_over_query_when_provided(
    monkeypatch, isolated_data_dir,
):
    captured: dict[str, object] = {}

    def fake_summarize(page, application, goal, max_chars=300):
        captured["goal"] = goal
        return "ok"

    monkeypatch.setattr(app_mod, "summarize_page_for_goal", fake_summarize)
    with TestClient(app) as client:
        resp = client.post(
            "/summarize",
            json={
                "url": "https://x", "text": "body text here",
                "query": "paraphrased query",
                "goal": "canonical goal",
            },
        )
    assert resp.status_code == 200
    assert captured["goal"] == "canonical goal"


def test_summarize_rejects_blank_text(isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post(
            "/summarize",
            json={"url": "https://x", "text": "  ", "query": "q"},
        )
    assert resp.status_code == 422


def test_summarize_rejects_blank_query(isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post(
            "/summarize",
            json={"url": "https://x", "text": "ok", "query": "  "},
        )
    assert resp.status_code == 422


def test_summarize_returns_503_on_summarizer_error(
    monkeypatch, isolated_data_dir,
):
    def boom(*args, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(app_mod, "summarize_page_for_goal", boom)
    with TestClient(app) as client:
        resp = client.post(
            "/summarize",
            json={"url": "https://x", "text": "body", "query": "q"},
        )
    assert resp.status_code == 503


def test_summarize_returns_null_snippet_when_summarizer_returns_none(
    monkeypatch, isolated_data_dir,
):
    monkeypatch.setattr(
        app_mod, "summarize_page_for_goal",
        lambda *_a, **_k: None,
    )
    with TestClient(app) as client:
        resp = client.post(
            "/summarize",
            json={"url": "https://x", "text": "body", "query": "q"},
        )
    assert resp.status_code == 200
    assert resp.json()["snippet"] is None


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
