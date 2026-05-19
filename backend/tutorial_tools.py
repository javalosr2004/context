"""Tutorial tool surface.

Two tools are exposed to the model:
    - ``tutorial_update_plan(plan, plan_reasoning)`` — emit the full
      remaining plan as a hypothesis. The backend merges this against
      the frozen prefix (completed + awaiting steps) via
      :func:`backend.plan_merge.merge_plan_tail`.
    - ``tutorial_request_screen(reason)`` — ask for a fresh screenshot.

Optional emission: a turn may call only ``tutorial_request_screen``; the
existing plan stands. Re-emission of an identical plan is allowed but
should be the model's deliberate choice, not a heartbeat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from backend.plan_merge import TailCandidate
from backend.tutorial_schema import (
    ActionTarget,
    TutorialAction,
    TutorialPlan,
    TutorialStep,
    normalize_tutorial_plan,
    remove_gemini_unsupported_schema_keys,
)


UPDATE_PLAN_TOOL_NAME = "tutorial_update_plan"
REQUEST_SCREEN_TOOL_NAME = "tutorial_request_screen"
REQUEST_COMPLETION_TOOL_NAME = "tutorial_request_completion"
TUTORIAL_TOOL_NAMES = frozenset({
    UPDATE_PLAN_TOOL_NAME,
    REQUEST_SCREEN_TOOL_NAME,
    REQUEST_COMPLETION_TOOL_NAME,
})

INVALID_TOOL_CALL = "invalid_tool_call"
INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"

TEMPLATE_STEP_ID = "pending"  # placeholder; merger replaces with real step_id


class TutorialToolCallError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TutorialToolCall:
    name: str
    arguments: str


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        # mode="after" so discriminator fields (which are Literal-coerced
        # before validators run) are not rejected by Pydantic's discriminator
        # machinery, which forbids mode="before" validators on the
        # discriminator field.
        if isinstance(value, str) and not value.strip():
            raise ValueError("String fields must not be blank.")
        return value


CONFIDENCE_DESCRIPTION = (
    "Your honest probability that this step is correct given everything you "
    "can see and infer right now, 0.0-1.0. Early items in the plan should be "
    "high (0.8-0.95) because the screen agrees with them. Late items are "
    "expected to be lower (0.2-0.5) — they are speculative tail. Do not "
    "shorten the plan to avoid low confidence; low confidence late in the "
    "plan is the signal we want."
)

REFINES_CURRENT_DESCRIPTION = (
    "Set true ONLY on the first item of your plan, and ONLY when this item "
    "is a sharper version of the step the user is currently on (the "
    "AWAITING entry in the Plan state block). The merger will keep that "
    "step's identity and stall counter, replacing only its payload. Leave "
    "false when the awaiting step is still the right action and your plan "
    "describes what comes after it (the awaiting step is preserved). Must "
    "be false on every item after the first, and must be false when no "
    "step is awaiting."
)


REQUIRES_CONFIRMATION_DESCRIPTION = (
    "Pause and wait for the user to confirm this action landed correctly "
    "before advancing. Default true for actions whose outcome is visible to "
    "the user (clicks, typing, scrolling). False for mechanical actions "
    "with no observable effect (press_key, wait). Always true for confirm."
)


class _ActionPayloadBase(_StrictModel):
    requires_confirmation: bool = Field(description=REQUIRES_CONFIRMATION_DESCRIPTION)


class ClickAction(_ActionPayloadBase):
    kind: Literal["click"]
    agent_description: str = Field(
        min_length=1,
        description=(
            "Short target name handed to a visual-grounding model. Use the "
            "canonical on-screen label or conventional control name as a "
            "human would say it: 'Sign up', 'the Apple menu', 'the "
            "username field', 'the Storage row in System Settings'. 2–8 "
            "words. Add a small parent-container disambiguator only when "
            "identity is genuinely ambiguous ('Sign up in the page "
            "header'). Do NOT describe pixel appearance (color, shape, "
            "icon glyph), absolute position ('top-right', 'lower-left', "
            "'above the divider'), or chain multiple spatial clauses — "
            "the grounder sees the same screen and does the looking."
        ),
    )
    requires_confirmation: bool = Field(
        default=True, description=REQUIRES_CONFIRMATION_DESCRIPTION
    )


class TypeAction(_ActionPayloadBase):
    kind: Literal["type"]
    copiable_text: str = Field(min_length=1)
    agent_description: str = Field(
        min_length=1,
        description=(
            "Short target name handed to a visual-grounding model. Use the "
            "canonical on-screen label or conventional control name as a "
            "human would say it: 'Sign up', 'the Apple menu', 'the "
            "username field', 'the Storage row in System Settings'. 2–8 "
            "words. Add a small parent-container disambiguator only when "
            "identity is genuinely ambiguous ('Sign up in the page "
            "header'). Do NOT describe pixel appearance (color, shape, "
            "icon glyph), absolute position ('top-right', 'lower-left', "
            "'above the divider'), or chain multiple spatial clauses — "
            "the grounder sees the same screen and does the looking."
        ),
    )
    requires_confirmation: bool = Field(
        default=True, description=REQUIRES_CONFIRMATION_DESCRIPTION
    )


class ScrollAction(_ActionPayloadBase):
    kind: Literal["scroll"]
    expected_end_state: str = Field(min_length=1)
    requires_confirmation: bool = Field(
        default=True, description=REQUIRES_CONFIRMATION_DESCRIPTION
    )


class PressKeyAction(_ActionPayloadBase):
    kind: Literal["press_key"]
    key: str = Field(min_length=1)
    requires_confirmation: bool = Field(
        default=False, description=REQUIRES_CONFIRMATION_DESCRIPTION
    )


class WaitAction(_ActionPayloadBase):
    kind: Literal["wait"]
    duration_ms: int = Field(ge=0, le=10000)
    requires_confirmation: bool = Field(
        default=False, description=REQUIRES_CONFIRMATION_DESCRIPTION
    )


class UserChoiceAction(_ActionPayloadBase):
    kind: Literal["user_choice"]
    prompt: str = Field(
        min_length=1,
        description=(
            "Short instruction shown to the user when the next move is a "
            "free choice they make themselves — picking which item to open, "
            "typing their own username, entering a search query they care "
            "about, etc. There is no deterministic target or string; the "
            "overlay renders this prompt and waits for the user to act."
        ),
    )
    requires_confirmation: bool = Field(
        default=True, description=REQUIRES_CONFIRMATION_DESCRIPTION
    )


ActionPayload = Annotated[
    Union[
        ClickAction,
        TypeAction,
        ScrollAction,
        PressKeyAction,
        WaitAction,
        UserChoiceAction,
    ],
    Field(discriminator="kind"),
]


class PlanItem(_StrictModel):
    refines_current: bool = Field(
        default=False, description=REFINES_CURRENT_DESCRIPTION
    )
    human_text: str = Field(min_length=1, description="One concise on-screen instruction.")
    confidence: float = Field(ge=0.0, le=1.0, description=CONFIDENCE_DESCRIPTION)
    actions: list[ActionPayload] = Field(
        min_length=1,
        description=(
            "Ordered mechanical actions that together accomplish this step's "
            "user-perceived intent. Each action is a JSON object whose "
            "discriminator field is named exactly \"kind\" (NOT \"action\" or "
            "\"type\"), with value one of: \"click\", \"type\", \"scroll\", "
            "\"press_key\", \"wait\", \"user_choice\". The remaining fields depend on kind "
            "(see the per-variant schemas). One step per user intent; "
            "decompose into atomic actions inside. Set "
            "requires_confirmation=true on the action whose result the user "
            "should verify before advancing — the backend will pause for "
            "user confirmation and then request a fresh screen so you can "
            "re-validate before the next step."
        ),
    )


PlanTailItem = PlanItem


class TutorialUpdatePlanArguments(_StrictModel):
    plan_reasoning: str = Field(
        min_length=1,
        description=(
            "One sentence: why this remaining trajectory, what changed from "
            "the prior emission (or 'unchanged' if you stand by it)."
        ),
    )
    abandon_awaiting: bool = Field(
        default=False,
        description=(
            "Set true ONLY when the AWAITING step is no longer valid given "
            "what you now see — the user is on a completely wrong screen, "
            "the target has disappeared, or the previous instruction was "
            "incorrect. When true, the awaiting step is REMOVED from the "
            "plan (it's neither completed nor refined) and your new plan "
            "replaces it from scratch. Mutually exclusive with "
            "refines_current=true on the first item. Completed steps are "
            "still preserved. Use sparingly: prefer refines_current when "
            "the step is right but the payload needs sharpening."
        ),
    )
    plan: list[PlanTailItem] = Field(
        min_length=1,
        max_length=128,
        description=(
            "Your complete remaining plan from the current cursor through "
            "goal completion. Always emit the full hypothesis; the backend "
            "preserves the frozen prefix automatically."
        ),
    )


class TutorialRequestScreenArguments(_StrictModel):
    reason: str = Field(min_length=1)


class TutorialRequestCompletionArguments(_StrictModel):
    reason: str = Field(
        min_length=1,
        description=(
            "One short sentence summarising why you believe the user's goal "
            "is reached. The backend shows this to the user verbatim and "
            "asks them to confirm before ending the tutorial."
        ),
    )


class _ToolCallPayload(_StrictModel):
    name: Literal[
        "tutorial_update_plan",
        "tutorial_request_screen",
        "tutorial_request_completion",
    ]
    arguments: dict[str, Any]


class _ToolCallList(_StrictModel):
    calls: list[_ToolCallPayload] = Field(min_length=1, max_length=4)


_tool_call_list_adapter = TypeAdapter(_ToolCallList)
_update_plan_adapter = TypeAdapter(TutorialUpdatePlanArguments)
_request_completion_adapter = TypeAdapter(TutorialRequestCompletionArguments)


# ---------------- Schema export (for LLM clients) ----------------


def tutorial_tool_response_schema() -> dict[str, Any]:
    return remove_gemini_unsupported_schema_keys(_ToolCallList.model_json_schema())


def openai_tutorial_tool_definitions() -> list[dict[str, Any]]:
    return [
        _build_openai_tool(
            name=UPDATE_PLAN_TOOL_NAME,
            description=(
                "Emit your complete remaining plan from the current cursor "
                "through goal completion. The plan is a hypothesis; you will "
                "rewrite it after the next screen. Only call this when the "
                "screen changes your hypothesis — otherwise just request the "
                "next screen and the existing plan stands."
            ),
            model=TutorialUpdatePlanArguments,
        ),
        _build_openai_tool(
            name=REQUEST_SCREEN_TOOL_NAME,
            description=(
                "Request a fresh screenshot from the user's device. Call "
                "this when the current screen is missing, stale, or "
                "insufficient — or at the end of a turn to verify the "
                "result of the in-flight step. After this is called, the "
                "rest of the turn is discarded."
            ),
            model=TutorialRequestScreenArguments,
        ),
        _build_openai_tool(
            name=REQUEST_COMPLETION_TOOL_NAME,
            description=(
                "Propose that the user's goal is reached and the tutorial "
                "should end. The backend shows your reason to the user and "
                "asks them to confirm before terminating the session. Only "
                "call this when the latest screen — or the user's last "
                "message — gives you a concrete reason to believe the goal "
                "is met. Do not use this as a way to abandon a stuck plan."
            ),
            model=TutorialRequestCompletionArguments,
        ),
    ]


def _build_openai_tool(
    name: str,
    description: str,
    model: type[BaseModel],
) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": add_strict_object_constraints(model.model_json_schema()),
        "strict": True,
    }


def add_strict_object_constraints(value: Any) -> Any:
    if isinstance(value, dict):
        strict_value: dict[str, Any] = {}
        for key, child in value.items():
            # OpenAI strict function schemas reject `oneOf` and `discriminator`.
            # Pydantic emits both for discriminated unions; rewrite `oneOf` to
            # `anyOf` and drop the discriminator metadata.
            if key == "discriminator":
                continue
            if key == "oneOf":
                strict_value["anyOf"] = add_strict_object_constraints(child)
                continue
            strict_value[key] = add_strict_object_constraints(child)

        properties = strict_value.get("properties")
        if isinstance(properties, dict):
            strict_value["required"] = list(properties.keys())
            strict_value["additionalProperties"] = False
        elif strict_value.get("type") == "object":
            strict_value["additionalProperties"] = False
        return strict_value

    if isinstance(value, list):
        return [add_strict_object_constraints(item) for item in value]

    return value


# ---------------- Parsing ----------------


def parse_tutorial_tool_call_list(raw_json: str) -> list[TutorialToolCall]:
    try:
        payload = _tool_call_list_adapter.validate_json(raw_json)
    except ValidationError as error:
        raise TutorialToolCallError(
            INVALID_TOOL_ARGUMENTS,
            f"Tutorial tool fallback returned invalid JSON: {error}",
        ) from error
    return [
        TutorialToolCall(name=call.name, arguments=json.dumps(call.arguments))
        for call in payload.calls
    ]


def is_request_screen_call(call: TutorialToolCall) -> bool:
    return call.name == REQUEST_SCREEN_TOOL_NAME


def is_update_plan_call(call: TutorialToolCall) -> bool:
    return call.name == UPDATE_PLAN_TOOL_NAME


def is_request_completion_call(call: TutorialToolCall) -> bool:
    return call.name == REQUEST_COMPLETION_TOOL_NAME


def parse_request_completion_reason(call: TutorialToolCall) -> str:
    try:
        arguments = _request_completion_adapter.validate_json(call.arguments)
    except ValidationError as error:
        raise TutorialToolCallError(
            INVALID_TOOL_ARGUMENTS,
            f"Invalid arguments for {call.name}: {error}",
        ) from error
    return arguments.reason


def parse_request_screen_reason(call: TutorialToolCall) -> str:
    try:
        payload = json.loads(call.arguments)
        arguments = TutorialRequestScreenArguments.model_validate(payload)
    except (ValidationError, json.JSONDecodeError) as error:
        raise TutorialToolCallError(
            INVALID_TOOL_ARGUMENTS,
            f"Invalid arguments for {call.name}: {error}",
        ) from error
    return arguments.reason


def parse_update_plan_arguments(call: TutorialToolCall) -> TutorialUpdatePlanArguments:
    if call.name != UPDATE_PLAN_TOOL_NAME:
        raise TutorialToolCallError(
            INVALID_TOOL_CALL,
            f"Expected {UPDATE_PLAN_TOOL_NAME}, got {call.name!r}.",
        )
    try:
        return _update_plan_adapter.validate_json(call.arguments)
    except ValidationError as error:
        raise TutorialToolCallError(
            INVALID_TOOL_ARGUMENTS,
            f"Invalid arguments for {call.name}: {error}",
        ) from error


# ---------------- Materialization: PlanTailItem -> TailCandidate ----------------


def candidates_from_arguments(
    arguments: TutorialUpdatePlanArguments,
) -> list[TailCandidate]:
    return [_candidate_from_item(item) for item in arguments.plan]


def _candidate_from_item(item: PlanTailItem) -> TailCandidate:
    template = _step_template_from_item(item)
    return TailCandidate(
        refines_current=item.refines_current, step_template=template
    )


def _step_template_from_item(item: PlanItem) -> TutorialStep:
    actions = [_action_from_payload(payload, item.human_text) for payload in item.actions]
    return TutorialStep(
        step_id=TEMPLATE_STEP_ID,
        instruction=item.human_text,
        actions=actions,
        confidence=item.confidence,
    )


def _action_from_payload(payload: ActionPayload, human_text: str) -> TutorialAction:
    if isinstance(payload, ClickAction):
        return TutorialAction(
            type="click",
            target=ActionTarget(kind="element", description=payload.agent_description),
            requires_confirmation=payload.requires_confirmation,
        )
    if isinstance(payload, TypeAction):
        return TutorialAction(
            type="type",
            target=ActionTarget(kind="element", description=payload.agent_description),
            text=payload.copiable_text,
            requires_confirmation=payload.requires_confirmation,
        )
    if isinstance(payload, ScrollAction):
        return TutorialAction(
            type="scroll",
            target=ActionTarget(kind="screen", description=payload.expected_end_state),
            direction=_infer_scroll_direction(
                f"{human_text} {payload.expected_end_state}"
            ),
            requires_confirmation=payload.requires_confirmation,
        )
    if isinstance(payload, PressKeyAction):
        return TutorialAction(
            type="press_key",
            key=payload.key,
            requires_confirmation=payload.requires_confirmation,
        )
    if isinstance(payload, WaitAction):
        return TutorialAction(
            type="wait",
            duration_ms=payload.duration_ms,
            requires_confirmation=payload.requires_confirmation,
        )
    if isinstance(payload, UserChoiceAction):
        return TutorialAction(
            type="user_choice",
            prompt=payload.prompt,
            requires_confirmation=payload.requires_confirmation,
        )
    raise TutorialToolCallError(  # pragma: no cover — discriminated union is exhaustive
        INVALID_TOOL_ARGUMENTS,
        f"Unsupported action payload kind: {type(payload).__name__}",
    )


def _infer_scroll_direction(text: str) -> Literal["up", "down", "left", "right"]:
    lowered = text.lower()
    for direction in ("up", "left", "right", "down"):
        if direction in lowered:
            return direction
    return "down"


# ---------------- Plan assembly ----------------


def plan_from_steps(goal: str, steps: list[TutorialStep]) -> TutorialPlan:
    plan = TutorialPlan(
        schema_version="tutorial_plan.v1",
        goal=goal,
        summary="Follow the streamed tutorial actions.",
        steps=steps,
    )
    return normalize_tutorial_plan(plan)
