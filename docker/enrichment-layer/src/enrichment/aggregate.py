from __future__ import annotations

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from enrichment.config import settings
from enrichment.parse import EnrichedDraft
from enrichment.schema_draft import DraftStepKind


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepSource(_Strict):
    source_index: int = Field(ge=0, description="Index into AggregatePlan.sources.")


class AggregatedStep(_Strict):
    instruction: str = Field(min_length=1)
    kind: DraftStepKind
    sources: list[StepSource] = Field(
        min_length=1,
        description="Indices of source plans that contributed this step.",
    )


class PlanSource(_Strict):
    url: str
    title: str
    content_hash: str


class AggregatePlan(_Strict):
    """One consensus plan stitched from N candidate plans, with provenance."""

    schema_version: Literal["aggregate_plan.v1"] = "aggregate_plan.v1"
    application: str
    goal: str
    steps: list[AggregatedStep] = Field(min_length=1, max_length=30)
    sources: list[PlanSource] = Field(min_length=1)
    source_count: int
    model_name: str


AGGREGATE_PROMPT = """You are consolidating multiple step-by-step tutorial drafts for the same
goal into ONE consensus plan a user could follow end to end.

Inputs: a list of candidate plans, each with a numeric source_index, URL, and
ordered steps. They may disagree on order, granularity, and specifics.

Produce one plan that:
- Is the shortest correct path. Aim for 5-12 steps.
- Merges semantically identical steps even if worded differently.
- Resolves contradictions in favor of the majority OR the most authoritative
  source (official docs > third-party tutorials > listicles). When sources
  describe distinct ALTERNATIVE paths (e.g. OAuth vs. email), pick one and
  drop the other — do not interleave them.
- Drops steps that only appear in a single low-quality source and look like
  noise (prerequisites, side trips, app-specific UI of a wrong tool).
- For each step, lists sources = indices of the input plans that support it.
  At least one source per step is required.

Do NOT invent UI labels, coordinates, or roles. Keep instructions short and
imperative — a downstream agent will re-ground each step against the live
screen.
"""

_MAX_STEPS_PER_SOURCE = 30


def aggregate_drafts(
    drafts: list[EnrichedDraft],
    application: str,
    goal: str,
) -> AggregatePlan | None:
    if not drafts:
        return None

    sources = [
        PlanSource(url=d.source_url, title=d.source_title, content_hash=d.source_content_hash)
        for d in drafts
    ]

    if len(drafts) == 1:
        # one draft → no consensus needed, just lift it
        d = drafts[0]
        return AggregatePlan(
            application=application,
            goal=goal,
            steps=[
                AggregatedStep(
                    instruction=s.instruction,
                    kind=s.kind,
                    sources=[StepSource(source_index=0)],
                )
                for s in d.plan.steps[:_MAX_STEPS_PER_SOURCE]
            ],
            sources=sources,
            source_count=1,
            model_name=d.model_name,
        )

    input_payload = {
        "application": application,
        "goal": goal,
        "candidate_plans": [
            {
                "source_index": i,
                "url": d.source_url,
                "title": d.source_title,
                "steps": [{"instruction": s.instruction, "kind": s.kind} for s in d.plan.steps],
            }
            for i, d in enumerate(drafts)
        ],
    }

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": AGGREGATE_PROMPT},
            {"role": "user", "content": json.dumps(input_payload)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "aggregate_plan_body",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            }
        },
    )

    try:
        payload = json.loads(response.output_text or "{}")
        steps = [AggregatedStep(**s) for s in payload["steps"]]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None

    # Clamp out-of-range source indices defensively.
    max_idx = len(sources) - 1
    for s in steps:
        s.sources = [src for src in s.sources if 0 <= src.source_index <= max_idx]
        if not s.sources:
            s.sources = [StepSource(source_index=0)]

    return AggregatePlan(
        application=application,
        goal=goal,
        steps=steps,
        sources=sources,
        source_count=len(drafts),
        model_name=settings.openai_model,
    )


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "click", "type", "press_key", "scroll",
                            "wait", "navigate", "verify", "other",
                        ],
                    },
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_index": {"type": "integer"},
                            },
                            "required": ["source_index"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["instruction", "kind", "sources"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": False,
}
