from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class TutorialPlanValidationError(ValueError):
    pass


class TutorialSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionTarget(TutorialSchemaModel):
    kind: Literal["element", "screen", "window", "region"]
    label: str | None = None
    role: str | None = None
    description: str | None = None
    text_nearby: list[str] = Field(default_factory=list)


class ClickAction(TutorialSchemaModel):
    type: Literal["click"]
    target: ActionTarget


class DoubleClickAction(TutorialSchemaModel):
    type: Literal["double_click"]
    target: ActionTarget


class RightClickAction(TutorialSchemaModel):
    type: Literal["right_click"]
    target: ActionTarget


class HoverAction(TutorialSchemaModel):
    type: Literal["hover"]
    target: ActionTarget


class TypeAction(TutorialSchemaModel):
    type: Literal["type"]
    target: ActionTarget
    text: str = Field(min_length=1)


class PressKeyAction(TutorialSchemaModel):
    type: Literal["press_key"]
    keys: list[str] = Field(min_length=1)


class ScrollAction(TutorialSchemaModel):
    type: Literal["scroll"]
    target: ActionTarget | None = None
    direction: Literal["up", "down", "left", "right"]
    amount: Literal["small", "medium", "large"]
    until: str | None = None


class DragAction(TutorialSchemaModel):
    type: Literal["drag"]
    target: ActionTarget
    direction: Literal["up", "down", "left", "right"]
    amount: Literal["small", "medium", "large"]


class WaitAction(TutorialSchemaModel):
    type: Literal["wait"]
    until: str = Field(min_length=1)
    timeout_ms: int | None = Field(default=None, gt=0)


class ConfirmAction(TutorialSchemaModel):
    type: Literal["confirm"]
    question: str = Field(min_length=1)
    expected_screen: str = Field(min_length=1)


TutorialAction = Annotated[
    ClickAction
    | DoubleClickAction
    | RightClickAction
    | HoverAction
    | TypeAction
    | PressKeyAction
    | ScrollAction
    | DragAction
    | WaitAction
    | ConfirmAction,
    Field(discriminator="type"),
]


class TutorialStep(TutorialSchemaModel):
    step_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    action: TutorialAction
    confidence: float = Field(ge=0.0, le=1.0)
    requires_confirmation: bool

    @model_validator(mode="before")
    @classmethod
    def normalize_requires_confirmation(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        action = data.get("action")
        action_type = action.get("type") if isinstance(action, dict) else None
        confidence = data.get("confidence")
        if action_type == "confirm" or is_low_confidence(confidence):
            return {**data, "requires_confirmation": True}

        return data

    @model_validator(mode="after")
    def require_confirmation_for_uncertainty(self) -> TutorialStep:
        if self.action.type == "confirm" and not self.requires_confirmation:
            raise ValueError("confirm actions must set requires_confirmation to true")
        if self.confidence < 0.7 and not self.requires_confirmation:
            raise ValueError("steps below 0.7 confidence must require confirmation")
        return self


class TutorialPlan(TutorialSchemaModel):
    schema_version: Literal["tutorial_plan.v1"]
    goal: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    steps: list[TutorialStep] = Field(min_length=1, max_length=8)


def parse_tutorial_plan(raw_json: str) -> TutorialPlan:
    try:
        return TutorialPlan.model_validate_json(raw_json)
    except ValidationError as error:
        raise TutorialPlanValidationError(
            "LLM returned an invalid tutorial plan."
        ) from error


def is_low_confidence(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value < 0.7
    )
