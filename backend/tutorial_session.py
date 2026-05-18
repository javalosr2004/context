"""Async agent-loop tutorial session.

Each session owns one ``asyncio.Task`` running an agent loop: call the
model with tools, execute the tool calls, feed the results back into the
next call, repeat until the model emits a final text answer.

The model has two tools:
    - ``tutorial_update_plan`` proposes the full remaining plan as a
      hypothesis. The backend merges the proposal against the frozen
      prefix (completed + awaiting steps) via
      :func:`backend.plan_merge.merge_plan_tail`. A turn that does not
      call this tool means "the existing plan stands."
    - ``tutorial_request_screen`` suspends the loop on an ``asyncio.Future``
      until the WebSocket layer delivers a fresh screenshot.

After each agent loop the pending plan steps are walked one-by-one,
awaiting client confirmation between each. The next agent loop sees a
"frozen prefix" of completed + awaiting steps that it may not rewrite.
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
from backend.tutorial_schema import DraftPlan, TutorialAction, TutorialPlan, TutorialStep
from backend.web_ground import NullWebGroundProducer, WebGroundProducer
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
)
from backend.plan_merge import (
    PlanMergeError,
    PlanMergeResult,
    merge_plan_tail,
)
from backend.tutorial_tools import (
    REQUEST_SCREEN_TOOL_NAME,
    UPDATE_PLAN_TOOL_NAME,
    TutorialToolCall,
    TutorialToolCallError,
    candidates_from_arguments,
    is_request_screen_call,
    is_update_plan_call,
    parse_request_screen_reason,
    parse_update_plan_arguments,
    plan_from_steps,
)


logger = logging.getLogger(__name__)


EventSink = Callable[[ServerSessionEvent], Awaitable[None]]


MAX_AGENT_TURNS = 8
MAX_CONSECUTIVE_SCREEN_REQUESTS = 3
STALL_ATTEMPT_THRESHOLD = 2
SCREEN_CHANGING_ACTION_TYPES = frozenset(
    {"click", "double_click", "right_click", "type", "press_key", "scroll", "drag"}
)


@dataclass(frozen=True)
class _ActionOutcome:
    replan_note: str | None = None
    advanced_past_step: bool = False


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
    pending_step_starts: set[tuple[str, int]] = field(default_factory=set)
    pending_step_confirmations: dict[tuple[str, int], tuple[bool, str]] = field(
        default_factory=dict
    )
    step_event: asyncio.Event = field(default_factory=asyncio.Event)
    awaiting_step_id: str | None = None
    awaiting_action_index: int | None = None
    current_task: asyncio.Task[None] | None = None
    plan_emitted: bool = False
    screen_request_counter: int = 0
    step_counter: int = 0
    attempts_without_progress: dict[str, int] = field(default_factory=dict)
    prev_active_step_id: str | None = None
    last_action_kind: str | None = None
    screen_is_stale: bool = False
    screen_captured_at: datetime | None = None
    draft_plan: DraftPlan | None = None
    draft_plan_task: asyncio.Task[None] | None = None
    web_ground: WebGroundProducer = field(default_factory=NullWebGroundProducer)
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
        self.attempts_without_progress = {}
        self.prev_active_step_id = None
        self.last_action_kind = None
        self.screen_is_stale = False
        self.history.append(HistoryEntry(role="user", content=text))

    async def handle_user_screen(
        self,
        request_id: str,
        screen: ScreenSnapshot,
    ) -> None:
        # Always accept the screen — dropping it on a request_id mismatch
        # leaves the agent loop parked on `pending_screen` forever, which
        # presents as a hung session. A fresher frame is strictly better
        # than a hang.
        image = uploaded_image_from_snapshot(screen)
        self.latest_screen = image
        self.screen_is_stale = False
        self.screen_captured_at = datetime.now(UTC)

        future = self.pending_screen
        if future is None:
            logger.debug(
                "user_screen arrived with no pending future; stored as latest_screen",
                extra={
                    "session_id": self.session_id,
                    "request_id": request_id,
                },
            )
            return
        if self.pending_screen_request_id != request_id:
            logger.debug(
                "user_screen request_id mismatch; resolving pending future anyway",
                extra={
                    "session_id": self.session_id,
                    "request_id": request_id,
                    "expected_request_id": self.pending_screen_request_id,
                },
            )
        if not future.done():
            future.set_result(image)

    async def handle_step_started(self, step_id: str, action_index: int) -> None:
        # Record every step_started; the walk loop's `_has_later_event`
        # uses out-of-slot signals to advance past stale steps, and an
        # exact-slot signal unblocks the current wait.
        self.pending_step_starts.add((step_id, action_index))
        self.step_event.set()

    async def handle_user_confirmation(
        self,
        step_id: str,
        action_index: int,
        confirmed: bool,
        note: str | None,
    ) -> None:
        # Record every confirmation. Out-of-slot confirmations either
        # advance the walk loop via `_has_later_event` (when the slot is
        # past the current step) or sit harmlessly until garbage-collected
        # on session reset. Dropping them silently stalls the walk loop.
        if not self._is_awaiting_slot(step_id, action_index):
            logger.debug(
                "user_confirmation arrived for non-awaiting slot; recording anyway",
                extra={
                    "session_id": self.session_id,
                    "step_id": step_id,
                    "action_index": action_index,
                    "expected_step_id": self.awaiting_step_id,
                    "expected_action_index": self.awaiting_action_index,
                },
            )
        self.pending_step_confirmations[(step_id, action_index)] = (
            confirmed,
            (note or "").strip(),
        )
        self.step_event.set()

    def _is_awaiting_slot(self, step_id: str, action_index: int) -> bool:
        if step_id in self.completed_step_ids:
            return False
        if self.awaiting_step_id != step_id:
            return False
        if self.awaiting_action_index is None:
            return False
        return action_index == self.awaiting_action_index

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
            and any(a.type in SCREEN_CHANGING_ACTION_TYPES for a in steps_by_id[sid].actions)
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
                    self.history.append(HistoryEntry(
                        role="assistant", content=text))
                    await self.emit(TextResponseEventLike(text=text))
                self.status = "ready"
                await self.emit(StatusChangedEvent(status="ready", label="Ready"))
                return

            request_screen_call = first_request_screen_call(tool_calls)
            update_plan_calls = [
                c for c in tool_calls if is_update_plan_call(c)]
            unknown_calls = [
                c
                for c in tool_calls
                if not is_update_plan_call(c) and not is_request_screen_call(c)
            ]
            for call in unknown_calls:
                self.history.append(
                    HistoryEntry(
                        role="tool",
                        content=(
                            f"{call.name} rejected: unknown tool. The only "
                            f"available tools are {UPDATE_PLAN_TOOL_NAME} "
                            f"and {REQUEST_SCREEN_TOOL_NAME}."
                        ),
                    )
                )

            # Only the most recent update_plan in a turn is honored; earlier
            # ones would be immediately overwritten and just confuse history.
            if len(update_plan_calls) > 1:
                self.history.append(
                    HistoryEntry(
                        role="tool",
                        content=(
                            f"Multiple {UPDATE_PLAN_TOOL_NAME} calls in one "
                            "turn; only the last one was applied."
                        ),
                    )
                )
            for call in update_plan_calls[:-1]:
                self._log_dropped_update_plan(call)
            if update_plan_calls:
                await self._execute_plan_update_call(update_plan_calls[-1])

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

            # No request_screen this turn — agent loop is done.
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
        queue: asyncio.Queue[LLMStreamEvent |
                             Exception | None] = asyncio.Queue()

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
                awaiting_step_id=self.awaiting_step_id,
                awaiting_action_index=self.awaiting_action_index,
                attempts_without_progress=self.attempts_without_progress,
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
                generate_draft_plan,
                self.llm,
                goal,
                image,
                images,
                self.web_ground,
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

    async def _execute_plan_update_call(self, call: TutorialToolCall) -> None:
        try:
            arguments = parse_update_plan_arguments(call)
        except TutorialToolCallError as error:
            logger.warning(
                "Rejected tutorial_update_plan args",
                extra={"session_id": self.session_id, "error": error.message},
            )
            self.history.append(
                HistoryEntry(
                    role="tool",
                    content=f"{call.name} rejected: {error.message}",
                )
            )
            return

        candidates = candidates_from_arguments(arguments)
        frozen_prefix_ids = list(self.completed_step_ids)
        awaiting_in_prefix: str | None = None
        if (
            self.awaiting_step_id is not None
            and self.awaiting_step_id not in self.completed_step_ids
        ):
            frozen_prefix_ids.append(self.awaiting_step_id)
            awaiting_in_prefix = self.awaiting_step_id

        try:
            result: PlanMergeResult = merge_plan_tail(
                current_plan_steps=self.plan_steps,
                frozen_prefix_ids=frozen_prefix_ids,
                awaiting_step_id=awaiting_in_prefix,
                new_tail=candidates,
                step_counter=self.step_counter,
            )
        except (PlanMergeError, ValueError) as error:
            logger.warning(
                "Rejected plan merge",
                extra={"session_id": self.session_id, "error": str(error)},
            )
            self.history.append(
                HistoryEntry(
                    role="tool",
                    content=f"{call.name} rejected: {error}",
                )
            )
            return

        self.plan_steps = result.plan_steps
        self.step_counter = result.step_counter

        plan = plan_from_steps(self.goal or "", self.plan_steps)
        if not self.plan_emitted:
            await self.emit(PlanReadyEvent(plan=plan))
            self.plan_emitted = True
        else:
            await self.emit(PlanUpdatedEvent(plan=plan))

        self.history.append(
            HistoryEntry(
                role="assistant",
                content=(
                    f"called {call.name}(reasoning={arguments.plan_reasoning!r}, "
                    f"tail_len={len(candidates)})"
                ),
            )
        )
        live_tail_start = len(self.completed_step_ids)
        tail_summary = ", ".join(
            f"{step.step_id}=[{','.join(a.type for a in step.actions)}]"
            for step in result.plan_steps[live_tail_start:]
        )
        self.history.append(
            HistoryEntry(
                role="tool",
                content=(
                    f"{call.name} ok — new tail: [{tail_summary}]. "
                    "Completed prefix preserved."
                ),
            )
        )

    def _log_dropped_update_plan(self, call: TutorialToolCall) -> None:
        self.history.append(
            HistoryEntry(
                role="tool",
                content=(
                    f"{call.name} dropped (superseded by a later "
                    f"{UPDATE_PLAN_TOOL_NAME} call in the same turn)."
                ),
            )
        )

    def _active_step_id(self) -> str | None:
        """The step the model is currently 'pointed at' — awaiting step if
        any, otherwise the first unwalked step in the plan."""
        if self.awaiting_step_id is not None:
            return self.awaiting_step_id
        completed = set(self.completed_step_ids)
        for step in self.plan_steps:
            if step.step_id not in completed:
                return step.step_id
        return None

    def _record_screen_progress(self) -> None:
        """Update the stall counter after a fresh screen lands.

        If the active step is the same one we were pointing at before the
        request, the user did not advance and the model's prior plan did
        not get the user unstuck — bump that step's counter. Otherwise
        progress was made; reset.
        """
        active = self._active_step_id()
        if active is None:
            self.prev_active_step_id = None
            return
        if active == self.prev_active_step_id:
            self.attempts_without_progress[active] = (
                self.attempts_without_progress.get(active, 0) + 1
            )
        else:
            self.attempts_without_progress.pop(active, None)
        self.prev_active_step_id = active

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

        self._record_screen_progress()
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
        last_step = self._last_completed_step()
        if last_step is not None:
            reason = (
                f"Verifying the result of completed {last_step.step_id} "
                f"([{','.join(a.type for a in last_step.actions)}]: "
                f"{last_step.instruction}). "
                "The attached screen is the post-action state — confirm the "
                "action achieved its goal before planning the next move, "
                "and switch strategy rather than re-emitting an equivalent "
                "action."
            )
        else:
            reason = (
                "Need to verify the current screen after the user action "
                "before planning the next instruction."
            )
        await self._request_screen(reason)

    def _last_completed_step(self) -> TutorialStep | None:
        if not self.completed_step_ids:
            return None
        last_id = self.completed_step_ids[-1]
        for step in reversed(self.plan_steps):
            if step.step_id == last_id:
                return step
        return None

    async def _request_screen(self, reason: str) -> None:
        self.latest_screen = None
        call = TutorialToolCall(
            name=REQUEST_SCREEN_TOOL_NAME,
            arguments=json.dumps({"reason": reason}),
        )
        await self._execute_screen_request(call)

    # -------- Step walkthrough --------

    async def _walk_steps(self) -> bool:
        # Plan ready/updated events are emitted by _execute_plan_update_call
        # at the moment the plan changes — no need to re-emit on every walk.

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
                # step_counter monotonic so re-planned steps get fresh
                # IDs that don't collide with rejected ones.
                completed = set(self.completed_step_ids)
                self.plan_steps = [
                    s for s in self.plan_steps if s.step_id in completed
                ]
                self.prev_active_step_id = None
                return True

        return False

    async def _await_step(self, step: TutorialStep) -> str | None:
        self.awaiting_step_id = step.step_id
        step_index = self._plan_index(step.step_id)
        try:
            # Re-resolve the live step each iteration; a mid-await
            # refines_current merge may have replaced the actions list while
            # keeping the same step_id.
            action_index = 0
            while True:
                current = next(
                    (s for s in self.plan_steps if s.step_id == step.step_id),
                    step,
                )
                if action_index >= len(current.actions):
                    break
                action = current.actions[action_index]
                outcome = await self._await_action(
                    step_id=step.step_id,
                    action_index=action_index,
                    action=action,
                    step_index=step_index,
                )
                if outcome.advanced_past_step:
                    return None
                if outcome.replan_note is not None:
                    return outcome.replan_note
                action_index += 1
        finally:
            self.awaiting_step_id = None
            self.awaiting_action_index = None

        current = next(
            (s for s in self.plan_steps if s.step_id == step.step_id), step
        )
        self.completed_step_ids.append(current.step_id)
        last_action = current.actions[-1]
        self.last_action_kind = last_action.type
        if any(a.type in SCREEN_CHANGING_ACTION_TYPES for a in current.actions):
            self.screen_is_stale = True
        action_summary = ", ".join(a.type for a in current.actions)
        self.history.append(
            HistoryEntry(
                role="user",
                content=(
                    f"confirmed {current.step_id} ({action_summary}): "
                    f"{current.instruction}. The next attached screen is "
                    "the post-action state — verify the action achieved "
                    "its goal before emitting another step, and do not "
                    "re-emit any action equivalent to this one."
                ),
            )
        )
        return None

    async def _await_action(
        self,
        *,
        step_id: str,
        action_index: int,
        action: "TutorialAction",
        step_index: int,
    ) -> "_ActionOutcome":
        self.awaiting_action_index = action_index
        slot = (step_id, action_index)
        self.status = "step_ready"
        await self.emit(StepReadyEvent(step_id=step_id, action_index=action_index))

        while slot not in self.pending_step_starts:
            if self._has_later_event(step_index):
                self.completed_step_ids.append(step_id)
                return _ActionOutcome(advanced_past_step=True)
            if slot in self.pending_step_confirmations:
                break
            await self._wait_for_step_event()
        self.pending_step_starts.discard(slot)

        if not action.requires_confirmation:
            return _ActionOutcome()

        self.status = "awaiting_confirmation"
        await self.emit(
            AwaitingConfirmationEvent(
                step_id=step_id, action_index=action_index)
        )

        while slot not in self.pending_step_confirmations:
            if self._has_later_event(step_index):
                self.completed_step_ids.append(step_id)
                return _ActionOutcome(advanced_past_step=True)
            await self._wait_for_step_event()
        confirmed, note = self.pending_step_confirmations.pop(slot)

        if confirmed:
            return _ActionOutcome()

        message = (
            f"Step {step_id} action {action_index + 1} ({action.type}) was rejected."
        )
        if note:
            message = f"{message} User note: {note}"
        return _ActionOutcome(replan_note=message)

    def _plan_index(self, step_id: str) -> int:
        for index, step in enumerate(self.plan_steps):
            if step.step_id == step_id:
                return index
        return -1

    def _has_later_event(self, current_index: int) -> bool:
        signaled_ids = {sid for sid, _ in self.pending_step_starts} | {
            sid for sid, _ in self.pending_step_confirmations.keys()
        }
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
            self.awaiting_action_index = None

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
    awaiting_step_id: str | None = None,
    awaiting_action_index: int | None = None,
    attempts_without_progress: dict[str, int] | None = None,
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
                "action. Prefer tutorial_request_screen before rewriting the "
                "plan; do not trust the attached image for verification."
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
            "Draft plan hypothesis (use to seed your first tutorial_update_plan "
            "call; refine against the screen, drop or rewrite items that the "
            "screen contradicts):"
        )
        for index, step in enumerate(draft_plan.steps, start=1):
            lines.append(f"  {index}. [{step.kind}] {step.instruction}")
        lines.append("")
    if plan_steps:
        _render_plan_block(
            lines,
            plan_steps=plan_steps,
            completed_step_ids=completed_step_ids or [],
            awaiting_step_id=awaiting_step_id,
            awaiting_action_index=awaiting_action_index,
            attempts_without_progress=attempts_without_progress or {},
        )
    lines.append("Conversation so far:")
    if not history:
        lines.append("- <none yet>")
        return "\n".join(lines)
    for entry in history:
        lines.append(f"[{entry.role}] {entry.content}")
    return "\n".join(lines)


def _render_plan_block(
    lines: list[str],
    *,
    plan_steps: list[TutorialStep],
    completed_step_ids: list[str],
    awaiting_step_id: str | None,
    awaiting_action_index: int | None,
    attempts_without_progress: dict[str, int],
) -> None:
    completed = set(completed_step_ids)
    lines.append(
        "Plan state — your next tutorial_update_plan replaces the TAIL. "
        "Completed steps are immutable. The AWAITING step (if any) is the "
        "step the user is currently on; set refines_current=true on the "
        "first plan item to refine that step in place (same identity, new "
        "payload), or leave refines_current=false to keep the awaiting "
        "step as-is and have your plan describe what comes after it:"
    )
    frozen_split_index = 0
    for index, step in enumerate(plan_steps):
        if step.step_id in completed or step.step_id == awaiting_step_id:
            frozen_split_index = index + 1
        else:
            break

    lines.append("  COMPLETED (immutable):")
    completed_steps = [
        s for s in plan_steps[:frozen_split_index] if s.step_id in completed
    ]
    if not completed_steps:
        lines.append("    <none>")
    else:
        for step in completed_steps:
            lines.append(
                f"    - {step.step_id} [done] "
                f"{_format_action_summary(step)}: {step.instruction}"
            )

    if awaiting_step_id is not None:
        awaiting_step = next(
            (s for s in plan_steps if s.step_id == awaiting_step_id), None
        )
        if awaiting_step is not None:
            attempts = attempts_without_progress.get(awaiting_step_id, 0)
            suffix = (
                f" (attempts_without_progress={attempts})" if attempts else ""
            )
            action_pointer = _format_action_pointer(
                awaiting_step, awaiting_action_index)
            lines.append("  AWAITING (user is on this step now):")
            lines.append(
                f"    - {awaiting_step.step_id}{suffix} "
                f"{action_pointer} conf={awaiting_step.confidence:.2f}: "
                f"{awaiting_step.instruction}"
            )

    lines.append("  TAIL (rewrite freely):")
    tail = plan_steps[frozen_split_index:]
    if not tail:
        lines.append("    <empty>")
    else:
        for step in tail:
            lines.append(
                f"    - {step.step_id} [{_format_action_summary(step)}] "
                f"conf={step.confidence:.2f}: {step.instruction}"
            )

    if awaiting_step_id is not None:
        attempts = attempts_without_progress.get(awaiting_step_id, 0)
        if attempts >= STALL_ATTEMPT_THRESHOLD:
            lines.append("")
            lines.append(
                f"  STALL: {awaiting_step_id} has been pending across "
                f"{attempts} fresh screens without user progress. The "
                "instruction may be wrong, the target may have moved, or "
                "the user is stuck. On your next tutorial_update_plan: "
                "rewrite the tail to take a different approach to this "
                "step, OR insert a confirm step to check state, OR lower "
                "confidence to surface uncertainty. Do not simply re-emit "
                "the same tail."
            )
    lines.append("")


def _format_action_summary(step: TutorialStep) -> str:
    kinds = [a.type for a in step.actions]
    if len(kinds) == 1:
        return kinds[0]
    return f"{len(kinds)} actions: {','.join(kinds)}"


def _format_action_pointer(step: TutorialStep, action_index: int | None) -> str:
    kinds = [a.type for a in step.actions]
    if len(kinds) == 1:
        return f"[{kinds[0]}]"
    if action_index is None or not (0 <= action_index < len(kinds)):
        return f"[{len(kinds)} actions: {','.join(kinds)}]"
    return (
        f"action {action_index + 1}/{len(kinds)} [{kinds[action_index]}] "
        f"(full list: {','.join(kinds)})"
    )


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
        step.step_id in completed
        and any(a.type in SCREEN_CHANGING_ACTION_TYPES for a in step.actions)
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
