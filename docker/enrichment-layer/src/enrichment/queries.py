from __future__ import annotations

import json

from openai import OpenAI

from enrichment.config import settings
from enrichment.models import QueryPlan

SYSTEM_PROMPT = """You generate web search queries to find tutorials for software tasks.

Given a user request, identify:
- application: the software application involved (e.g. "Figma", "VS Code")
- goal: a short imperative phrase describing what the user wants to do
- queries: 3-5 distinct web search queries likely to surface step-by-step tutorials

Vary query phrasing (how-to, step-by-step, tutorial, guide). Avoid near-duplicates.
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
