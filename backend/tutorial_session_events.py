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


class UserAnswerEvent(TutorialSessionEventModel):
    type: Literal["user_answer"]
    question_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class StepStartedEvent(TutorialSessionEventModel):
    type: Literal["step_started"]
    step_id: str = Field(min_length=1)


class UserConfirmationEvent(TutorialSessionEventModel):
    type: Literal["user_confirmation"]
    step_id: str = Field(min_length=1)
    confirmed: bool
    note: str | None = None


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


class AwaitingConfirmationEvent(TutorialSessionEventModel):
    type: Literal["awaiting_confirmation"] = "awaiting_confirmation"
    step_id: str


class ScreenRequestedEvent(TutorialSessionEventModel):
    type: Literal["screen_requested"] = "screen_requested"
    request_id: str
    reason: str


class SessionCompletedEvent(TutorialSessionEventModel):
    type: Literal["session_completed"] = "session_completed"


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
    | SessionCompletedEvent
    | ErrorEvent
)
