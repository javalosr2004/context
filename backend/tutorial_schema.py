from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


INVALID_TUTORIAL_PLAN_MESSAGE = "LLM returned an invalid tutorial plan."
LOW_CONFIDENCE_THRESHOLD = 0.7
GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "additionalProperties",
        "additional_properties",
        "default",
    }
)


class TutorialPlanValidationError(ValueError):
    pass


class TutorialSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionTarget(TutorialSchemaModel):
    kind: Literal["element", "screen", "window", "region"] = Field(
        description="Type of UI target the overlay should locate."
    )
    label: str | None = Field(
        default=None,
        description="Visible label or accessible name for the target.",
    )
    role: str | None = Field(
        default=None,
        description="UI role such as button, menu item, text field, or window.",
    )
    description: str | None = Field(
        default=None,
        description="Semantic visual description useful for grounding on screen.",
    )


class TutorialAction(TutorialSchemaModel):
    type: Literal[
        "click",
        "double_click",
        "right_click",
        "hover",
        "type",
        "press_key",
        "scroll",
        "drag",
        "wait",
        "confirm",
    ] = Field(description="Action type supported by the overlay tutorial player.")
    target: ActionTarget | None = Field(
        default=None,
        description="Required for pointer actions and drag actions.",
    )
    text: str | None = Field(
        default=None,
        description="Text to enter. Only used when type is 'type'.",
    )
    key: str | None = Field(
        default=None,
        description="Keyboard key or shortcut. Only used when type is 'press_key'.",
    )
    direction: Literal["up", "down", "left", "right"] | None = Field(
        default=None,
        description="Direction for scroll or drag actions.",
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        le=10000,
        description="Wait duration in milliseconds. Only used when type is 'wait'.",
    )


class TutorialStep(TutorialSchemaModel):
    step_id: str = Field(
        min_length=1,
        description="Stable unique ID like step_001.",
    )
    instruction: str = Field(
        min_length=1,
        description="One concise user-facing overlay instruction.",
    )
    action: TutorialAction
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence from 0.0 to 1.0.",
    )
    requires_confirmation: bool = Field(
        description="True when the screen state or target is uncertain."
    )


class TutorialPlan(TutorialSchemaModel):
    schema_version: Literal["tutorial_plan.v1"]
    goal: str = Field(min_length=1, description="The user's requested task.")
    summary: str = Field(
        min_length=1,
        description="Short summary of the generated tutorial plan.",
    )
    steps: list[TutorialStep] = Field(
        min_length=1,
        max_length=32,
        description="Ordered tutorial steps for the overlay player.",
    )


DraftStepKind = Literal[
    "click",
    "type",
    "press_key",
    "scroll",
    "wait",
    "navigate",
    "verify",
    "other",
]


class DraftStep(TutorialSchemaModel):
    instruction: str = Field(
        min_length=1,
        description="One short human-readable sentence for the user.",
    )
    kind: DraftStepKind = Field(
        description="Coarse action kind hint; refiner may override.",
    )


class DraftPlan(TutorialSchemaModel):
    """Coarse hypothesis plan generated up-front from the goal.

    Not executable on its own — the agent loop refines each step against
    the live screen before emitting a TutorialStep.
    """

    schema_version: Literal["draft_plan.v1"] = "draft_plan.v1"
    goal: str = Field(min_length=1)
    steps: list[DraftStep] = Field(min_length=1, max_length=20)


def parse_draft_plan(raw_json: str) -> DraftPlan:
    try:
        return DraftPlan.model_validate_json(raw_json)
    except ValidationError as error:
        raise TutorialPlanValidationError(
            "LLM returned an invalid draft plan."
        ) from error


def draft_plan_response_schema() -> dict[str, Any]:
    return remove_gemini_unsupported_schema_keys(DraftPlan.model_json_schema())


def parse_tutorial_plan(raw_json: str) -> TutorialPlan:
    try:
        plan = TutorialPlan.model_validate_json(raw_json)
        validate_tutorial_plan_semantics(plan)
        return plan
    except (ValidationError, ValueError) as error:
        raise TutorialPlanValidationError(
            INVALID_TUTORIAL_PLAN_MESSAGE
        ) from error


def tutorial_plan_response_schema() -> dict[str, Any]:
    return remove_gemini_unsupported_schema_keys(TutorialPlan.model_json_schema())


def remove_gemini_unsupported_schema_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: remove_gemini_unsupported_schema_keys(child)
            for key, child in value.items()
            if key not in GEMINI_UNSUPPORTED_SCHEMA_KEYS
        }

    if isinstance(value, list):
        return [remove_gemini_unsupported_schema_keys(item) for item in value]

    return value


def validate_tutorial_plan_semantics(plan: TutorialPlan) -> None:
    for step in plan.steps:
        validate_step_semantics(step)


def validate_step_semantics(step: TutorialStep) -> None:
    validate_action_semantics(step.action)

    if step.action.type == "confirm" and not step.requires_confirmation:
        raise ValueError("confirm actions must set requires_confirmation to true")

    if (
        step.confidence < LOW_CONFIDENCE_THRESHOLD
        and not step.requires_confirmation
    ):
        raise ValueError("steps below 0.7 confidence must require confirmation")


def validate_action_semantics(action: TutorialAction) -> None:
    if action.type in {"click", "double_click", "right_click", "hover"}:
        require_target(action)

    if action.type == "type" and not has_text(action.text):
        raise ValueError("type action requires text")

    if action.type == "press_key" and not has_text(action.key):
        raise ValueError("press_key action requires key")

    if action.type == "scroll" and action.direction is None:
        raise ValueError("scroll action requires direction")

    if action.type == "drag":
        require_target(action)
        if action.direction is None:
            raise ValueError("drag action requires direction")

    if action.type == "wait" and action.duration_ms is None:
        raise ValueError("wait action requires duration_ms")


def require_target(action: TutorialAction) -> None:
    if action.target is None:
        raise ValueError(f"{action.type} action requires target")


def has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())
