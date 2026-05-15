from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from backend.tutorial_schema import (
    ActionTarget,
    TutorialAction,
    TutorialPlan,
    TutorialStep,
    remove_gemini_unsupported_schema_keys,
)


TUTORIAL_TOOL_NAMES = frozenset(
    {
        "tutorial_click",
        "tutorial_type",
        "tutorial_scroll",
        "tutorial_press_key",
        "tutorial_wait",
        "tutorial_confirm",
    }
)
INVALID_TOOL_CALL = "invalid_tool_call"
INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"


class TutorialToolCallError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TutorialToolCall:
    name: str
    arguments: str


class TutorialToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("String fields must not be blank.")
        return value


class TutorialClickArguments(TutorialToolArguments):
    human_text: str = Field(min_length=1)
    agent_description: str = Field(min_length=1)


class TutorialTypeArguments(TutorialToolArguments):
    human_text: str = Field(min_length=1)
    copiable_text: str = Field(min_length=1)
    agent_description: str = Field(min_length=1)


class TutorialScrollArguments(TutorialToolArguments):
    human_text: str = Field(min_length=1)
    expected_end_state: str = Field(min_length=1)


class TutorialPressKeyArguments(TutorialToolArguments):
    human_text: str = Field(min_length=1)
    key: str = Field(min_length=1)


class TutorialWaitArguments(TutorialToolArguments):
    human_text: str = Field(min_length=1)
    duration_ms: int = Field(ge=0, le=10000)


class TutorialConfirmArguments(TutorialToolArguments):
    human_text: str = Field(min_length=1)


class TutorialToolCallPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal[
        "tutorial_click",
        "tutorial_type",
        "tutorial_scroll",
        "tutorial_press_key",
        "tutorial_wait",
        "tutorial_confirm",
    ]
    arguments: dict[str, Any]


class TutorialToolCallList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: list[TutorialToolCallPayload] = Field(min_length=1, max_length=8)


tutorial_tool_call_list_adapter = TypeAdapter(TutorialToolCallList)


def tutorial_tool_response_schema() -> dict[str, Any]:
    return remove_gemini_unsupported_schema_keys(TutorialToolCallList.model_json_schema())


def openai_tutorial_tool_definitions() -> list[dict[str, Any]]:
    return [
        build_openai_tool(
            name="tutorial_click",
            description="Tell the overlay to guide the user to click a visible UI target.",
            model=TutorialClickArguments,
        ),
        build_openai_tool(
            name="tutorial_type",
            description="Tell the overlay to guide the user to type or paste text into a UI target.",
            model=TutorialTypeArguments,
        ),
        build_openai_tool(
            name="tutorial_scroll",
            description="Tell the overlay to guide the user to scroll until an expected state is visible.",
            model=TutorialScrollArguments,
        ),
        build_openai_tool(
            name="tutorial_press_key",
            description="Tell the overlay to guide the user to press a keyboard key or shortcut.",
            model=TutorialPressKeyArguments,
        ),
        build_openai_tool(
            name="tutorial_wait",
            description="Tell the overlay to wait for a short deterministic UI transition.",
            model=TutorialWaitArguments,
        ),
        build_openai_tool(
            name="tutorial_confirm",
            description="Ask the user to confirm that the screen matches the expected state.",
            model=TutorialConfirmArguments,
        ),
    ]


