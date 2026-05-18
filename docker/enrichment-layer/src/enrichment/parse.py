from __future__ import annotations

import json

from openai import OpenAI
from pydantic import BaseModel

from enrichment.config import settings
from enrichment.models import ExtractedPage
from enrichment.schema_draft import DraftPlan


class EnrichedDraft(BaseModel):
    plan: DraftPlan
    is_tutorial: bool
    source_url: str
    source_content_hash: str
    source_title: str
    model_name: str


PARSE_PROMPT = """You convert a single web tutorial page into a coarse step-by-step plan.

The plan will be fed into a downstream tutorial agent that aligns each step to
the live screen. Do not invent UI targets, coordinates, or roles. Write each
instruction as a short imperative sentence a user could follow on screen.

Output:
- is_tutorial: false if the page is not actually a step-by-step tutorial for
  the requested application and goal (e.g. forum posts, marketing copy,
  changelogs, listicles, irrelevant content). In that case return steps as
  a single placeholder.
- plan.goal: the goal the page teaches, phrased as an imperative.
- plan.steps: ordered DraftSteps. Merge sub-bullets into a single step when
  they describe one user-visible action. Drop pure prose intros, outros,
  and unrelated tips.

For each step pick the best kind hint:
- click, type, press_key, scroll, wait, navigate, verify, other
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_tutorial": {"type": "boolean"},
        "plan": {
            "type": "object",
            "properties": {
                "schema_version": {"type": "string", "enum": ["draft_plan.v1"]},
                "goal": {"type": "string"},
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
                        },
                        "required": ["instruction", "kind"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["schema_version", "goal", "steps"],
            "additionalProperties": False,
        },
    },
    "required": ["is_tutorial", "plan"],
    "additionalProperties": False,
}

_MAX_INPUT_CHARS = 12000


def parse_to_draft(
    page: ExtractedPage,
    application: str,
    goal: str,
) -> EnrichedDraft | None:
    body = (page.text or "")[:_MAX_INPUT_CHARS]
    if not body.strip():
        return None

    user_content = (
        f"Application: {application}\n"
        f"Goal: {goal}\n"
        f"Source URL: {page.url}\n"
        f"Page title: {page.title}\n\n"
        f"--- page main text ---\n{body}"
    )

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": PARSE_PROMPT},
            {"role": "user", "content": user_content},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "enriched_draft",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            }
        },
    )
    try:
        payload = json.loads(response.output_text or "{}")
        plan = DraftPlan(**payload["plan"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None

    if not payload.get("is_tutorial"):
        return None

    return EnrichedDraft(
        plan=plan,
        is_tutorial=True,
        source_url=page.url,
        source_content_hash=page.content_hash,
        source_title=page.title,
        model_name=settings.openai_model,
    )


def is_parse_candidate(page: ExtractedPage) -> bool:
    """Cheap structural gate before spending an LLM call on a page."""
    return page.ordered_list_items >= 3 and page.application_term_present
