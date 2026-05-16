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
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.images import UploadedImage
from backend.llm import LLMRequest, LLMTextDelta, LLMToolCallEvent, MultimodalLLM
from backend.tutorial_guide import (
    TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT,
    classify_user_message_intent,
    generate_draft_plan,
)
from backend.tutorial_schema import DraftPlan, TutorialPlan, TutorialStep
from backend.tutorial_session_events import (
    AwaitingConfirmationEvent,
    DraftPlanReadyEvent,
    PlanReadyEvent,
    PlanUpdatedEvent,
    ScreenRequestedEvent,
    ScreenSnapshot,
    ServerSessionEvent,
    SessionCompletedEvent,
    StatusChangedEvent,
    StepReadyEvent,
    TutorialTextDeltaEvent,
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
SCREEN_CHANGING_ACTION_TYPES = frozenset(
    {"click", "double_click", "right_click", "type", "press_key", "scroll", "drag"}
)


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
    uploaded_images: list[UploadedImage] = field(default_factory=list)
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
    step_counter: int = 0
    last_action_kind: str | None = None
    screen_is_stale: bool = False
    screen_captured_at: datetime | None = None
    draft_plan: DraftPlan | None = None
    draft_plan_task: asyncio.Task[None] | None = None
    status: str = "created"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # -------- Public entry points (driven by the WS handler) --------

    async def handle_user_message(
        self,
        text: str,
        uploaded_images: list[ScreenSnapshot] | None = None,
    ) -> None:
        text = text.strip()
        if not text:
            return
        await self._cancel_current_task()

        message_images = uploaded_images_from_snapshots(uploaded_images or [])
        intent = await self._classify_message_intent(text)
        if intent == "new_goal":
            await self._reset_for_new_goal(text, message_images)
        else:
            self.uploaded_images.extend(message_images)
            self.history.append(HistoryEntry(role="user", content=text))

        await self._start_task(self._run_session(refresh_screen=True))

    async def _classify_message_intent(self, text: str) -> str:
        """Decide whether `text` is a new goal or a follow-up.

        First message of the session is always a new goal — no classifier
        call. Otherwise route through the LLM; fall back to 'follow_up' on
        any failure so we never accidentally wipe accumulated context.
        """
        if self.goal is None:
            return "new_goal"
        try:
            return await asyncio.to_thread(
                classify_user_message_intent,
                self.llm,
                self.goal,
                self.draft_plan,
                text,
            )
        except Exception:
            logger.exception(
                "User message intent classification failed; defaulting to follow_up",
                extra={"session_id": self.session_id},
            )
            return "follow_up"

    async def _reset_for_new_goal(
        self,
        text: str,
        uploaded_images: list[UploadedImage],
    ) -> None:
        await self._cancel_draft_task()
        self.goal = text
        self.plan_steps = []
        self.completed_step_ids = []
        self.plan_emitted = False
        self.draft_plan = None
        self.uploaded_images = list(uploaded_images)
        self.step_counter = 0
        self.last_action_kind = None
        self.screen_is_stale = False
        self.history.append(HistoryEntry(role="user", content=text))

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
        self.screen_is_stale = False
        self.screen_captured_at = datetime.now(UTC)
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
        await self._cancel_draft_task()

    # -------- Top-level session coroutine --------

    async def _run_session(self, refresh_screen: bool = False) -> None:
        try:
            if refresh_screen:
                await self._request_screen(
                    "Capturing the current screen alongside the user's message."
                )
                self._kick_off_draft_plan()
            any_steps_walked = False
            while True:
                await self._run_agent_loop()
                unwalked = self._unwalked_steps()
                if not unwalked:
                    if any_steps_walked:
                        await self.emit(SessionCompletedEvent())
                        self.status = "completed"
                    return
                walk_started_completed = set(self.completed_step_ids)
                replan_requested = await self._walk_steps()
                any_steps_walked = True
                newly_completed = [
                    sid
                    for sid in self.completed_step_ids
                    if sid not in walk_started_completed
                ]
                needs_fresh_screen = replan_requested or self._completed_changed_screen(
                    newly_completed
                )
                if needs_fresh_screen:
                    await self._request_fresh_screen_after_user_action()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Tutorial session crashed",
                extra={"session_id": self.session_id},
            )
            raise

    def _unwalked_steps(self) -> list[TutorialStep]:
        completed = set(self.completed_step_ids)
        return [s for s in self.plan_steps if s.step_id not in completed]

    def _completed_changed_screen(self, completed_step_ids: list[str]) -> bool:
        if not completed_step_ids:
            return False
        steps_by_id = {step.step_id: step for step in self.plan_steps}
        return any(
            sid in steps_by_id
            and steps_by_id[sid].action.type in SCREEN_CHANGING_ACTION_TYPES
            for sid in completed_step_ids
        )

    # -------- Agent loop --------

    async def _run_agent_loop(self) -> None:
        self.status = "planning"
        await self.emit(StatusChangedEvent(status="planning", label="Thinking"))

        consecutive_screen_requests = 0
        last_screen_reason = ""

        for turn in range(MAX_AGENT_TURNS):
            tool_calls, text = await self._stream_llm_once()
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
                if self.screen_is_stale:
                    logger.info(
                        "Forcing tutorial_request_screen on text-only turn with stale screen",
                        extra={
                            "session_id": self.session_id,
                            "last_action_kind": self.last_action_kind,
                            "dropped_text_chars": len(text),
                        },
                    )
                    self.history.append(
                        HistoryEntry(
                            role="tool",
                            content=(
                                "Loop guard: dropped text response because the "
                                f"screen is stale after a {self.last_action_kind}. "
                                "Requesting a fresh screen and re-planning."
                            ),
                        )
                    )
                    synthetic_reason = (
                        f"verifying the result of the last {self.last_action_kind} "
                        "before continuing"
                    )
                    consecutive_screen_requests += 1
                    if consecutive_screen_requests >= MAX_CONSECUTIVE_SCREEN_REQUESTS:
                        await self._emit_screen_request_stall(synthetic_reason)
                        return
                    await self._execute_screen_request(
                        TutorialToolCall(
                            name=REQUEST_SCREEN_TOOL_NAME,
                            arguments=json.dumps({"reason": synthetic_reason}),
                        )
                    )
                    continue
                if text.strip():
                    self.history.append(HistoryEntry(role="assistant", content=text))
                    await self.emit(TextResponseEventLike(text=text))
                self.status = "ready"
                await self.emit(StatusChangedEvent(status="ready", label="Ready"))
                return

            request_screen_call = first_request_screen_call(tool_calls)
            action_calls = [
                call for call in tool_calls if call.name != REQUEST_SCREEN_TOOL_NAME
            ]

            # Hard guard: if the screen is stale (user just performed a
            # screen-changing action) and the model is about to emit more
            # actions without first asking for a fresh screen, override.
            # Otherwise the agent keeps re-emitting scrolls/clicks based on
            # a pre-action view it cannot verify.
            if (
                self.screen_is_stale
                and action_calls
                and request_screen_call is None
            ):
                logger.info(
                    "Forcing tutorial_request_screen due to stale screen",
                    extra={
                        "session_id": self.session_id,
                        "last_action_kind": self.last_action_kind,
                        "dropped_action_names": [c.name for c in action_calls],
                    },
                )
                self.history.append(
                    HistoryEntry(
                        role="tool",
                        content=(
                            "Loop guard: dropped action calls "
                            f"{[c.name for c in action_calls]} because the "
                            f"screen is stale after a {self.last_action_kind}. "
                            "Requesting a fresh screen first."
                        ),
                    )
                )
                synthetic_reason = (
                    f"verifying the result of the last {self.last_action_kind} "
                    "before continuing"
                )
                consecutive_screen_requests += 1
                if consecutive_screen_requests >= MAX_CONSECUTIVE_SCREEN_REQUESTS:
                    await self._emit_screen_request_stall(synthetic_reason)
                    return
                await self._execute_screen_request(
                    TutorialToolCall(
                        name=REQUEST_SCREEN_TOOL_NAME,
                        arguments=json.dumps({"reason": synthetic_reason}),
                    )
                )
                continue

            for call in action_calls:
                await self._execute_action_call(call)

            if request_screen_call is not None:
                if action_calls:
                    self.history.append(
                        HistoryEntry(
                            role="tool",
                            content=(
                                f"{REQUEST_SCREEN_TOOL_NAME} deferred until after "
                                "the user completes the planned action steps."
                            ),
                        )
                    )
                    return
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

    async def _stream_llm_once(self) -> tuple[list[TutorialToolCall], str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[LLMStreamEvent | Exception | None] = asyncio.Queue()

        def produce_events() -> None:
            try:
                for event in self.llm.stream_tutorial_events(self._build_llm_request()):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as error:  # noqa: BLE001 — re-raise on the session task
                loop.call_soon_threadsafe(queue.put_nowait, error)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        producer = asyncio.create_task(asyncio.to_thread(produce_events))
        tool_calls: list[TutorialToolCall] = []
        text_parts: list[str] = []

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if isinstance(event, Exception):
                    raise event
                if isinstance(event, LLMTextDelta):
                    text_parts.append(event.text)
                    logger.info(
                        "LLM text delta",
                        extra={
                            "session_id": self.session_id,
                            "delta": repr(event.text),
                            "delta_chars": len(event.text),
                        },
                    )
                    await self.emit(TutorialTextDeltaEvent(text=event.text))
                elif isinstance(event, LLMToolCallEvent):
                    tool_calls.append(event.tool_call)
        finally:
            await producer

        text = "".join(text_parts)
        if text_parts:
            logger.info(
                "LLM text concatenated",
                extra={
                    "session_id": self.session_id,
                    "text": repr(text),
                    "text_chars": len(text),
                    "delta_count": len(text_parts),
                },
            )

        return tool_calls, text

    def _build_llm_request(self) -> LLMRequest:
        request = LLMRequest(
            system_prompt=TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT,
            user_text=render_history(
                goal=self.goal or "",
                history=self.history,
                has_latest_screen=self.latest_screen is not None,
                draft_plan=self.draft_plan,
                plan_steps=self.plan_steps,
                completed_step_ids=self.completed_step_ids,
                last_action_kind=self.last_action_kind,
                screen_is_stale=self.screen_is_stale,
                uploaded_image_count=len(self.uploaded_images),
            ),
            images=self._llm_images(),
            enable_search_grounding=False,
            temperature=0,
        )
        return request

    def _llm_images(self) -> list[UploadedImage]:
        images: list[UploadedImage] = []
        if self.latest_screen is not None:
            images.append(self.latest_screen)
        images.extend(self.uploaded_images)
        return images

    # -------- Draft plan (Slice A) --------

    def _kick_off_draft_plan(self) -> None:
        if self.goal is None or self.draft_plan is not None:
            return
        if self.draft_plan_task is not None and not self.draft_plan_task.done():
            return
        goal = self.goal
        image = self.latest_screen
        images = list(self.uploaded_images)
        self.draft_plan_task = asyncio.create_task(
            self._run_draft_plan(goal, image, images)
        )

    async def _run_draft_plan(
        self,
        goal: str,
        image: UploadedImage | None,
        images: list[UploadedImage],
    ) -> None:
        try:
            plan = await asyncio.to_thread(
                generate_draft_plan, self.llm, goal, image, images
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Draft plan generation failed",
                extra={"session_id": self.session_id},
            )
            return
        # The session may have moved on to a new goal while we were
        # generating. Only adopt the draft if the goal still matches.
        if self.goal != goal:
            return
        self.draft_plan = plan
        await self.emit(DraftPlanReadyEvent(plan=plan))

    async def _cancel_draft_task(self) -> None:
        task = self.draft_plan_task
        if task is None or task.done():
            self.draft_plan_task = None
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self.draft_plan_task = None

    async def _execute_action_call(self, call: TutorialToolCall) -> None:
        try:
            step = step_from_tool_call(call, self.step_counter)
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
        self.step_counter += 1
        await self.emit(TutorialActionEvent(step=step))
        self.history.append(
            HistoryEntry(
                role="assistant",
                content=f"called {call.name}({_redact_action_args(call.arguments)})",
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
                    "is attached as the image in this turn. Plan from it. "
                    "After you instruct the user to do something, you may "
                    "request another screen to verify the result."
                ),
            )
        )
        self.status = "planning"
        await self.emit(StatusChangedEvent(status="planning", label="Thinking"))

    async def _request_fresh_screen_after_user_action(self) -> None:
        await self._request_screen(
            "Need to verify the current screen after the user action "
            "before planning the next instruction."
        )

    async def _request_screen(self, reason: str) -> None:
        self.latest_screen = None
        call = TutorialToolCall(
            name=REQUEST_SCREEN_TOOL_NAME,
            arguments=json.dumps({"reason": reason}),
        )
        await self._execute_screen_request(call)

    # -------- Step walkthrough --------

    async def _walk_steps(self) -> bool:
        plan = plan_from_steps(self.goal or "", self.plan_steps)
        if not self.plan_emitted:
            await self.emit(PlanReadyEvent(plan=plan))
            self.plan_emitted = True
        else:
            await self.emit(PlanUpdatedEvent(plan=plan))

        # Snapshot the pending steps. New steps added later (e.g. after a
        # replan) will be walked in the next outer iteration.
        for step in list(self.plan_steps):
            if step.step_id in self.completed_step_ids:
                continue
            replan_note = await self._await_step(step)
            if replan_note is not None:
                self.history.append(
                    HistoryEntry(role="user", content=replan_note)
                )
                # Truncate the plan to what was actually completed; keep
                # completion history and step_counter so re-planned steps
                # get fresh IDs that don't collide with rejected ones.
                completed = set(self.completed_step_ids)
                self.plan_steps = [
                    s for s in self.plan_steps if s.step_id in completed
                ]
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
            self.last_action_kind = step.action.type
            if step.action.type in SCREEN_CHANGING_ACTION_TYPES:
                self.screen_is_stale = True
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


