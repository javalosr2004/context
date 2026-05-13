from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from backend.images import UploadedImage
from backend.llm import LLMRequest, MultimodalLLM
from backend.tutorial_schema import TutorialPlan, parse_tutorial_plan


TUTORIAL_CREATOR_SYSTEM_PROMPT = (
    "Your task is to be an agentic tutorial creator. You will create verbose "
    "tutorials that describe what action to perform - click, hover, scroll. "
    "When useful, look for tutorials, official documentation, or other helpful "
    "current information with Google Search. Prefer concrete, step-by-step "
    "instructions over generic advice. If the screen or user intent is unclear, "
    "state the uncertainty and ask for confirmation before continuing."
)

TUTORIAL_PLAN_SYSTEM_PROMPT = """
You are a tutorial planner for a macOS overlay teaching system.

Return only valid JSON. Do not include Markdown. Do not include prose outside JSON.
The response must match schema_version "tutorial_plan.v1".
Return at most 8 steps.

Allowed action types:
click, double_click, right_click, hover, type, press_key, scroll, drag, wait, confirm.

Each step must include:
- step_id
- instruction
- action
- confidence
- requires_confirmation

Each step must contain exactly one action.
Do not invent action types.
Do not use a generic payload object. Use only the fields allowed by each action type.
Use confirm when confidence is below 0.7, the target is ambiguous, or the screen may not match the expected state.
Keep instruction short and readable for a human overlay.
Use semantic targets, not coordinates, unless coordinates were provided.

JSON shape:
{
  "schema_version": "tutorial_plan.v1",
  "goal": "string",
  "summary": "string",
  "steps": [
    {
      "step_id": "step_001",
      "instruction": "string",
      "action": {
        "type": "click",
        "target": {
          "kind": "element",
          "label": "string",
          "role": "string",
          "description": "string",
          "text_nearby": ["string"]
        }
      },
      "confidence": 0.0,
      "requires_confirmation": true
    }
  ]
}

Action schemas:
- click, double_click, right_click, hover: {"type": "...", "target": ActionTarget}
- type: {"type": "type", "target": ActionTarget, "text": "string"}
- press_key: {"type": "press_key", "keys": ["Meta", "K"]}
- scroll: {"type": "scroll", "target": ActionTarget optional, "direction": "up|down|left|right", "amount": "small|medium|large", "until": "string optional"}
- drag: {"type": "drag", "target": ActionTarget, "direction": "up|down|left|right", "amount": "small|medium|large"}
- wait: {"type": "wait", "until": "string", "timeout_ms": 5000 optional}
- confirm: {"type": "confirm", "question": "string", "expected_screen": "string"}

ActionTarget schema:
{"kind": "element|screen|window|region", "label": "string optional", "role": "string optional", "description": "string optional", "text_nearby": ["string"] optional}
""".strip()


@dataclass(frozen=True)
class TutorialStreamRequest:
    conversation_id: str
    text: str
    images: list[UploadedImage]


@dataclass(frozen=True)
class TutorialPlanRequest:
    conversation_id: str
    text: str
    images: list[UploadedImage]


class TutorialGuide:
    def __init__(self, llm: MultimodalLLM) -> None:
        self._llm = llm

    def create_plan(self, request: TutorialPlanRequest) -> TutorialPlan:
        raw_plan = self._llm.complete_text(
            LLMRequest(
                system_prompt=TUTORIAL_PLAN_SYSTEM_PROMPT,
                user_text=build_tutorial_plan_user_prompt(request.text),
                images=request.images,
                enable_search_grounding=False,
                response_mime_type="application/json",
            )
        )
        return parse_tutorial_plan(raw_plan)

    def stream_tutorial(self, request: TutorialStreamRequest) -> Iterator[str]:
        return self._llm.stream_text(
            LLMRequest(
                system_prompt=TUTORIAL_CREATOR_SYSTEM_PROMPT,
                user_text=request.text,
                images=request.images,
                enable_search_grounding=True,
            )
        )


def build_tutorial_plan_user_prompt(user_request: str) -> str:
    return (
        "Create a compact tutorial plan for this user request. "
        "Use the attached screen images as the current visual context.\n\n"
        f"User request: {user_request}"
    )
