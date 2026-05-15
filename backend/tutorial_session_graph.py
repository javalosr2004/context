from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.images import UploadedImage
from backend.tutorial_guide import TutorialGuide, TutorialSessionPlanRequest
from backend.tutorial_schema import (
    PlannerNeedsContext,
    PlannerReady,
    TutorialPlan,
    TutorialStep,
)
from backend.tutorial_session_events import (
    ErrorEvent,
    ServerSessionEvent,
    StatusChangedEvent,
    TutorialActionDeltaEvent,
    TutorialActionEvent,
)
from backend.tutorial_tools import TutorialToolCallError

logger = logging.getLogger(__name__)

EventSink = Callable[[ServerSessionEvent], None]

_current_sink: ContextVar[EventSink | None] = ContextVar(
    "tutorial_session_event_sink", default=None
)


def emit_event(event: ServerSessionEvent) -> None:
    sink = _current_sink.get()
    if sink is not None:
        sink(event)


class TutorialSessionState(TypedDict, total=False):
    session_id: str
    goal: str
    messages: list[dict[str, str]]
    latest_screen: dict[str, str] | None
    current_plan: dict[str, Any] | None
    current_step_id: str | None
    completed_step_ids: list[str]
    pending_question: dict[str, str] | None
    status: str
    last_error: str | None


class TutorialSessionGraph:
    def __init__(self, tutorial_guide: TutorialGuide) -> None:
        self._tutorial_guide = tutorial_guide
        self._graph = self._compile_graph()

    def start(
        self,
        state: TutorialSessionState,
        event_sink: EventSink | None = None,
    ) -> dict[str, Any]:
        token = _current_sink.set(event_sink)
        try:
            return self._graph.invoke(state, config_for_session(state["session_id"]))
        finally:
            _current_sink.reset(token)

    def resume(
        self,
        session_id: str,
        value: dict[str, Any],
        event_sink: EventSink | None = None,
    ) -> dict[str, Any]:
        token = _current_sink.set(event_sink)
        try:
            return self._graph.invoke(
                Command(resume=value), config=config_for_session(session_id)
            )
        finally:
            _current_sink.reset(token)

    def state_for(self, session_id: str) -> TutorialSessionState:
        snapshot = self._graph.get_state(config_for_session(session_id))
        return TutorialSessionState(snapshot.values or {})

    def _compile_graph(self) -> Any:
        builder = StateGraph(TutorialSessionState)
        builder.add_node("receive_user_message", self._receive_user_message)
        builder.add_node("plan_or_ask_context", self._plan_or_ask_context)
        builder.add_node("wait_for_context", self._wait_for_context)
        builder.add_node("emit_plan", self._emit_plan)
        builder.add_node("wait_for_step_confirmation", self._wait_for_step_confirmation)
        builder.add_node("advance_or_replan", self._advance_or_replan)
        builder.add_node("complete", self._complete)

        builder.add_edge(START, "receive_user_message")
        builder.add_edge("receive_user_message", "plan_or_ask_context")
        builder.add_conditional_edges(
            "plan_or_ask_context",
            route_after_planning,
            {
                "wait_for_context": "wait_for_context",
                "emit_plan": "emit_plan",
            },
        )
        builder.add_edge("wait_for_context", "plan_or_ask_context")
        builder.add_edge("emit_plan", "wait_for_step_confirmation")
        builder.add_edge("wait_for_step_confirmation", "advance_or_replan")
        builder.add_conditional_edges(
            "advance_or_replan",
            route_after_confirmation,
            {
                "plan_or_ask_context": "plan_or_ask_context",
                "wait_for_step_confirmation": "wait_for_step_confirmation",
                "complete": "complete",
            },
        )
        builder.add_edge("complete", END)

        return builder.compile(checkpointer=InMemorySaver())

    def _receive_user_message(
        self,
        state: TutorialSessionState,
    ) -> TutorialSessionState:
        return TutorialSessionState(
            completed_step_ids=state.get("completed_step_ids", []),
            current_step_id=state.get("current_step_id"),
            current_plan=state.get("current_plan"),
            pending_question=None,
            status="planning",
            last_error=None,
        )

    def _plan_or_ask_context(
        self,
        state: TutorialSessionState,
    ) -> TutorialSessionState:
        emit_event(StatusChangedEvent(status="planning", label="Analyzing screen"))
        logger.info(
            "Graph node: plan_or_ask_context",
            extra={
                "session_id": state.get("session_id"),
                "goal_chars": len(state.get("goal", "")),
                "message_count": len(state.get("messages", [])),
                "has_screen": state.get("latest_screen") is not None,
            },
        )
        request = TutorialSessionPlanRequest(
            session_id=state["session_id"],
            goal=state["goal"],
            messages=state.get("messages", []),
            latest_screen=uploaded_image_from_screen(state.get("latest_screen")),
        )
        try:
            streamed_step_ids: list[str] = []

            def emit_streamed_step(step: TutorialStep) -> None:
                streamed_step_ids.append(step.step_id)
                emit_event(TutorialActionDeltaEvent(step=step))

            reply = self._tutorial_guide.create_session_planner_reply(
                request,
                on_streamed_step=emit_streamed_step,
            )
        except TutorialToolCallError as error:
            emit_event(ErrorEvent(code=error.code, message=error.message))
            logger.warning(
                "Tutorial tool stream failed; falling back to structured planner",
                extra={
                    "session_id": state.get("session_id"),
                    "code": error.code,
                    "detail": error.message,
                },
            )
            reply = self._tutorial_guide.create_structured_session_planner_reply(
                request
            )

        if isinstance(reply, PlannerNeedsContext):
            question = {
                "question_id": next_question_id(state),
                "prompt": reply.question,
            }
            return TutorialSessionState(
                messages=state.get("messages", [])
                + [{"role": "assistant", "content": reply.question}],
                pending_question=question,
                status="needs_context",
                last_error=None,
            )

        if isinstance(reply, PlannerReady):
            for step in unstreamed_steps(reply.plan.steps, streamed_step_ids):
                emit_event(TutorialActionEvent(step=step))
            return TutorialSessionState(
                current_plan=reply.plan.model_dump(mode="json"),
                current_step_id=None,
                pending_question=None,
                status="planned",
                last_error=None,
            )

        raise ValueError(f"Unsupported planner reply: {reply!r}")

    def _wait_for_context(
        self,
        state: TutorialSessionState,
    ) -> TutorialSessionState:
        pending_question = state.get("pending_question") or {}
        answer = interrupt(
            {
                "type": "context_question",
                "question_id": pending_question.get("question_id"),
                "prompt": pending_question.get("prompt"),
            }
        )
        answer_text = str(answer.get("text", "")).strip()
        latest_screen = answer.get("screen") or state.get("latest_screen")
        return TutorialSessionState(
            messages=state.get("messages", [])
            + [{"role": "user", "content": answer_text}],
            latest_screen=latest_screen,
            pending_question=None,
            status="planning",
            last_error=None,
        )

    def _emit_plan(self, state: TutorialSessionState) -> TutorialSessionState:
        emit_event(StatusChangedEvent(status="planning", label="Validating targets"))
        plan = plan_from_state(state)
        current_step_id = next_uncompleted_step_id(
            plan=plan,
            completed_step_ids=state.get("completed_step_ids", []),
        )
        return TutorialSessionState(
            current_step_id=current_step_id,
            status="awaiting_confirmation",
        )

    def _wait_for_step_confirmation(
        self,
        state: TutorialSessionState,
    ) -> TutorialSessionState:
        step_id = state.get("current_step_id")
        response = interrupt(
            {
                "type": "step_confirmation",
                "step_id": step_id,
            }
        )
        latest_screen = response.get("screen") or state.get("latest_screen")
        confirmed = bool(response.get("confirmed"))

        if confirmed and step_id is not None:
            return TutorialSessionState(
                completed_step_ids=append_unique(
                    state.get("completed_step_ids", []),
                    step_id,
                ),
                latest_screen=latest_screen,
                status="advancing",
                last_error=None,
            )

        note = str(response.get("note") or "").strip()
        message = f"Step {step_id} was rejected."
        if note:
            message = f"{message} User note: {note}"

        return TutorialSessionState(
            messages=state.get("messages", [])
            + [{"role": "user", "content": message}],
            latest_screen=latest_screen,
            status="planning",
            last_error=None,
        )

    def _advance_or_replan(
        self,
        state: TutorialSessionState,
    ) -> TutorialSessionState:
        if state.get("status") == "planning":
            return TutorialSessionState()

        plan = plan_from_state(state)
        next_step_id = next_uncompleted_step_id(
            plan=plan,
            completed_step_ids=state.get("completed_step_ids", []),
        )
        if next_step_id is None:
            return TutorialSessionState(current_step_id=None, status="completed")

        return TutorialSessionState(
            current_step_id=next_step_id,
            status="awaiting_confirmation",
        )

    def _complete(self, state: TutorialSessionState) -> TutorialSessionState:
        return TutorialSessionState(status="completed", current_step_id=None)


