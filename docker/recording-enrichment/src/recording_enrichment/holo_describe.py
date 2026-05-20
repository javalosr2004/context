"""Describe a single UI action using HCompany's Holo chat gateway."""
from __future__ import annotations

import base64
import logging
import os
from typing import Literal, Optional, Protocol

from pydantic import BaseModel


logger = logging.getLogger(__name__)

PROMPT_VERSION = "describe-v2"


SYSTEM_PROMPT_TEMPLATE = """You are describing a single UI action that is part of a larger workflow.

USER GOAL FOR THE WORKFLOW:
"{goal}"

Given the target crop (tight) and context crop (wider) of the moment a user
performed an action, return a JSON object with:
  - target_phrase: short noun phrase naming the UI element, in the dialect a
    visual grounder would use to re-locate it. Include visible text in quotes
    and a disambiguating spatial/visual cue when needed.
  - kind: one of [button, input, link, tab, icon, list_item, cell, menu_item, text, other]
  - visible_text: the literal visible text on the element, or null.

The user goal is context for disambiguation only. Do NOT include the goal in
the target_phrase. Describe the element as it appears on screen, not the user's
intent.
"""


KIND_LITERALS = Literal[
    "button", "input", "link", "tab", "icon",
    "list_item", "cell", "menu_item", "text", "other",
]


class Description(BaseModel):
    target_phrase: str
    kind: KIND_LITERALS
    visible_text: Optional[str] = None


DESCRIPTION_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["target_phrase", "kind"],
    "properties": {
        "target_phrase": {"type": "string", "minLength": 1, "maxLength": 200},
        "kind": {
            "type": "string",
            "enum": [
                "button", "input", "link", "tab", "icon",
                "list_item", "cell", "menu_item", "text", "other",
            ],
        },
        "visible_text": {"type": ["string", "null"]},
    },
}


def build_system_prompt(goal: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(goal=goal)


def build_messages(goal: str, target_jpeg: bytes, context_jpeg: bytes) -> list[dict]:
    """Format the chat.completions messages array.

    Target crop is sent first, context second. Both as data URIs.
    """
    target_b64 = base64.b64encode(target_jpeg).decode("ascii")
    context_b64 = base64.b64encode(context_jpeg).decode("ascii")
    return [
        {"role": "system", "content": build_system_prompt(goal)},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Target crop (tight, centered on cursor):"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{target_b64}"}},
                {"type": "text", "text": "Context crop (wider, same cursor):"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{context_b64}"}},
                {"type": "text", "text": "Return JSON only."},
            ],
        },
    ]


class Describer(Protocol):
    def describe(self, target_jpeg: bytes, context_jpeg: bytes, goal: str) -> Description: ...


class HoloDescriber:
    """Production describer that hits the Holo chat.completions endpoint."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        from openai import OpenAI  # imported lazily so tests don't need openai

        self._model = model or os.environ.get("HOLO_MODEL", "holo3-35b")
        self._client = OpenAI(
            api_key=api_key or os.environ.get("HOLO_API_KEY", "missing"),
            base_url=base_url or os.environ.get("HOLO_BASE_URL", "https://api.hcompany.ai/v1"),
        )

    def describe(self, target_jpeg: bytes, context_jpeg: bytes, goal: str) -> Description:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=build_messages(goal, target_jpeg, context_jpeg),
            temperature=0.0,
            extra_body={
                "structured_outputs": {
                    "name": "ui_action_description",
                    "schema": DESCRIPTION_JSON_SCHEMA,
                }
            },
        )
        text = response.choices[0].message.content or ""
        return Description.model_validate_json(text)
