import pytest

from enrichment import parse as parse_mod
from enrichment import pipeline as pipeline_mod
from enrichment.fetch import FetchResult
from enrichment.models import QueryPlan, SearchHit
from enrichment.parse import EnrichedDraft
from enrichment.schema_draft import DraftPlan, DraftStep


FAKE_HTML = b"""
<html><head><title>Figma PNG Export Tutorial</title></head>
<body>
  <h1>Export PNG in Figma</h1>
  <ol>
    <li>Select your frame in Figma.</li>
    <li>Open the export panel.</li>
    <li>Click PNG and press Export.</li>
    <li>Choose your output directory.</li>
  </ol>
</body></html>
"""


@pytest.fixture
def fakes(monkeypatch):
    plan = QueryPlan(
        application="Figma",
        goal="export PNG",
        queries=["how to export png figma", "figma png export tutorial"],
    )

    def fake_gen(_raw: str) -> QueryPlan:
        return plan

    async def fake_search(queries):
        return [
            SearchHit(query=queries[0], url="https://a.example.com/figma", title="A", rank=0),
            SearchHit(query=queries[1], url="https://b.example.com/figma", title="B", rank=0),
        ]

    async def fake_fetch(urls):
        return [
            FetchResult(
                url=u, final_url=u, http_status=200, html=FAKE_HTML,
                content_hash=f"hash-{i}",
            )
            for i, u in enumerate(urls)
        ]

    def fake_parse(page, application, goal):
        return EnrichedDraft(
            plan=DraftPlan(
                goal=goal,
                steps=[
                    DraftStep(instruction="Select the frame.", kind="click"),
                    DraftStep(instruction="Open the export panel.", kind="click"),
                    DraftStep(instruction="Click Export.", kind="click"),
                ],
            ),
            is_tutorial=True,
            source_url=page.url,
            source_content_hash=page.content_hash,
            source_title=page.title,
            model_name="fake-model",
        )

    monkeypatch.setattr(pipeline_mod, "generate_queries", fake_gen)
    monkeypatch.setattr(pipeline_mod, "fan_out_search", fake_search)
    monkeypatch.setattr(pipeline_mod, "fan_out_fetch", fake_fetch)
    monkeypatch.setattr(parse_mod, "parse_to_draft", fake_parse)
    monkeypatch.setattr(pipeline_mod, "parse_to_draft", fake_parse)
    return plan


async def test_pipeline_end_to_end(fakes, isolated_data_dir):
    result = await pipeline_mod.run_enrichment("how do I export a PNG in Figma?")

    assert result.plan.application == "Figma"
    assert result.hit_count == 2
    assert result.page_count == 2
    assert result.parsed_plan_count == 2
    assert result.run_id

    assert (isolated_data_dir / "runs" / result.run_id / "meta.json").exists()
    assert len(list((isolated_data_dir / "pages").glob("*.html"))) == 2
    assert len(list((isolated_data_dir / "parsed").glob("*.json"))) == 2
    assert len(list((isolated_data_dir / "plans").glob("*.json"))) == 2
    assert (isolated_data_dir / "index.db").exists()
