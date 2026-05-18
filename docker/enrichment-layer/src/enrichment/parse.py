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
    method_label: str = "default"
    method_summary: str = ""


PARSE_PROMPT = """You convert a single web tutorial page into a coarse step-by-step plan.

The plan will be fed into a downstream tutorial agent that aligns each step
to the live screen. Do not invent UI targets, coordinates, or roles. Write
each instruction as a short imperative sentence a user could follow.

The page may be a structured tutorial OR a forum thread / Q&A / blog post.
All of these can contain actionable steps. Extract the actions regardless
of layout. Sources of actions include:
- Ordered or unordered lists of steps.
- Numbered headings or "Step 1 / Step 2" headings.
- Prose paragraphs containing imperative sentences ("Then click Save", "Run
  pip install ...").
- Forum/Q&A answers describing what fixed a problem.
- Code blocks adjacent to "run this" / "type this" prose.

Set is_tutorial = false (and return a single placeholder step) if ANY apply:
- The page has no concrete actions a user could perform (pure marketing,
  feature lists, changelogs, "what is X?" explainers, opinion pieces).
- The page describes actions but for a DIFFERENT application than the
  requested one. Example: requested "GitHub" but page teaches the Eclipse
  Git plugin, GitKraken, or VS Code.
- The page describes actions for the requested application but for a
  DIFFERENT goal. Example: requested goal "export PNG" but page teaches
  importing or exporting SVG.
- The match is only partial (the goal is one paragraph inside a broader
  guide and the page never actually walks through it).
- The page is primarily a discussion/argument with no resolution or
  consensus action. Borderline cases: prefer false.

When is_tutorial = true:
- plan.goal: the goal the page teaches, phrased as an imperative.
- plan.steps: ordered DraftSteps. Merge sub-bullets into one step when they
  describe a single user-visible action. Drop prose intros, outros, tips,
  and prerequisites that are not actions.
- For forum/Q&A pages: reconstruct the action sequence from the answer that
  the asker accepted, or from the highest-signal reply. Skip the question
  text, off-topic replies, and meta discussion.

For each step pick the best kind hint:
- click, type, press_key, scroll, wait, navigate, verify, other

Also identify the METHOD this page teaches. Many goals have multiple
independent paths (e.g. "view storage on Mac": Apple-menu-About-This-Mac,
Finder-Get-Info, Disk-Utility, Spotlight, terminal). Set:
- method_label: short snake_case identifier for the path, derived from the
  primary entry point or tool. Examples: "apple_menu_about",
  "finder_get_info", "disk_utility", "spotlight_search", "terminal".
  If the page does not clearly fit a named alternative, use "default".
- method_summary: one short sentence naming the entry point in plain English
  ("Use the Apple menu's About This Mac").
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_tutorial": {"type": "boolean"},
        "method_label": {"type": "string"},
        "method_summary": {"type": "string"},
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
    "required": ["is_tutorial", "method_label", "method_summary", "plan"],
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

    label = (payload.get("method_label") or "default").strip() or "default"
    return EnrichedDraft(
        plan=plan,
        is_tutorial=True,
        source_url=page.url,
        source_content_hash=page.content_hash,
        source_title=page.title,
        model_name=settings.openai_model,
        method_label=_normalize_label(label),
        method_summary=(payload.get("method_summary") or "").strip(),
    )


def _normalize_label(raw: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in raw.lower().strip())
    cleaned = cleaned.strip("_-")
    return cleaned[:48] or "default"


def is_parse_candidate(page: ExtractedPage) -> bool:
    """Cheap structural gate before spending an LLM call on a page.

    Intentionally permissive on document structure: forum threads, Q&A
    pages, and inline-prose tutorials all carry useful actions even when
    they don't use <ol>. Final filtering happens inside the parser via
    is_tutorial=false. We only require that the application and goal
    are actually mentioned on the page.
    """
    return (
        page.application_term_present
        and page.goal_term_present
        and page.text_length >= 400
    )
