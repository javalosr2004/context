from __future__ import annotations

import json

from openai import OpenAI

from enrichment.config import settings
from enrichment.models import QueryPlan

SYSTEM_PROMPT = """You generate web search queries to find tutorials for software tasks.

Given a user request, identify:
- application: the software application involved (e.g. "Figma", "VS Code")
- goal: a short imperative phrase describing what the user wants to do
- queries: 3-5 distinct web search queries likely to surface step-by-step
  tutorials AND authoritative sources for the application.

Query mix:
- At least 1-2 queries should use blog/tutorial phrasings ("how to", "step by
  step", "tutorial", "guide"). These surface community walkthroughs that
  non-technical users find easy to follow.
- At least 1 query should target the application's CANONICAL / authoritative
  source. Phrase it the way that source titles its own pages. Examples:
  - For developer tools: "quickstart", "getting started", "reference",
    "overview", "official documentation" (e.g. "Cloud Run deploy container
    quickstart").
  - For consumer/creative apps: "help center", "support", "official guide"
    (e.g. "Figma help center export PNG").
  - For niche/open-source projects: the project name + "docs" or
    "documentation" (e.g. "Ink/Stitch docs basic use").
  Pick the form that matches where the authoritative content actually lives
  for THIS application — don't force "documentation" on a consumer app.

Avoid near-duplicates. Avoid version numbers unless the user mentioned one.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "application": {"type": "string"},
        "goal": {"type": "string"},
        "queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["application", "goal", "queries"],
    "additionalProperties": False,
}


def generate_queries(raw_request: str) -> QueryPlan:
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_request},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "query_plan",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            }
        },
    )
    payload = json.loads(response.output_text or "{}")
    plan = QueryPlan(**payload)
    plan.queries = _dedup(plan.queries)[: settings.max_queries]
    return plan


def _dedup(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = " ".join(q.lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())
    return out
