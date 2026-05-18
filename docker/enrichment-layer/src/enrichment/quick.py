"""Cheap single-call guide generation.

Skips per-page LLM parsing and structured aggregation. One LLM call ingests
the extracted text from all candidate pages and emits a single markdown
guide describing the most valuable / generic tutorial for the goal.

Trades provenance + structured steps for speed and cost. Use when callers
just want a usable guide and don't need per-step source attribution.
"""
from __future__ import annotations

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from enrichment.config import settings
from enrichment.models import ExtractedPage


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuickGuideSource(_Strict):
    url: str
    title: str
    content_hash: str


class QuickGuide(_Strict):
    schema_version: Literal["quick_guide.v1"] = "quick_guide.v1"
    application: str
    goal: str
    guide_markdown: str = Field(min_length=1)
    sources: list[QuickGuideSource]
    source_count: int
    model_name: str


QUICK_PROMPT = """You are given the extracted body text from several web pages, all
retrieved for the same user goal in the same application. Your job is to
return ONE polished markdown guide that synthesizes the BEST and MOST
GENERIC path a user could follow to accomplish the goal.

Rules:
- Pick the path that is the most widely applicable across users and
  versions — avoid steps that depend on a specific blog author's setup.
- EXTRACT, don't INVENT. If a UI label, screen location, keyboard shortcut,
  or visible cue appears in one of the sources, you may use it. Do not
  invent UI labels, paths, or coordinates the sources never mention.
- Be concrete. Prefer "Run `gcloud run deploy --source .`" over "deploy
  your container using the gcloud CLI".
- Skip prerequisites that aren't actions (e.g. "make sure Docker is
  installed") unless a source explicitly requires a non-obvious setup
  step.
- Drop content that is only relevant to one source's specific framework
  (e.g. Deno-specific setup when the goal is generic container deploy).
- Drop steps that assume a STARTING STATE the user didn't ask about. The
  user came to do the requested goal, not to do the setup that came before
  it. Examples to drop:
  - "Clone your application repo" (when the goal is "deploy a container")
  - "Sign up for a Google Cloud account" (when the goal assumes the user
    is already using the service)
  - "Install Docker" (when the goal is using Docker, not installing it)
  Only include such steps if a source explicitly flags them as a
  non-obvious requirement specific to the goal.

The output (`guide_markdown`) must:
- Open with a one-sentence intro naming the approach.
- Be a numbered list, one action per item.
- Use **bold** for UI element names and `code` for shortcuts, commands,
  and exact text the user types.
- End with a one-line verification sentence describing the visible state
  the user should see if it worked, ONLY if a source mentions one.
"""


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "guide_markdown": {"type": "string"},
    },
    "required": ["guide_markdown"],
    "additionalProperties": False,
}


_MAX_CHARS_PER_PAGE = 8000


def synthesize_quick_guide(
    pages: list[ExtractedPage],
    application: str,
    goal: str,
) -> QuickGuide | None:
    if not pages:
        return None

    sources = [
        QuickGuideSource(url=p.url, title=p.title, content_hash=p.content_hash)
        for p in pages
    ]

    input_payload = {
        "application": application,
        "goal": goal,
        "pages": [
            {
                "source_index": i,
                "url": p.url,
                "title": p.title,
                "text": (p.text or "")[:_MAX_CHARS_PER_PAGE],
            }
            for i, p in enumerate(pages)
        ],
    }

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": QUICK_PROMPT},
            {"role": "user", "content": json.dumps(input_payload)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "quick_guide_body",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            }
        },
    )

    try:
        payload = json.loads(response.output_text or "{}")
        guide_md = (payload.get("guide_markdown") or "").strip()
    except (json.JSONDecodeError, ValueError):
        return None

    if not guide_md:
        return None

    return QuickGuide(
        application=application,
        goal=goal,
        guide_markdown=guide_md,
        sources=sources,
        source_count=len(sources),
        model_name=settings.openai_model,
    )