def render_history(
    goal: str,
    history: list[HistoryEntry],
    has_latest_screen: bool = False,
    uploaded_image_count: int = 0,
    draft_plan: DraftPlan | None = None,
    plan_steps: list[TutorialStep] | None = None,
    completed_step_ids: list[str] | None = None,
    last_action_kind: str | None = None,
    screen_is_stale: bool = False,
) -> str:
    lines: list[str] = []
    if goal:
        lines.append(f"User goal: {goal}")
        lines.append("")
    lines.append("Loop state:")
    if has_latest_screen:
        if screen_is_stale:
            lines.append(
                "- latest_screen: attached but STALE — taken before the last "
                "action. Call tutorial_request_screen before emitting another "
                "action; do not trust the attached image for verification."
            )
        else:
            lines.append("- latest_screen: attached to this request")
    else:
        lines.append("- latest_screen: not attached yet")
    if uploaded_image_count:
        start_index = 2 if has_latest_screen else 1
        end_index = start_index + uploaded_image_count - 1
        if start_index == end_index:
            lines.append(
                f"- uploaded_reference_images: 1 attached as image {start_index}"
            )
        else:
            lines.append(
                "- uploaded_reference_images: "
                f"{uploaded_image_count} attached as images {start_index}-{end_index}"
            )
    if last_action_kind is not None:
        lines.append(f"- last_completed_action: {last_action_kind}")
    lines.append("")
    if draft_plan is not None:
        lines.append(
            "Draft plan hypothesis (refine against the screen, batch confidently "
            "when the screen agrees, deviate when it does not):"
        )
        for index, step in enumerate(draft_plan.steps, start=1):
            lines.append(f"  {index}. [{step.kind}] {step.instruction}")
        lines.append("")
    if plan_steps:
        completed = set(completed_step_ids or [])
        lines.append(
            "Current plan state (do NOT re-emit completed steps; append only "
            "what comes next):"
        )
        for step in plan_steps:
            status = "done" if step.step_id in completed else "pending"
            lines.append(
                f"  - {step.step_id} [{status}] {step.action.type}: {step.instruction}"
            )
        lines.append("")
    lines.append("Conversation so far:")
    if not history:
        lines.append("- <none yet>")
        return "\n".join(lines)
    for entry in history:
        lines.append(f"[{entry.role}] {entry.content}")
    return "\n".join(lines)


