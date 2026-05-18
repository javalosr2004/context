import asyncio

import pytest
from fastapi.testclient import TestClient

from enrichment import parse as parse_mod
from enrichment import pipeline as pipeline_mod
from enrichment.app import app
from enrichment.fetch import FetchResult
from enrichment.models import QueryPlan, SearchHit
from enrichment.parse import EnrichedDraft
from enrichment.schema_draft import DraftPlan, DraftStep


@pytest.fixture
def stubbed(monkeypatch):
    plan = QueryPlan(application="Figma", goal="export PNG", queries=["q1"])

    def fake_gen(_):
        return plan

    async def fake_search(_qs):
        return [SearchHit(query="q1", url="https://a.example.com", title="A", rank=0)]

    async def fake_fetch(urls):
        return [FetchResult(
            url=u, final_url=u, http_status=200,
            html=b"<html><body><ol><li>a</li><li>b</li><li>c</li></ol>Figma</body></html>",
            content_hash=f"h-{i}",
        ) for i, u in enumerate(urls)]

    def fake_parse(page, app_, goal):
        return EnrichedDraft(
            plan=DraftPlan(goal=goal, steps=[DraftStep(instruction="do it", kind="click")]),
            is_tutorial=True,
            source_url=page.url,
            source_content_hash=page.content_hash,
            source_title=page.title,
            model_name="fake",
        )

    monkeypatch.setattr(pipeline_mod, "generate_queries", fake_gen)
    monkeypatch.setattr(pipeline_mod, "fan_out_search", fake_search)
    monkeypatch.setattr(pipeline_mod, "fan_out_fetch", fake_fetch)
    monkeypatch.setattr(parse_mod, "parse_to_draft", fake_parse)
    monkeypatch.setattr(pipeline_mod, "parse_to_draft", fake_parse)


async def test_post_returns_job_then_polls_done(stubbed, isolated_data_dir):
    with TestClient(app) as client:
        resp = client.post("/query", json={"request": "how to export png in figma"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending"
        job_id = body["job_id"]

        for _ in range(50):
            await asyncio.sleep(0.05)
            poll = client.get(f"/jobs/{job_id}").json()
            if poll["status"] in ("done", "failed"):
                break

        assert poll["status"] == "done", poll
        assert poll["run_id"]
        assert (isolated_data_dir / "runs" / poll["run_id"] / "meta.json").exists()


def test_unknown_job_returns_404(isolated_data_dir):
    with TestClient(app) as client:
        assert client.get("/jobs/does-not-exist").status_code == 404


async def test_failed_job_records_error(monkeypatch, isolated_data_dir):
    def boom(_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline_mod, "generate_queries", boom)

    with TestClient(app) as client:
        job_id = client.post("/query", json={"request": "x"}).json()["job_id"]
        for _ in range(50):
            await asyncio.sleep(0.05)
            poll = client.get(f"/jobs/{job_id}").json()
            if poll["status"] in ("done", "failed"):
                break
        assert poll["status"] == "failed"
        assert "kaboom" in poll["error"]
