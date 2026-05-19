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
        "user_choice",
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
    prompt: str | None = Field(
        default=None,
        description=(
            "Free-text prompt for the user when type is 'user_choice'. "
            "The user is expected to take whatever action best fits "
            "(click, type, etc.); there is no deterministic target."
        ),
    )
    requires_confirmation: bool = Field(
        description=(
            "True when the user must explicitly confirm this action before "
            "the step advances. Always true for confirm actions."
        ),
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
    actions: list[TutorialAction] = Field(
        min_length=1,
        description=(
            "Ordered list of mechanical actions that together accomplish "
            "the step's user-perceived intent. Walked one at a time."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence from 0.0 to 1.0.",
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
        max_length=128,
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


UserMessageIntentKind = Literal["new_goal", "follow_up"]


class UserMessageIntent(TutorialSchemaModel):
    """Classifier output: is the new message a new goal or a follow-up?"""

    intent: UserMessageIntentKind = Field(
        description=(
            "'new_goal' if the user is switching to an unrelated task; "
            "'follow_up' if it refines, answers, or continues the existing goal."
        ),
    )


class SearchQueryRefinement(TutorialSchemaModel):
    """One concise web search query grounded in the user's screen."""

    query: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "A single web search query (roughly 5-12 words) that names the "
            "specific OS, app, and version visible on screen alongside the "
            "user's goal. Avoid generic phrasings."
        ),
    )


def parse_search_query_refinement(raw_json: str) -> SearchQueryRefinement:
    try:
        return SearchQueryRefinement.model_validate_json(raw_json)
    except ValidationError as error:
        raise TutorialPlanValidationError(
            "LLM returned an invalid search query refinement."
        ) from error


def search_query_refinement_response_schema() -> dict[str, Any]:
    return remove_gemini_unsupported_schema_keys(
        SearchQueryRefinement.model_json_schema()
    )


def parse_user_message_intent(raw_json: str) -> UserMessageIntent:
    try:
        return UserMessageIntent.model_validate_json(raw_json)
    except ValidationError as error:
        raise TutorialPlanValidationError(
            "LLM returned an invalid user message intent."
        ) from error


def user_message_intent_response_schema() -> dict[str, Any]:
    return remove_gemini_unsupported_schema_keys(UserMessageIntent.model_json_schema())


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
        normalize_tutorial_plan(plan)
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
    if not step.actions:
        raise ValueError("step must contain at least one action")
    for action in step.actions:
        validate_action_semantics(action)


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

    if action.type == "user_choice":
        if not has_text(action.prompt):
            raise ValueError("user_choice action requires prompt")
        if action.target is not None:
            raise ValueError("user_choice action must not carry a target")


def require_target(action: TutorialAction) -> None:
    if action.target is None:
        raise ValueError(f"{action.type} action requires target")


def has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def normalize_tutorial_plan(plan: TutorialPlan) -> TutorialPlan:
    """Apply deterministic post-processing to a validated plan in-place.

    Currently collapses a `click` action that is immediately followed within
    the same step by a `type` action on the same target: the click is
    redundant since clicking to type *is* the typing gesture, and emitting
    both shows the user two highlights on the same UI region.
    """
    for step in plan.steps:
        step.actions = _collapse_click_then_type_same_target(step.actions)
    return plan


def _collapse_click_then_type_same_target(
    actions: list[TutorialAction],
) -> list[TutorialAction]:
    result: list[TutorialAction] = []
    index = 0
    while index < len(actions):
        current = actions[index]
        following = actions[index + 1] if index + 1 < len(actions) else None
        if (
            current.type == "click"
            and following is not None
            and following.type == "type"
            and current.target is not None
            and following.target is not None
            and _targets_equal(current.target, following.target)
        ):
            index += 1  # drop the click; emit the type on the next iteration
            continue
        result.append(current)
        index += 1
    return result


def _targets_equal(left: ActionTarget, right: ActionTarget) -> bool:
    return (
        left.kind == right.kind
        and _normalized(left.label) == _normalized(right.label)
        and _normalized(left.role) == _normalized(right.role)
        and _normalized(left.description) == _normalized(right.description)
    )


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().lower()
    return stripped if stripped else None