def _redact_action_args(arguments: str) -> str:
    """Drop perception-shaped fields from a tool-call arg string before it
    enters history. agent_description and confidence are evidence for a single
    decision; replaying them as 'facts' in the prompt makes the model anchor
    on its own prior description rather than the fresh screen."""
    try:
        parsed = json.loads(arguments)
    except (TypeError, ValueError):
        return arguments
    if not isinstance(parsed, dict):
        return arguments
    keep = {k: v for k, v in parsed.items() if k not in {"agent_description", "confidence"}}
    return json.dumps(keep, ensure_ascii=False)


def first_request_screen_call(
    tool_calls: list[TutorialToolCall],
) -> TutorialToolCall | None:
    for call in tool_calls:
        if call.name == REQUEST_SCREEN_TOOL_NAME:
            return call
    return None


def has_screen_changing_step(
    steps: list[TutorialStep],
    completed_step_ids: list[str],
) -> bool:
    completed = set(completed_step_ids)
    return any(
        step.step_id in completed and step.action.type in SCREEN_CHANGING_ACTION_TYPES
        for step in steps
    )


def uploaded_image_from_snapshot(snapshot: ScreenSnapshot) -> UploadedImage:
    return UploadedImage(
        data=base64.b64decode(snapshot.data_base64),
        mime_type=snapshot.mime_type,
        filename="screen",
    )


def uploaded_images_from_snapshots(
    snapshots: list[ScreenSnapshot],
) -> list[UploadedImage]:
    return [
        UploadedImage(
            data=base64.b64decode(snapshot.data_base64),
            mime_type=snapshot.mime_type,
            filename=f"uploaded_image_{index:03}",
        )
        for index, snapshot in enumerate(snapshots, start=1)
    ]