def build_openai_tool(
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
        strict_value = {
            key: add_strict_object_constraints(child)
            for key, child in value.items()
        }
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


def parse_tutorial_tool_call_list(raw_json: str) -> list[TutorialToolCall]:
    try:
        payload = tutorial_tool_call_list_adapter.validate_json(raw_json)
    except ValidationError as error:
        raise TutorialToolCallError(
            INVALID_TOOL_ARGUMENTS,
            f"Tutorial tool fallback returned invalid JSON: {error}",
        ) from error

    return [
        TutorialToolCall(name=call.name, arguments=json.dumps(call.arguments))
        for call in payload.calls
    ]


def step_from_tool_call(call: TutorialToolCall, index: int) -> TutorialStep:
    if call.name not in TUTORIAL_TOOL_NAMES:
        raise TutorialToolCallError(
            INVALID_TOOL_CALL,
            f"Unsupported tutorial tool call: {call.name}",
        )

    try:
        arguments = parse_tool_arguments(call)
    except (ValidationError, json.JSONDecodeError) as error:
        raise TutorialToolCallError(
            INVALID_TOOL_ARGUMENTS,
            f"Invalid arguments for {call.name}: {error}",
        ) from error

    return step_from_arguments(call.name, arguments, index)


def parse_tool_arguments(call: TutorialToolCall) -> TutorialToolArguments:
    payload = json.loads(call.arguments)
    if call.name == "tutorial_click":
        return TutorialClickArguments.model_validate(payload)
    if call.name == "tutorial_type":
        return TutorialTypeArguments.model_validate(payload)
    if call.name == "tutorial_scroll":
        return TutorialScrollArguments.model_validate(payload)
    if call.name == "tutorial_press_key":
        return TutorialPressKeyArguments.model_validate(payload)
    if call.name == "tutorial_wait":
        return TutorialWaitArguments.model_validate(payload)
    if call.name == "tutorial_confirm":
        return TutorialConfirmArguments.model_validate(payload)
    raise TutorialToolCallError(
        INVALID_TOOL_CALL,
        f"Unsupported tutorial tool call: {call.name}",
    )


def step_from_arguments(
    tool_name: str,
    arguments: TutorialToolArguments,
    index: int,
) -> TutorialStep:
    step_id = f"step_{index + 1:03}"

    if isinstance(arguments, TutorialClickArguments):
        action = TutorialAction(
            type="click",
            target=described_target(arguments.agent_description),
        )
        return TutorialStep(
            step_id=step_id,
            instruction=arguments.human_text,
            action=action,
            confidence=0.9,
            requires_confirmation=False,
        )

    if isinstance(arguments, TutorialTypeArguments):
        action = TutorialAction(
            type="type",
            target=described_target(arguments.agent_description),
            text=arguments.copiable_text,
        )
        return TutorialStep(
            step_id=step_id,
            instruction=arguments.human_text,
            action=action,
            confidence=0.9,
            requires_confirmation=False,
        )

    if isinstance(arguments, TutorialScrollArguments):
        action = TutorialAction(
            type="scroll",
            target=described_target(arguments.expected_end_state, kind="screen"),
            direction=infer_scroll_direction(
                f"{arguments.human_text} {arguments.expected_end_state}"
            ),
        )
        return TutorialStep(
            step_id=step_id,
            instruction=arguments.human_text,
            action=action,
            confidence=0.85,
            requires_confirmation=False,
        )

    if isinstance(arguments, TutorialPressKeyArguments):
        return TutorialStep(
            step_id=step_id,
            instruction=arguments.human_text,
            action=TutorialAction(type="press_key", key=arguments.key),
            confidence=0.9,
            requires_confirmation=False,
        )

    if isinstance(arguments, TutorialWaitArguments):
        return TutorialStep(
            step_id=step_id,
            instruction=arguments.human_text,
            action=TutorialAction(type="wait", duration_ms=arguments.duration_ms),
            confidence=0.9,
            requires_confirmation=False,
        )

    if isinstance(arguments, TutorialConfirmArguments):
        return TutorialStep(
            step_id=step_id,
            instruction=arguments.human_text,
            action=TutorialAction(type="confirm"),
            confidence=0.65,
            requires_confirmation=True,
        )

    raise TutorialToolCallError(
        INVALID_TOOL_ARGUMENTS,
        f"Unsupported arguments for {tool_name}.",
    )


def described_target(description: str, kind: str = "element") -> ActionTarget:
    return ActionTarget(kind=kind, description=description)


def infer_scroll_direction(text: str) -> Literal["up", "down", "left", "right"]:
    lowered = text.lower()
    for direction in ("up", "left", "right", "down"):
        if direction in lowered:
            return direction
    return "down"


def plan_from_steps(goal: str, steps: list[TutorialStep]) -> TutorialPlan:
    return TutorialPlan(
        schema_version="tutorial_plan.v1",
        goal=goal,
        summary="Follow the streamed tutorial actions.",
        steps=steps,
    )


def steps_from_tool_calls(calls: Iterator[TutorialToolCall]) -> Iterator[TutorialStep]:
    for index, call in enumerate(calls):
        yield step_from_tool_call(call, index)