def config_for_session(session_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": session_id}}


def route_after_planning(state: TutorialSessionState) -> str:
    if state.get("pending_question") is not None:
        return "wait_for_context"
    return "emit_plan"


def route_after_confirmation(state: TutorialSessionState) -> str:
    if state.get("status") == "planning":
        return "plan_or_ask_context"
    if state.get("status") == "completed":
        return "complete"
    return "wait_for_step_confirmation"


def uploaded_image_from_screen(screen: dict[str, str] | None) -> UploadedImage | None:
    if screen is None:
        return None
    return UploadedImage(
        data=base64.b64decode(screen["data_base64"]),
        mime_type=screen["mime_type"],
        filename="screen",
    )


def next_question_id(state: TutorialSessionState) -> str:
    message_count = len(state.get("messages", []))
    return f"question_{message_count + 1:03}"


def plan_from_state(state: TutorialSessionState) -> TutorialPlan:
    raw_plan = state.get("current_plan")
    if raw_plan is None:
        raise ValueError("Tutorial session has no current plan.")
    return TutorialPlan.model_validate(raw_plan)


def next_uncompleted_step_id(
    plan: TutorialPlan,
    completed_step_ids: list[str],
) -> str | None:
    completed = set(completed_step_ids)
    for step in plan.steps:
        if step.step_id not in completed:
            return step.step_id
    return None


def append_unique(values: list[str], value: str) -> list[str]:
    if value in values:
        return values
    return values + [value]


def unstreamed_steps(
    steps: list[TutorialStep],
    streamed_step_ids: list[str],
) -> list[TutorialStep]:
    streamed = set(streamed_step_ids)
    return [step for step in steps if step.step_id not in streamed]
