from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from backend.tutorial_guide import TutorialGuide
from backend.tutorial_schema import TutorialPlan
from backend.tutorial_session_events import (
    AssistantQuestionEvent,
    AwaitingConfirmationEvent,
    ClientSessionEvent,
    CreateTutorialSessionResponse,
    ErrorEvent,
    PlanReadyEvent,
    PlanUpdatedEvent,
    RequestReceivedEvent,
    ScreenSnapshot,
    ServerSessionEvent,
    SessionCompletedEvent,
    StatusChangedEvent,
    StepReadyEvent,
    TutorialSessionResponse,
    UserAnswerEvent,
    UserConfirmationEvent,
    UserMessageEvent,
)
from backend.tutorial_session_graph import EventSink, TutorialSessionGraph, TutorialSessionState


SESSION_NOT_FOUND = "session_not_found"
INVALID_SESSION_EVENT = "invalid_session_event"


class TutorialSessionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class TutorialSessionRecord:
    session_id: str
    status: str = "created"
    goal: str | None = None
    current_step_id: str | None = None
    completed_step_ids: list[str] = field(default_factory=list)
    pending_question: dict[str, str] | None = None
    current_plan: TutorialPlan | None = None
    last_error: str | None = None
    plan_emitted: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TutorialSessionManager:
    def __init__(
        self,
        tutorial_guide: TutorialGuide,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._graph = TutorialSessionGraph(tutorial_guide)
        self._session_id_factory = session_id_factory or (lambda: str(uuid4()))
        self._sessions: dict[str, TutorialSessionRecord] = {}

    def create_session(self) -> CreateTutorialSessionResponse:
        session_id = self._session_id_factory()
        self._sessions[session_id] = TutorialSessionRecord(session_id=session_id)
        return CreateTutorialSessionResponse(session_id=session_id, status="created")

    def get_session(self, session_id: str) -> TutorialSessionResponse:
        session = self._require_session(session_id)
        return response_from_session(session)

    def pre_threadpool_events(
        self,
        event: ClientSessionEvent,
    ) -> list[ServerSessionEvent]:
        if isinstance(event, UserMessageEvent):
            return [
                RequestReceivedEvent(),
                StatusChangedEvent(status="planning", label="Thinking"),
            ]
        if isinstance(event, UserAnswerEvent):
            return [StatusChangedEvent(status="planning", label="Thinking")]
        if isinstance(event, UserConfirmationEvent) and not event.confirmed:
            return [
                StatusChangedEvent(
                    status="planning",
                    label="Replanning from current screen",
                )
            ]
        return []

    def handle_client_event(
        self,
        session_id: str,
        event: ClientSessionEvent,
        event_sink: EventSink,
    ) -> None:
        if isinstance(event, UserMessageEvent):
            self._handle_user_message(session_id, event, event_sink)
            return
        if isinstance(event, UserAnswerEvent):
            self._handle_user_answer(session_id, event, event_sink)
            return
        if isinstance(event, UserConfirmationEvent):
            self._handle_user_confirmation(session_id, event, event_sink)
            return
        self._handle_step_started(session_id, event.step_id, event_sink)

    def _handle_user_message(
        self,
        session_id: str,
        event: UserMessageEvent,
        event_sink: EventSink,
    ) -> None:
        session = self._require_session(session_id)
        session.goal = event.text.strip()
        session.status = "planning"
        session.plan_emitted = False
        session.updated_at = datetime.now(UTC)
        messages = messages_with_user_turn(
            self._graph.state_for(session_id).get("messages", []),
            session.goal,
        )

        result = self._graph.start(
            TutorialSessionState(
                session_id=session_id,
                goal=session.goal,
                messages=messages,
                latest_screen=screen_to_state(event.screen),
                current_plan=None,
                current_step_id=None,
                completed_step_ids=[],
                pending_question=None,
                status="planning",
                last_error=None,
            ),
            event_sink=event_sink,
        )
        self._emit_events_after_graph_run(
            session_id, result, plan_was_rejected=False, event_sink=event_sink
        )

    def _handle_user_answer(
        self,
        session_id: str,
        event: UserAnswerEvent,
        event_sink: EventSink,
    ) -> None:
        session = self._require_session(session_id)
        pending_question = session.pending_question or {}
        if event.question_id != pending_question.get("question_id"):
            raise TutorialSessionError(
                INVALID_SESSION_EVENT,
                "The answer did not match the pending tutorial question.",
            )

        result = self._graph.resume(
            session_id,
            {
                "question_id": event.question_id,
                "text": event.text,
                "screen": screen_to_state(event.screen),
            },
            event_sink=event_sink,
        )
        self._emit_events_after_graph_run(
            session_id, result, plan_was_rejected=False, event_sink=event_sink
        )

    def _handle_user_confirmation(
        self,
        session_id: str,
        event: UserConfirmationEvent,
        event_sink: EventSink,
    ) -> None:
        session = self._require_session(session_id)
        if event.step_id != session.current_step_id:
            raise TutorialSessionError(
                INVALID_SESSION_EVENT,
                "The confirmation did not match the current tutorial step.",
            )

        result = self._graph.resume(
            session_id,
            {
                "step_id": event.step_id,
                "confirmed": event.confirmed,
                "note": event.note,
                "screen": screen_to_state(event.screen),
            },
            event_sink=event_sink,
        )
        self._emit_events_after_graph_run(
            session_id,
            result,
            plan_was_rejected=not event.confirmed,
            event_sink=event_sink,
        )

    def _handle_step_started(
        self,
        session_id: str,
        step_id: str,
        event_sink: EventSink,
    ) -> None:
        session = self._require_session(session_id)
        if step_id != session.current_step_id:
            raise TutorialSessionError(
                INVALID_SESSION_EVENT,
                "The started step is not the current tutorial step.",
            )

        session.status = "awaiting_confirmation"
        session.updated_at = datetime.now(UTC)
        event_sink(AwaitingConfirmationEvent(step_id=step_id))

    def _emit_events_after_graph_run(
        self,
        session_id: str,
        result: dict[str, Any],
        plan_was_rejected: bool,
        event_sink: EventSink,
    ) -> None:
        state = self._graph.state_for(session_id)
        session = self._require_session(session_id)
        update_session_from_state(session, state)

        if session.status == "needs_context" and session.pending_question is not None:
            event_sink(StatusChangedEvent(status="needs_context", label="Needs context"))
            event_sink(
                AssistantQuestionEvent(
                    question_id=session.pending_question["question_id"],
                    prompt=session.pending_question["prompt"],
                )
            )
            return

        if session.current_plan is not None and session.status == "awaiting_confirmation":
            if not session.plan_emitted:
                event_sink(PlanReadyEvent(plan=session.current_plan))
                session.plan_emitted = True
            elif plan_was_rejected:
                event_sink(PlanUpdatedEvent(plan=session.current_plan))

        if session.status == "awaiting_confirmation" and session.current_step_id is not None:
            event_sink(StepReadyEvent(step_id=session.current_step_id))
            event_sink(AwaitingConfirmationEvent(step_id=session.current_step_id))
            return

        if session.status == "completed":
            event_sink(SessionCompletedEvent())
            return

        if "__interrupt__" in result:
            event_sink(
                ErrorEvent(
                    code="unknown_interrupt",
                    message="The tutorial session paused without a recognized state.",
                )
            )

    def _require_session(self, session_id: str) -> TutorialSessionRecord:
        session = self._sessions.get(session_id)
        if session is None:
            raise TutorialSessionError(
                SESSION_NOT_FOUND,
                f"Tutorial session does not exist: {session_id}",
            )
        return session


def screen_to_state(screen: ScreenSnapshot | None) -> dict[str, str] | None:
    if screen is None:
        return None
    return screen.model_dump(mode="json")


def messages_with_user_turn(
    messages: list[dict[str, str]],
    text: str,
) -> list[dict[str, str]]:
    trimmed_text = text.strip()
    if not trimmed_text:
        return messages
    return messages + [{"role": "user", "content": trimmed_text}]


def update_session_from_state(
    session: TutorialSessionRecord,
    state: TutorialSessionState,
) -> None:
    session.goal = state.get("goal") or session.goal
    session.status = state.get("status") or session.status
    session.current_step_id = state.get("current_step_id")
    session.completed_step_ids = state.get("completed_step_ids", [])
    session.pending_question = state.get("pending_question")
    session.current_plan = plan_from_state(state)
    session.last_error = state.get("last_error")
    session.updated_at = datetime.now(UTC)


def plan_from_state(state: TutorialSessionState) -> TutorialPlan | None:
    raw_plan = state.get("current_plan")
    if raw_plan is None:
        return None
    return TutorialPlan.model_validate(raw_plan)


def response_from_session(session: TutorialSessionRecord) -> TutorialSessionResponse:
    return TutorialSessionResponse(
        session_id=session.session_id,
        status=session.status,
        goal=session.goal,
        current_step_id=session.current_step_id,
        completed_step_ids=session.completed_step_ids,
        pending_question=session.pending_question,
        current_plan=session.current_plan,
        last_error=session.last_error,
    )
