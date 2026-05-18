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


class AlternativeMethod(_Strict):
    """A path the sources described that we chose NOT to make primary."""
    method_label: str
    summary: str = Field(min_length=1, description="One sentence describing the path.")
    source_indices: list[int] = Field(
        default_factory=list,
        description="Indices into AggregatePlan.sources that mentioned this path.",
    )


class AggregatePlan(_Strict):
    """One consensus plan stitched from N candidate plans, with provenance."""

    schema_version: Literal["aggregate_plan.v1"] = "aggregate_plan.v1"
    application: str
    goal: str
    method_label: str = "default"
    method_summary: str = ""
    guide_markdown: str = ""
    steps: list[AggregatedStep] = Field(min_length=1, max_length=30)
    alternative_methods: list[AlternativeMethod] = Field(default_factory=list)
    sources: list[PlanSource] = Field(min_length=1)
    source_count: int
    model_name: str


AGGREGATE_PROMPT = """You are consolidating multiple step-by-step tutorial drafts for the same
goal into ONE cohesive guide a real user can follow end-to-end.

Inputs: a list of candidate plans, each with a numeric source_index, URL, and
ordered steps. They may disagree on order, granularity, and specifics.

You produce TWO things:

1. `steps`: a structured list of consensus steps for downstream programmatic
   use. Aim for 5-12 steps. Merge semantically identical steps. Each step
   lists `sources` = indices of plans that support it (>=1 required).

2. `alternative_methods`: a list of OTHER paths the sources described that you
   chose not to make primary. For each, include a short snake_case
   `method_label`, a one-sentence `summary` ("Use the Finder Get Info dialog
   on the drive."), and `source_indices` = which source plans mentioned it.
   Use [] if the sources only described one approach. NEVER put primary steps
   in here — alternatives only.

3. `guide_markdown`: a clean, ordered markdown guide written FOR THE END USER.
   Make it feel like a polished how-to — not a JSON dump. It must:
   - Open with a one-sentence intro naming the method.
   - Use a numbered list, one action per item.
   - Include UI labels, screen locations, keyboard shortcuts, and visible
     cues (button color, icon shape, region of screen) WHEN they appear in
     ANY source plan. Do NOT invent any of these.
   - Use **bold** for UI element names. Use `code` for shortcuts and exact
     text the user types.
   - End with a one-line verification step that names the visual state the
     user should see if the action worked — but ONLY if a source plan
     mentions such a state. Omit the verification line if no source
     describes one.

Rules across both outputs:
- EXTRACT, don't INVENT. If a UI label, location, or shortcut appears in any
  source plan's instructions, preserve it. Do not add ones the sources never
  mention.
- When sources describe distinct ALTERNATIVE paths (e.g. OAuth vs. email),
  pick the strongest single path for `steps` + `guide_markdown` and put the
  others in `alternative_methods`. Never interleave alternatives into steps.
- Drop steps that appear in only one low-quality source and look like noise.
- Be concrete and specific. Avoid vague phrases like "navigate to the
  settings" when a source provides the actual path.
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
        # one draft → no consensus needed, just lift it. Synthesize a simple
        # markdown guide from the steps so callers always get guide_markdown.
        d = drafts[0]
        agg_steps = [
            AggregatedStep(
                instruction=s.instruction,
                kind=s.kind,
                sources=[StepSource(source_index=0)],
            )
            for s in d.plan.steps[:_MAX_STEPS_PER_SOURCE]
        ]
        return AggregatePlan(
            application=application,
            goal=goal,
            method_label=d.method_label or "default",
            method_summary=d.method_summary,
            guide_markdown=_deterministic_guide(d.method_summary, agg_steps),
            steps=agg_steps,
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
                "method_label": d.method_label,
                "method_summary": d.method_summary,
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
        alternatives = [AlternativeMethod(**a) for a in payload.get("alternative_methods", [])]
        guide_md = (payload.get("guide_markdown") or "").strip()
    except (json.JSONDecodeError, KeyError, ValueError):
        return None

    # Clamp out-of-range source indices defensively.
    max_idx = len(sources) - 1
    for s in steps:
        s.sources = [src for src in s.sources if 0 <= src.source_index <= max_idx]
        if not s.sources:
            s.sources = [StepSource(source_index=0)]

    summary = _pick_summary(drafts)
    label = drafts[0].method_label if drafts else "default"
    # Clamp alt-method source indices defensively.
    max_idx = len(sources) - 1
    for a in alternatives:
        a.source_indices = [i for i in a.source_indices if 0 <= i <= max_idx]

    return AggregatePlan(
        application=application,
        goal=goal,
        method_label=label,
        method_summary=summary,
        guide_markdown=guide_md or _deterministic_guide(summary, steps),
        steps=steps,
        alternative_methods=alternatives,
        sources=sources,
        source_count=len(drafts),
        model_name=settings.openai_model,
    )


def _pick_summary(drafts: list[EnrichedDraft]) -> str:
    for d in drafts:
        if d.method_summary:
            return d.method_summary
    return ""


def _deterministic_guide(summary: str, steps: list[AggregatedStep]) -> str:
    lines: list[str] = []
    if summary:
        lines.append(summary)
        lines.append("")
    for i, s in enumerate(steps, start=1):
        lines.append(f"{i}. {s.instruction}")
    return "\n".join(lines)


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "guide_markdown": {"type": "string"},
        "alternative_methods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "method_label": {"type": "string"},
                    "summary": {"type": "string"},
                    "source_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["method_label", "summary", "source_indices"],
                "additionalProperties": False,
            },
        },
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
    "required": ["guide_markdown", "alternative_methods", "steps"],
    "additionalProperties": False,
}
