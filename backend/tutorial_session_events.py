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


class UserAnswer(TutorialSessionEventModel):
    question_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class UserAnswerEvent(TutorialSessionEventModel):
    """User's reply to an AssistantQuestionEvent batch.

    Every question_id from the batch must appear exactly once in
    ``answers`` for the backend to accept the response. The overlay is
    responsible for collecting all answers before submitting.
    """

    type: Literal["user_answer"]
    batch_id: str = Field(min_length=1)
    answers: list[UserAnswer] = Field(min_length=1)


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


class StepAnnotationCorrections(TutorialSessionEventModel):
    """Optional human corrections attached to an off-track verdict.

    Each field targets a specific agent so the extractor can emit per-agent
    eval fixtures without re-parsing free text.
    """

    instruction: str | None = None
    target_bbox: tuple[float, float, float, float] | None = None
    verifier_should_have_said: Literal["ok", "blocked"] | None = None


class UserStepAnnotationEvent(TutorialSessionEventModel):
    """Human eval annotation attached to a step.

    Emitted by the overlay when the user toggles eval mode and marks a step.
    ``verdict`` is the minimum payload; ``category`` and ``corrections`` are
    populated when the annotator drills in.
    """

    type: Literal["user_step_annotation"]
    step_id: str = Field(min_length=1)
    action_index: int = Field(ge=0)
    frame_hash: str | None = None
    verdict: Literal["correct", "off_track", "ambiguous"]
    category: Literal["plan", "grounding", "verifier", "loop"] | None = None
    note: str | None = None
    corrections: StepAnnotationCorrections | None = None


class UserCompletionResponseEvent(TutorialSessionEventModel):
    """User reply to a CompletionProposedEvent.

    confirmed=True  -> end the session.
    confirmed=False -> keep going; ``note`` is appended to history so the
    planner sees the user's reason for continuing.
    """

    type: Literal["user_completion_response"]
    confirmed: bool
    note: str | None = None


ClientSessionEvent = Annotated[
    UserMessageEvent
    | UserAnswerEvent
    | StepStartedEvent
    | UserConfirmationEvent
    | UserScreenEvent
    | UserCompletionResponseEvent
    | UserStepAnnotationEvent,
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


class AssistantQuestion(TutorialSessionEventModel):
    question_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    response_mode: Literal["options", "free_text"]
    options: list[str] = Field(default_factory=list)
    # Always true in v1 — the overlay always exposes an "Other..." field
    # alongside any suggested options. Kept on the wire so the Swift side
    # can branch on it later without a protocol change.
    allows_custom_answer: bool = True


class AssistantQuestionEvent(TutorialSessionEventModel):
    """A batch of 1-4 clarifying questions the planner needs answered
    before it commits to a plan.

    The overlay renders all questions at once and waits to collect every
    answer before sending a UserAnswerEvent keyed by ``batch_id``.
    """

    type: Literal["assistant_question"] = "assistant_question"
    batch_id: str
    reason: str
    questions: list[AssistantQuestion]


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
    # Full snippet text the planner actually ingested. Stored on the wire
    # so the grounding-faithfulness judge can score whether downstream
    # claims are supported by what was retrieved. May be empty for native
    # provider search where snippet content isn't exposed to us.
    content: str = ""


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


class CompletionProposedEvent(TutorialSessionEventModel):
    """Backend is asking the user to confirm that the tutorial is finished.

    ``source="llm"``   — the planner called tutorial_request_completion.
    ``source="backend"`` — the plan ran out and the backend is double-checking
    instead of auto-completing.

    The session waits for a UserCompletionResponseEvent before either firing
    SessionCompletedEvent (on confirmed=True) or re-engaging the planner
    (on confirmed=False).
    """

    type: Literal["completion_proposed"] = "completion_proposed"
    reason: str
    source: Literal["llm", "backend"]


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
    # Full verifier output kept on the wire so eval fixtures can score the
    # 4-way verdict, not just the coarse ok bool. See instruction_verifier.py.
    verdict: Literal["on_track", "blocked", "diverged", "unsure"] | None = None
    screen_summary: str | None = None


class LLMToolCallSummary(TutorialSessionEventModel):
    name: str
    arguments_chars: int = Field(ge=0)


class LLMCallEvent(TutorialSessionEventModel):
    """One LLM round-trip the session made. Full prompt/response are
    stored as a sidecar JSON file at ``llm_calls/{call_id}.json``; this
    event carries only the metadata + a ref so the JSONL stays grep-able.

    ``agent`` is the role the LLM played for this call (``planner``,
    ``verifier``, ``draft_planner``, ``query_refiner``, ``enricher``).
    Splitting by role is what lets eval extractors emit per-agent
    fixtures without re-parsing the trace.
    """

    type: Literal["llm_call"] = "llm_call"
    call_id: str
    agent: str
    model: str = ""
    elapsed_ms: float = Field(ge=0)
    image_count: int = Field(ge=0, default=0)
    prompt_system_chars: int = Field(ge=0, default=0)
    prompt_user_chars: int = Field(ge=0, default=0)
    response_text_chars: int = Field(ge=0, default=0)
    tool_calls: list[LLMToolCallSummary] = Field(default_factory=list)
    ok: bool = True
    error: str | None = None
    payload_ref: str = ""  # relative path inside the session dir


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
    | CompletionProposedEvent
    | InstructionVerificationStartedEvent
    | InstructionVerifiedEvent
    | LLMCallEvent
    | ErrorEvent
)
