from enrichment.aggregate import aggregate_drafts
from enrichment.parse import EnrichedDraft
from enrichment.schema_draft import DraftPlan, DraftStep


def _draft(url: str, steps: list[tuple[str, str]]) -> EnrichedDraft:
    return EnrichedDraft(
        plan=DraftPlan(
            goal="export PNG",
            steps=[DraftStep(instruction=i, kind=k) for i, k in steps],
        ),
        is_tutorial=True,
        source_url=url,
        source_content_hash=url.split("/")[-1],
        source_title="t",
        model_name="fake",
    )


def test_empty_drafts_returns_none():
    assert aggregate_drafts([], "Figma", "export PNG") is None


def test_single_draft_lifts_without_llm_call():
    """If there's only one draft, aggregate_drafts skips the LLM and lifts it directly."""
    draft = _draft(
        "https://a.example.com/x",
        [("Select the frame.", "click"), ("Click Export.", "click")],
    )
    result = aggregate_drafts([draft], "Figma", "export PNG")

    assert result is not None
    assert result.source_count == 1
    assert len(result.sources) == 1
    assert result.sources[0].url == "https://a.example.com/x"
    assert len(result.steps) == 2
    for s in result.steps:
        assert s.sources == [s.sources[0]]
        assert s.sources[0].source_index == 0
