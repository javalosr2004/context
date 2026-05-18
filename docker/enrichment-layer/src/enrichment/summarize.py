"""Per-page snippet summarization for the hot-path /snippets endpoint.

One nano LLM call per page. Extracts a short excerpt focused on the
caller's goal, suitable for use as a Tavily-shaped grounding snippet.
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from enrichment.config import settings
from enrichment.models import ExtractedPage

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 16000  # ~4k tokens

_SYSTEM_PROMPT = """You extract a single short excerpt from a web page that
would help a user accomplish a specific goal in a specific application.

Rules:
- Output 200-300 characters of plain text. No markdown. No numbering.
- Pull directly from the page. Do not invent UI labels, steps, or commands.
- If the page does not actually help with the goal, return an empty string.
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"snippet": {"type": "string"}},
    "required": ["snippet"],
    "additionalProperties": False,
}


def summarize_page_for_goal(
    page: ExtractedPage,
    application: str | None,
    goal: str | None,
    max_chars: int = 300,
) -> str | None:
    body = (page.text or "")[:_MAX_INPUT_CHARS]
    if not body.strip():
        return None

    app_line = application or "(unspecified)"
    goal_line = goal or "(use the page title as the goal)"
    user_content = (
        f"Application: {app_line}\n"
        f"Goal: {goal_line}\n"
        f"Source URL: {page.url}\n"
        f"Page title: {page.title}\n\n"
        f"--- page text ---\n{body}"
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "page_snippet",
                    "schema": _RESPONSE_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text or "{}")
    except (json.JSONDecodeError, ValueError, Exception) as exc:
        logger.warning("summarize_page_for_goal failed for %s: %s", page.url, exc)
        return None

    snippet = (payload.get("snippet") or "").strip()
    if not snippet:
        return None
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 1].rstrip() + "…"
    return snippet
