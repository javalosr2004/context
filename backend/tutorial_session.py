"""Async agent-loop tutorial session.

Replaces the LangGraph-based ``TutorialSessionGraph``. Each session owns
one ``asyncio.Task`` running a Codex/Claude-Code-style loop: call the
model with tools, execute the tool calls, feed the results back into the
next call, repeat until the model emits a final text answer.

Two kinds of tool calls are executed inline:
    - action tools (``tutorial_click``, ``tutorial_type``, ...) become
      ``TutorialStep`` records appended to the current plan.
    - ``tutorial_request_screen`` suspends the loop on an ``asyncio.Future``
      until the WebSocket layer delivers a fresh screenshot.

After the loop returns, any accumulated steps are walked one-by-one,
awaiting client confirmation between each. If a step is rejected the
agent loop is re-entered with the rejection note appended to the
conversation.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.images import UploadedImage
from backend.llm import LLMRequest, LLMTextDelta, LLMToolCallEvent, MultimodalLLM
from backend.tutorial_guide import TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT
from backend.tutorial_schema import TutorialPlan, TutorialStep
from backend.tutorial_session_events import (
    AwaitingConfirmationEvent,
    PlanReadyEvent,
    PlanUpdatedEvent,
    ScreenRequestedEvent,
    ScreenSnapshot,
    ServerSessionEvent,
    SessionCompletedEvent,
    StatusChangedEvent,
    StepReadyEvent,
    TextResponseEventLike,
    TutorialActionEvent,
)
from backend.tutorial_tools import (
    REQUEST_SCREEN_TOOL_NAME,
    TutorialToolCall,
    TutorialToolCallError,
    parse_request_screen_reason,
    plan_from_steps,
    step_from_tool_call,
)


logger = logging.getLogger(__name__)


EventSink = Callable[[ServerSessionEvent], Awaitable[None]]


MAX_AGENT_TURNS = 8
MAX_CONSECUTIVE_SCREEN_REQUESTS = 3


@dataclass
class HistoryEntry:
    role: str  # "user" | "assistant" | "tool"
    content: str


@dataclass
class TutorialSession:
    session_id: str
    llm: MultimodalLLM
    emit: EventSink
    goal: str | None = None
    history: list[HistoryEntry] = field(default_factory=list)
    plan_steps: list[TutorialStep] = field(default_factory=list)
    completed_step_ids: list[str] = field(default_factory=list)
    latest_screen: UploadedImage | None = None
    pending_screen: asyncio.Future[UploadedImage] | None = None
    pending_screen_request_id: str | None = None
    pending_step_starts: set[str] = field(default_factory=set)
    pending_step_confirmations: dict[str, tuple[bool, str]] = field(
        default_factory=dict
    )
    step_event: asyncio.Event = field(default_factory=asyncio.Event)
    awaiting_step_id: str | None = None
    current_task: asyncio.Task[None] | None = None
    plan_emitted: bool = False
    screen_request_counter: int = 0
    status: str = "created"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # -------- Public entry points (driven by the WS handler) --------

    async def handle_user_message(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        await self._cancel_current_task()
        self.goal = text
        self.plan_steps = []
        self.completed_step_ids = []
        self.plan_emitted = False
        self.history.append(HistoryEntry(role="user", content=text))
        await self._start_task(self._run_session())

    async def handle_user_screen(
        self,
        request_id: str,
        screen: ScreenSnapshot,
    ) -> None:
        future = self.pending_screen
        if future is None or self.pending_screen_request_id != request_id:
            logger.info(
                "Ignoring stray user_screen event",
                extra={
                    "session_id": self.session_id,
                    "request_id": request_id,
                    "expected_request_id": self.pending_screen_request_id,
                },
            )
            return
        image = uploaded_image_from_snapshot(screen)
        self.latest_screen = image
        if not future.done():
            future.set_result(image)

    async def handle_step_started(self, step_id: str) -> None:
        if not self._is_pending_plan_step(step_id):
            logger.info(
                "Ignoring stray step_started event",
                extra={
                    "session_id": self.session_id,
                    "step_id": step_id,
                    "expected_step_id": self.awaiting_step_id,
                },
            )
            return
        self.pending_step_starts.add(step_id)
        self.step_event.set()

    async def handle_user_confirmation(
        self,
        step_id: str,
        confirmed: bool,
        note: str | None,
    ) -> None:
        if not self._is_pending_plan_step(step_id):
            logger.info(
                "Ignoring stray user_confirmation event",
                extra={
                    "session_id": self.session_id,
                    "step_id": step_id,
                    "expected_step_id": self.awaiting_step_id,
                },
            )
            return
        self.pending_step_confirmations[step_id] = (confirmed, (note or "").strip())
        self.step_event.set()

    def _is_pending_plan_step(self, step_id: str) -> bool:
        if step_id in self.completed_step_ids:
            return False
        return any(step.step_id == step_id for step in self.plan_steps)

    async def shutdown(self) -> None:
        await self._cancel_current_task()

    # -------- Top-level session coroutine --------

    async def _run_session(self) -> None:
        try:
            while True:
                await self._run_agent_loop()
                if not self.plan_steps:
                    return
                replan = await self._walk_steps()
                if not replan:
                    await self.emit(SessionCompletedEvent())
                    self.status = "completed"
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Tutorial session crashed",
                extra={"session_id": self.session_id},
            )
            raise

    # -------- Agent loop --------

    async def _run_agent_loop(self) -> None:
        self.status = "planning"
        await self.emit(StatusChangedEvent(status="planning", label="Thinking"))

        consecutive_screen_requests = 0
        last_screen_reason = ""

        for turn in range(MAX_AGENT_TURNS):
            tool_calls, text = await asyncio.to_thread(self._call_llm_once)
            logger.info(
                "Agent loop turn",
                extra={
                    "session_id": self.session_id,
                    "turn": turn + 1,
                    "tool_calls": len(tool_calls),
                    "tool_call_names": [call.name for call in tool_calls],
                    "tool_call_args": [call.arguments for call in tool_calls],
                    "text_chars": len(text),
                },
            )

            if not tool_calls:
                text = text.strip()
                if text:
                    self.history.append(HistoryEntry(role="assistant", content=text))
                    await self.emit(TextResponseEventLike(text=text))
                self.status = "ready"
                await self.emit(StatusChangedEvent(status="ready", label="Ready"))
                return

            request_screen_call: TutorialToolCall | None = None
            for call in tool_calls:
                if call.name == REQUEST_SCREEN_TOOL_NAME:
                    request_screen_call = call
                    break
                await self._execute_action_call(call)

            if request_screen_call is not None:
                try:
                    last_screen_reason = parse_request_screen_reason(
                        request_screen_call
                    )
                except TutorialToolCallError:
                    pass
                consecutive_screen_requests += 1
                if consecutive_screen_requests >= MAX_CONSECUTIVE_SCREEN_REQUESTS:
                    await self._emit_screen_request_stall(last_screen_reason)
                    return
                await self._execute_screen_request(request_screen_call)
                # Loop again with the new screen available.
                continue

            consecutive_screen_requests = 0

            # All calls were action tools — agent loop is done for this turn.
            return

        logger.warning(
            "Agent loop hit MAX_AGENT_TURNS",
            extra={"session_id": self.session_id},
        )

    async def _emit_screen_request_stall(self, reason: str) -> None:
        reason = reason.strip()
        if reason:
            message = f"I need to see {reason}"
        else:
            message = (
                "I need to see a different screen before I can continue. "
                "Please switch to the relevant app or window."
            )
        logger.warning(
            "Agent loop stalled on repeated tutorial_request_screen",
            extra={
                "session_id": self.session_id,
                "reason": reason,
            },
        )
        self.history.append(HistoryEntry(role="assistant", content=message))
        await self.emit(TextResponseEventLike(text=message))
        self.status = "ready"
        await self.emit(StatusChangedEvent(status="ready", label="Ready"))

    def _call_llm_once(self) -> tuple[list[TutorialToolCall], str]:
        request = LLMRequest(
            system_prompt=TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT,
            user_text=render_history(self.goal or "", self.history),
            images=[self.latest_screen] if self.latest_screen is not None else [],
            enable_search_grounding=False,
            temperature=0,
        )
        tool_calls: list[TutorialToolCall] = []
        text_parts: list[str] = []
        for event in self.llm.stream_tutorial_events(request):
            if isinstance(event, LLMTextDelta):
                text_parts.append(event.text)
            elif isinstance(event, LLMToolCallEvent):
                tool_calls.append(event.tool_call)
        return tool_calls, "".join(text_parts)

    async def _execute_action_call(self, call: TutorialToolCall) -> None:
        try:
            step = step_from_tool_call(call, len(self.plan_steps))
        except TutorialToolCallError as error:
            logger.warning(
                "Discarding invalid tool call",
                extra={
                    "session_id": self.session_id,
                    "tool": call.name,
                    "error": error.message,
                },
            )
            self.history.append(
                HistoryEntry(
                    role="tool",
                    content=f"{call.name} rejected: {error.message}",
                )
            )
            return

        self.plan_steps.append(step)
        await self.emit(TutorialActionEvent(step=step))
        self.history.append(
            HistoryEntry(
                role="assistant",
                content=f"called {call.name}({call.arguments})",
            )
        )
        self.history.append(
            HistoryEntry(
                role="tool",
                content=f"{call.name} ok step_id={step.step_id}",
            )
        )

    async def _execute_screen_request(self, call: TutorialToolCall) -> None:
        try:
            reason = parse_request_screen_reason(call)
        except TutorialToolCallError as error:
            logger.warning(
                "Invalid request_screen call",
                extra={"session_id": self.session_id, "error": error.message},
            )
            self.history.append(
                HistoryEntry(
                    role="tool",
                    content=f"{call.name} rejected: {error.message}",
                )
            )
            return

        request_id = self._next_screen_request_id()
        self.pending_screen_request_id = request_id
        loop = asyncio.get_running_loop()
        self.pending_screen = loop.create_future()
        self.status = "needs_screen"

        await self.emit(StatusChangedEvent(status="needs_screen", label="Need a fresh screen"))
        await self.emit(ScreenRequestedEvent(request_id=request_id, reason=reason))

        try:
            await self.pending_screen
        finally:
            self.pending_screen = None
            self.pending_screen_request_id = None

        captured_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.history.append(
            HistoryEntry(
                role="assistant",
                content=f"called {call.name}({call.arguments})",
            )
        )
        self.history.append(
            HistoryEntry(
                role="tool",
                content=(
                    f"{call.name} ok — fresh screen captured at {captured_at} "
                    "is attached as the image in this turn. Plan from it; "
                    "do not request another screen unless the user has acted "
                    "since this capture."
                ),
            )
        )
        self.status = "planning"
        await self.emit(StatusChangedEvent(status="planning", label="Thinking"))

    # -------- Step walkthrough --------

    async def _walk_steps(self) -> bool:
        plan = plan_from_steps(self.goal or "", self.plan_steps)
        if not self.plan_emitted:
            await self.emit(PlanReadyEvent(plan=plan))
            self.plan_emitted = True
        else:
            await self.emit(PlanUpdatedEvent(plan=plan))

        for step in self.plan_steps:
            if step.step_id in self.completed_step_ids:
                continue
            replan_note = await self._await_step(step)
            if replan_note is not None:
                self.history.append(
                    HistoryEntry(role="user", content=replan_note)
                )
                # Reset accumulated plan so the agent loop builds fresh.
                self.plan_steps = []
                self.completed_step_ids = []
                return True

        return False

    async def _await_step(self, step: TutorialStep) -> str | None:
        self.awaiting_step_id = step.step_id
        step_index = self._plan_index(step.step_id)
        self.status = "step_ready"
        await self.emit(StepReadyEvent(step_id=step.step_id))

        try:
            # Phase 1: wait until this step starts, or the user advances past it.
            while step.step_id not in self.pending_step_starts:
                if self._has_later_event(step_index):
                    self.completed_step_ids.append(step.step_id)
                    return None
                if step.step_id in self.pending_step_confirmations:
                    break  # Confirmation arrived without an explicit start.
                await self._wait_for_step_event()
            self.pending_step_starts.discard(step.step_id)

            self.status = "awaiting_confirmation"
            await self.emit(AwaitingConfirmationEvent(step_id=step.step_id))

            # Phase 2: wait for this step's confirmation, or skip if user advanced.
            while step.step_id not in self.pending_step_confirmations:
                if self._has_later_event(step_index):
                    self.completed_step_ids.append(step.step_id)
                    return None
                await self._wait_for_step_event()
            confirmed, note = self.pending_step_confirmations.pop(step.step_id)
        finally:
            self.awaiting_step_id = None

        if confirmed:
            self.completed_step_ids.append(step.step_id)
            return None

        message = f"Step {step.step_id} was rejected."
        if note:
            message = f"{message} User note: {note}"
        return message

    def _plan_index(self, step_id: str) -> int:
        for index, step in enumerate(self.plan_steps):
            if step.step_id == step_id:
                return index
        return -1

    def _has_later_event(self, current_index: int) -> bool:
        signaled_ids = self.pending_step_starts | self.pending_step_confirmations.keys()
        for sid in signaled_ids:
            if self._plan_index(sid) > current_index:
                return True
        return False

    async def _wait_for_step_event(self) -> None:
        # Wait first, then clear: producers mutate state before set(), so any
        # set that races with our re-check will wake us up and we'll re-loop.
        await self.step_event.wait()
        self.step_event.clear()

    # -------- Task lifecycle --------

    async def _start_task(self, coro: Coroutine[None, None, None]) -> None:
        self.current_task = asyncio.create_task(coro)

    async def _cancel_current_task(self) -> None:
        task = self.current_task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self.current_task = None
            self.pending_screen = None
            self.pending_screen_request_id = None
            self.pending_step_starts.clear()
            self.pending_step_confirmations.clear()
            self.step_event.clear()
            self.awaiting_step_id = None

    def _next_screen_request_id(self) -> str:
        self.screen_request_counter += 1
        return f"screen_{self.screen_request_counter:03}"

    # -------- Read-only views --------

    def current_plan(self) -> TutorialPlan | None:
        if not self.plan_steps:
            return None
        return plan_from_steps(self.goal or "", self.plan_steps)


# ---------------- Helpers ----------------


def render_history(goal: str, history: list[HistoryEntry]) -> str:
    lines: list[str] = []
    if goal:
        lines.append(f"User goal: {goal}")
        lines.append("")
    lines.append("Conversation so far:")
    if not history:
        lines.append("- <none yet>")
        return "\n".join(lines)
    for entry in history:
        lines.append(f"[{entry.role}] {entry.content}")
    return "\n".join(lines)


def uploaded_image_from_snapshot(snapshot: ScreenSnapshot) -> UploadedImage:
    return UploadedImage(
        data=base64.b64decode(snapshot.data_base64),
        mime_type=snapshot.mime_type,
        filename="screen",
    )
