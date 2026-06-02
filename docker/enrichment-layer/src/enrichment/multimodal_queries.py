"""Multimodal query planning for the hot-path /snippets endpoint.

Takes the raw user request plus an optional screenshot, identifies the
visible environment (OS/app/region), decomposes the request into a few
*varying* sub-goals, and emits a flat list of search queries spanning
those sub-goals.

The varying-sub-goals shape matters: when the downstream aggregator
merges fetched pages it wants coverage across different interpretations
of an ambiguous request, not five paraphrases of the same one.
"""
from __future__ import annotations

import base64
import json
import logging

from openai import OpenAI

from enrichment.config import settings
from enrichment.models import MultimodalQueryPlan

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You plan web searches that surface tutorials for software tasks.

You receive a raw user request and, when available, a screenshot of the
user's current screen. Your output drives a multi-query web search whose
results are aggregated into one tutorial — so your queries must span
varying interpretations of the request, not paraphrase a single one.

Do three things:

1. Identify the environment from the screenshot.
   - Name the OS and version when visible (e.g. "macOS Sequoia").
   - Name the active application and any specific region or mode visible.
   - If no screenshot is provided, infer the most likely environment from
     the request, but say so plainly (e.g. "no screenshot; assuming web
     Figma").

2. Refine the request into 2-4 distinct goal facets.
   - Each facet is a short imperative phrase capturing one reasonable
     interpretation or sub-task of the user's request.
   - Facets must be meaningfully different from each other. If the
     request is unambiguous, produce one core facet plus 1-2 adjacent
     facets the user is likely to need next (prerequisite, follow-up,
     common variant).
   - Example. Request "export this design". Facets: "export selected
     frame as PNG", "export entire page as PDF", "batch export multiple
     frames".

3. Generate 3-6 web search queries total, spanning the facets.
   - At least one query should target the application's CANONICAL or
     authoritative source, phrased the way that source titles its own
     pages (e.g. "Figma help center export PNG", "Cloud Run deploy
     container quickstart", "Ink/Stitch docs basic use").
   - At least one query should use tutorial/blog phrasings ("how to",
     "step by step", "guide") to surface community walkthroughs.
   - Cover every facet with at least one query when budget allows.
   - Name the OS or app when relevant. Prefer specific labels over
     generic ones. No question marks, no quotes.
   - Avoid near-duplicates. Avoid version numbers unless the user
     mentioned one.

Return only the JSON object matching the provided schema.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "application": {"type": "string"},
        "environment": {"type": "string"},
        "goal_facets": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
    },
    "required": ["application", "environment", "goal_facets", "queries"],
    "additionalProperties": False,
}


def generate_multimodal_query_plan(
    raw_request: str,
    *,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> MultimodalQueryPlan:
    """Call the multimodal LLM and return a structured query plan.

    Raises on any OpenAI error so the caller can decide whether to fall
    back to a single-query path or surface the failure.
    """
    user_content: list[dict[str, object]] = [
        {"type": "input_text", "text": f"User request:\n{raw_request.strip()}"},
    ]
    if image_bytes:
        mime = image_mime or "image/png"
        b64 = base64.b64encode(image_bytes).decode("ascii")
        user_content.append(
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
        )

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "multimodal_query_plan",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            }
        },
    )

    payload = json.loads(response.output_text or "{}")
    plan = MultimodalQueryPlan(**payload)
    plan.queries = _dedup(plan.queries)[: settings.max_queries]
    plan.goal_facets = _dedup(plan.goal_facets)
    return plan


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = " ".join(value.lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(value.strip())
    return out
