from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.tutorial_schema import DraftPlan, TutorialPlan, TutorialStep


class TutorialSessionEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScreenSnapshot(TutorialSessionEventModel):
    mime_type: Literal["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]
    data_base64: str = Field(min_length=1)


class CreateTutorialSessionResponse(TutorialSessionEventModel):
    session_id: str
    status: str


class TutorialSessionResponse(TutorialSessionEventModel):
    session_id: str
    status: str
    goal: str | None = None
    current_step_id: str | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    pending_question: dict[str, str] | None = None
    current_plan: TutorialPlan | None = None
    last_error: str | None = None


class UserMessageEvent(TutorialSessionEventModel):
    type: Literal["user_message"]
    text: str = Field(min_length=1)
    uploaded_images: list[ScreenSnapshot] = Field(default_factory=list)


class UserAnswerEvent(TutorialSessionEventModel):
    type: Literal["user_answer"]
    question_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class StepStartedEvent(TutorialSessionEventModel):
    type: Literal["step_started"]
    step_id: str = Field(min_length=1)
    action_index: int = Field(ge=0)


class UserConfirmationEvent(TutorialSessionEventModel):
    type: Literal["user_confirmation"]
    step_id: str = Field(min_length=1)
    action_index: int = Field(ge=0)
    confirmed: bool
    note: str | None = None
    # Stable post-action screen the client captured after waiting for the
    # screen to settle. When present, the backend treats it as latest_screen
    # and skips the request_screen round-trip before replanning.
    screen: ScreenSnapshot | None = None


class UserScreenEvent(TutorialSessionEventModel):
    type: Literal["user_screen"]
    request_id: str = Field(min_length=1)
    screen: ScreenSnapshot


ClientSessionEvent = Annotated[
    UserMessageEvent
    | UserAnswerEvent
    | StepStartedEvent
    | UserConfirmationEvent
    | UserScreenEvent,
    Field(discriminator="type"),
]

client_session_event_adapter = TypeAdapter(ClientSessionEvent)


class SessionReadyEvent(TutorialSessionEventModel):
    type: Literal["session_ready"] = "session_ready"
    session_id: str


class RequestReceivedEvent(TutorialSessionEventModel):
    type: Literal["request_received"] = "request_received"


class StatusChangedEvent(TutorialSessionEventModel):
    type: Literal["status_changed"] = "status_changed"
    status: str
    label: str


class AssistantQuestionEvent(TutorialSessionEventModel):
    type: Literal["assistant_question"] = "assistant_question"
    question_id: str
    prompt: str


class DraftPlanReadyEvent(TutorialSessionEventModel):
    type: Literal["draft_plan_ready"] = "draft_plan_ready"
    plan: DraftPlan


class PlanReadyEvent(TutorialSessionEventModel):
    type: Literal["plan_ready"] = "plan_ready"
    plan: TutorialPlan


class PlanUpdatedEvent(TutorialSessionEventModel):
    type: Literal["plan_updated"] = "plan_updated"
    plan: TutorialPlan


class TutorialActionEvent(TutorialSessionEventModel):
    type: Literal["tutorial_action"] = "tutorial_action"
    step: TutorialStep


class TutorialActionDeltaEvent(TutorialSessionEventModel):
    type: Literal["tutorial_action_delta"] = "tutorial_action_delta"
    step: TutorialStep


class TutorialTextDeltaEvent(TutorialSessionEventModel):
    type: Literal["tutorial_text_delta"] = "tutorial_text_delta"
    text: str = Field(min_length=1)


class TextResponseEventLike(TutorialSessionEventModel):
    type: Literal["text_response"] = "text_response"
    text: str = Field(min_length=1)


class StepReadyEvent(TutorialSessionEventModel):
    type: Literal["step_ready"] = "step_ready"
    step_id: str
    action_index: int = Field(ge=0)


class AwaitingConfirmationEvent(TutorialSessionEventModel):
    type: Literal["awaiting_confirmation"] = "awaiting_confirmation"
    step_id: str
    action_index: int = Field(ge=0)


class ScreenRequestedEvent(TutorialSessionEventModel):
    type: Literal["screen_requested"] = "screen_requested"
    request_id: str
    reason: str


class WebSearchSource(TutorialSessionEventModel):
    title: str
    url: str


class WebSearchStartedEvent(TutorialSessionEventModel):
    type: Literal["web_search_started"] = "web_search_started"
    query: str


class WebSearchCompletedEvent(TutorialSessionEventModel):
    type: Literal["web_search_completed"] = "web_search_completed"
    query: str
    source_count: int = Field(ge=0)
    sources: list[WebSearchSource] = Field(default_factory=list)
    elapsed_ms: float = Field(ge=0)


class AgentTurnEvent(TutorialSessionEventModel):
    type: Literal["agent_turn"] = "agent_turn"
    turn: int = Field(ge=1)
    max_turns: int = Field(ge=1)


class PlanDiffEvent(TutorialSessionEventModel):
    type: Literal["plan_diff"] = "plan_diff"
    frozen_prefix_len: int = Field(ge=0)
    new_tail_len: int = Field(ge=0)
    refined_current: bool
    total_steps: int = Field(ge=0)


class StepProgressEvent(TutorialSessionEventModel):
    type: Literal["step_progress"] = "step_progress"
    step_id: str
    step_index: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    action_index: int = Field(ge=0)
    total_actions: int = Field(ge=0)


class SessionCompletedEvent(TutorialSessionEventModel):
    type: Literal["session_completed"] = "session_completed"


class InstructionVerificationStartedEvent(TutorialSessionEventModel):
    type: Literal["instruction_verification_started"] = (
        "instruction_verification_started"
    )
    step_id: str


class InstructionVerifiedEvent(TutorialSessionEventModel):
    type: Literal["instruction_verified"] = "instruction_verified"
    step_id: str
    ok: bool
    reason: str | None = None


class ErrorEvent(TutorialSessionEventModel):
    type: Literal["error"] = "error"
    code: str
    message: str


ServerSessionEvent = (
    SessionReadyEvent
    | RequestReceivedEvent
    | StatusChangedEvent
    | AssistantQuestionEvent
    | DraftPlanReadyEvent
    | PlanReadyEvent
    | PlanUpdatedEvent
    | TutorialActionEvent
    | TutorialActionDeltaEvent
    | TutorialTextDeltaEvent
    | TextResponseEventLike
    | StepReadyEvent
    | AwaitingConfirmationEvent
    | ScreenRequestedEvent
    | WebSearchStartedEvent
    | WebSearchCompletedEvent
    | AgentTurnEvent
    | PlanDiffEvent
    | StepProgressEvent
    | SessionCompletedEvent
    | InstructionVerificationStartedEvent
    | InstructionVerifiedEvent
    | ErrorEvent
)
