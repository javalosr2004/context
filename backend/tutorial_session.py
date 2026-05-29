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
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from backend.llm_recording import LLMCallSink

from backend.embeddings_client import (
    EXPECTED_SCREEN_SIMILARITY_THRESHOLD,
    LOGICAL_ID_SIMILARITY_THRESHOLD,
    EmbeddingsClient,
    NullEmbeddingsClient,
    cosine,
    step_fingerprint,
)
from backend.images import UploadedImage, downscale_for_verifier
from backend.instruction_verifier import VerifierVerdict, classify_screen
from backend.llm import (
    LLMRequest,
    LLMStreamEvent,
    LLMTextDelta,
    LLMToolCallArgsDelta,
    LLMToolCallEvent,
    LLMWebSearchCompleted,
    LLMWebSearchStarted,
    MultimodalLLM,
)
from backend.plan_arg_stream import IncrementalPlanPreview
from backend.enrichment_client import EnrichmentSnippetsProducer
from backend.tutorial_guide import (
    TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT,
    tool_stream_system_prompt,
    generate_draft_plan,
    refine_search_query,
)
from backend.tutorial_schema import DraftPlan, TutorialAction, TutorialPlan, TutorialStep
from backend.web_ground import NullWebGroundProducer, WebGroundProducer, WebGroundSnippet
from backend.tutorial_session_events import (
    AgentTurnEvent,
    AssistantQuestion,
    AssistantQuestionEvent,
    AwaitingConfirmationEvent,
    CompletionProposedEvent,
    DraftPlanReadyEvent,
    InstructionVerificationStartedEvent,
    InstructionVerifiedEvent,
    PlanDiffEvent,
    PlanReadyEvent,
    PlanStepPreviewEvent,
    PlanStreamResetEvent,
    PlanUpdatedEvent,
    ScreenRequestedEvent,
    ScreenSnapshot,
    ServerSessionEvent,
    SessionCompletedEvent,
    StatusChangedEvent,
    StepProgressEvent,
    StepReadyEvent,
    TutorialTextDeltaEvent,
    TextResponseEventLike,
    VerificationHintEvent,
    WebSearchCompletedEvent,
    WebSearchSource,
    WebSearchStartedEvent,
)
from backend.plan_merge import (
    PlanMergeError,
    PlanMergeResult,
    merge_plan_tail,
)
from backend.tutorial_tools import (
    ASK_USER_TOOL_NAME,
    REQUEST_COMPLETION_TOOL_NAME,
    REQUEST_SCREEN_TOOL_NAME,
    UPDATE_PLAN_TOOL_NAME,
    TutorialToolCall,
    TutorialToolCallError,
    candidates_from_arguments,
    is_ask_user_call,
    is_request_completion_call,
    is_request_screen_call,
    is_update_plan_call,
    parse_ask_user_arguments,
    parse_request_completion_reason,
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
    {
        "click",
        "double_click",
        "right_click",
        "type",
        "press_key",
        "scroll",
        "drag",
        "user_choice",
    }
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
    fast_llm: MultimodalLLM | None = None
    verifier_llm: MultimodalLLM | None = None
    embeddings_client: EmbeddingsClient = field(default_factory=NullEmbeddingsClient)
    goal: str | None = None
    history: list[HistoryEntry] = field(default_factory=list)
    plan_steps: list[TutorialStep] = field(default_factory=list)
    completed_step_ids: list[str] = field(default_factory=list)
    latest_screen: UploadedImage | None = None
    uploaded_images: list[UploadedImage] = field(default_factory=list)
    pending_screen: asyncio.Future[UploadedImage] | None = None
    pending_screen_request_id: str | None = None
    # Completion proposal flow. ``pending_completion`` is set by the agent
    # loop when the LLM calls tutorial_request_completion; the outer
    # session loop reads it and emits CompletionProposedEvent.
    # ``pending_completion_response`` is the future the session loop awaits;
    # ``handle_user_completion_response`` resolves it with (confirmed, note).
    pending_completion: tuple[str, str] | None = None  # (reason, source)
    pending_completion_response: (
        asyncio.Future[tuple[bool, str | None]] | None
    ) = None
    # Clarifying-question flow. ``tutorial_ask_user`` may be called on any
    # planning turn whenever the goal is genuinely ambiguous. It must be
    # the sole tool call in its turn: it is recorded as assistant/user
    # dialogue, not a tool-call pair, so it cannot be interleaved with
    # other tool calls in the same turn.
    pending_question_batch_id: str | None = None
    pending_question_ids: tuple[str, ...] | None = None
    pending_question_response: asyncio.Future[dict[str, str]] | None = None
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
    # Cache of embeddings for each known logical_id, populated as steps
    # are merged. Keeps the per-replan embed cost to "only the new
    # candidates" — we never re-embed a logical step we have seen.
    logical_step_embeddings: dict[str, list[float]] = field(default_factory=dict)
    prev_active_step_id: str | None = None
    last_action_kind: str | None = None
    screen_is_stale: bool = False
    screen_captured_at: datetime | None = None
    # Step IDs whose post-action stable screen the client already shipped
    # alongside the confirmation. Used to suppress the post-step
    # `screen_is_stale = True` flip that would otherwise force a
    # redundant request_screen round-trip.
    confirmed_with_fresh_screen_step_ids: set[str] = field(default_factory=set)
    draft_plan: DraftPlan | None = None
    draft_plan_task: asyncio.Task[None] | None = None
    # Per-instruction screen verification: at most one in flight per session.
    # On a "no" verdict the verifier emits a VerificationHintEvent toast.
    # For diverged/blocked it ALSO stages pending_verification_replan (which
    # the _await_action loop consumes) so the toast can auto-dismiss into a
    # real replan. For unsure it leaves pending_verification_replan unset and
    # waits for the user to confirm "off track" via UserHintResponseEvent.
    verifying_step_id: str | None = None
    verification_task: asyncio.Task[None] | None = None
    pending_verification_replan: str | None = None
    # step_id of the verification hint currently showing on the overlay, or
    # None. A UserHintResponseEvent with a matching step_id resolves it; any
    # other step_id is treated as a stale toast and ignored.
    awaiting_hint_response: str | None = None
    web_ground: WebGroundProducer = field(default_factory=NullWebGroundProducer)
    # Last gate (verifier) elapsed_ms, consumed by the next turn summary.
    _last_gate_elapsed_ms: float | None = None
    # A/B test (STEP_TOOLS_ENABLED): "full_plan" (today's default,
    # planner emits the entire remaining plan each turn) vs
    # "capped_head" (planner emits the next 1–5 detailed steps and the
    # outer loop replans rather than proposing completion on head
    # exhaustion). See backend/tutorial_guide.tool_stream_system_prompt.
    # NB: the dataclass default is "full_plan" so direct construction
    # (mostly tests) gets the simpler legacy behavior. Production runs
    # default to "capped_head" via TutorialSessionStore / the
    # STEP_TOOLS_ENABLED env var (see backend/main.py).
    step_tools_mode: Literal["full_plan", "capped_head"] = "full_plan"
    # GROUNDING_STRATEGY: ``parallel`` runs the enrichment service + draft
    # plan pre-pipeline before the planner sees the goal; ``planner``
    # skips the pre-pipeline and lets the planner call web_search as a
    # native tool. See backend/main.py for the env var and
    # backend/tutorial_guide.tool_stream_system_prompt for the prompt
    # block surfaced under planner mode.
    grounding_strategy: Literal["parallel", "planner"] = "parallel"
    # PLAN_STREAM_PREVIEW: when True, parse the streaming update_plan tool
    # arguments and emit per-step previews (PlanStepPreviewEvent) so the
    # overlay can render the guide as it is generated instead of waiting
    # for the full plan. Cosmetic only — the authoritative plan still
    # arrives via plan_ready/plan_updated. Providers that don't stream tool
    # args (Gemini/Holo) simply never emit previews. See backend/main.py.
    plan_stream_preview: bool = True
    # Bound for the capped_head replan-on-exhaustion loop: how many
    # times in a row may the outer loop regrow the head without any
    # newly-walked step before falling through to a completion proposal.
    _capped_head_empty_grows: int = 0
    _planner_calls: int = 0
    _planner_elapsed_ms_total: float = 0.0
    status: str = "created"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Optional eval sink: when set, every LLM call this session makes is
    # captured via RecordingLLM and forwarded here. Wired through by the
    # WS handler so the SessionEventLog can persist prompts/responses.
    llm_call_sink: "LLMCallSink | None" = None

    def __post_init__(self) -> None:
        if self.llm_call_sink is None:
            return
        from backend.llm_recording import RecordingLLM
        sink = self.llm_call_sink
        self.llm = RecordingLLM(self.llm, agent="planner", sink=sink)
        if self.fast_llm is not None:
            self.fast_llm = RecordingLLM(
                self.fast_llm, agent="draft_planner", sink=sink
            )
        if self.verifier_llm is not None:
            self.verifier_llm = RecordingLLM(
                self.verifier_llm, agent="verifier", sink=sink
            )

    # -------- Public entry points (driven by the WS handler) --------

    async def handle_user_message(
        self,
        text: str,
        uploaded_images: list[ScreenSnapshot] | None = None,
    ) -> None:
        text = text.strip()
        if not text:
            return
        logger.info(
            "[session] user_message",
            extra={
                "session_id": self.session_id,
                "text_chars": len(text),
                "image_count": len(uploaded_images or []),
            },
        )
        await self._cancel_current_task()

        message_images = uploaded_images_from_snapshots(uploaded_images or [])
        if self.goal is None:
            await self._reset_for_new_goal(text, message_images)
        else:
            # Once a goal is active, every subsequent message is treated as
            # a follow-up. Switching goals mid-session is a UI-driven action
            # (explicit reset), not something we infer from message content.
            self.uploaded_images.extend(message_images)
            self.history.append(HistoryEntry(role="user", content=text))

        await self._start_task(self._run_session(refresh_screen=True))

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
        self.logical_step_embeddings = {}
        self.prev_active_step_id = None
        self.last_action_kind = None
        self.screen_is_stale = False
        self.pending_question_batch_id = None
        self.pending_question_ids = None
        self.pending_question_response = None
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
        logger.info(
            "[session] user_screen",
            extra={
                "session_id": self.session_id,
                "request_id": request_id,
                "expected_request_id": self.pending_screen_request_id,
                "bytes": len(image.data),
                "awaiting_step_id": self.awaiting_step_id,
            },
        )

        future = self.pending_screen
        if future is None:
            logger.debug(
                "[session] user_screen no pending future; stored as latest_screen",
                extra={
                    "session_id": self.session_id,
                    "request_id": request_id,
                },
            )
            return
        if self.pending_screen_request_id != request_id:
            logger.debug(
                "[session] user_screen request_id mismatch; resolving anyway",
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
        logger.info(
            "[session] step_started",
            extra={
                "session_id": self.session_id,
                "step_id": step_id,
                "action_index": action_index,
                "awaiting_step_id": self.awaiting_step_id,
                "awaiting_action_index": self.awaiting_action_index,
            },
        )
        self.pending_step_starts.add((step_id, action_index))
        self.step_event.set()
        # User acted — drop any in-flight instruction verification. Its
        # screen snapshot is now stale. An already-set replan note is
        # preserved (a "no" verdict still warrants replan).
        await self._cancel_verification()

    async def handle_user_completion_response(
        self,
        confirmed: bool,
        note: str | None,
    ) -> None:
        logger.info(
            "[session] user_completion_response",
            extra={
                "session_id": self.session_id,
                "confirmed": confirmed,
                "note_chars": len((note or "").strip()),
                "had_pending": self.pending_completion_response is not None,
            },
        )
        future = self.pending_completion_response
        if future is None:
            logger.debug(
                "[session] user_completion_response no pending future; dropping",
                extra={"session_id": self.session_id},
            )
            return
        cleaned_note = (note or "").strip() or None
        if not future.done():
            future.set_result((confirmed, cleaned_note))

    async def handle_user_answer(
        self,
        batch_id: str,
        answers: list[tuple[str, str]],
    ) -> None:
        """Resolve a pending AssistantQuestionEvent batch.

        ``answers`` is a list of (question_id, text) pairs. Every
        question_id from the in-flight batch must be present exactly
        once; missing or extra ids drop the response so the overlay can
        retry. Empty strings are also rejected.
        """
        future = self.pending_question_response
        expected_ids = self.pending_question_ids
        expected_batch = self.pending_question_batch_id
        logger.info(
            "[session] user_answer",
            extra={
                "session_id": self.session_id,
                "batch_id": batch_id,
                "answer_count": len(answers),
                "expected_batch_id": expected_batch,
                "expected_question_ids": list(expected_ids or ()),
                "had_pending": future is not None,
            },
        )
        if future is None or expected_ids is None or expected_batch is None:
            return
        if batch_id != expected_batch:
            logger.warning(
                "[session] user_answer batch_id mismatch; dropping",
                extra={
                    "session_id": self.session_id,
                    "batch_id": batch_id,
                    "expected_batch_id": expected_batch,
                },
            )
            return
        cleaned: dict[str, str] = {}
        for qid, text in answers:
            stripped = (text or "").strip()
            if not stripped:
                logger.warning(
                    "[session] user_answer blank text; dropping batch",
                    extra={"session_id": self.session_id, "question_id": qid},
                )
                return
            if qid in cleaned:
                logger.warning(
                    "[session] user_answer duplicate question_id; dropping batch",
                    extra={"session_id": self.session_id, "question_id": qid},
                )
                return
            cleaned[qid] = stripped
        if set(cleaned.keys()) != set(expected_ids):
            logger.warning(
                "[session] user_answer question_ids do not match batch; dropping",
                extra={
                    "session_id": self.session_id,
                    "got_ids": sorted(cleaned.keys()),
                    "expected_ids": sorted(expected_ids),
                },
            )
            return
        if not future.done():
            future.set_result(cleaned)

    async def handle_user_confirmation(
        self,
        step_id: str,
        action_index: int,
        confirmed: bool,
        note: str | None,
        screen: ScreenSnapshot | None = None,
    ) -> None:
        # Record every confirmation. Out-of-slot confirmations either
        # advance the walk loop via `_has_later_event` (when the slot is
        # past the current step) or sit harmlessly until garbage-collected
        # on session reset. Dropping them silently stalls the walk loop.
        logger.info(
            "[session] user_confirmation",
            extra={
                "session_id": self.session_id,
                "step_id": step_id,
                "action_index": action_index,
                "confirmed": confirmed,
                "has_screen": screen is not None,
                "note_chars": len((note or "").strip()),
                "awaiting_step_id": self.awaiting_step_id,
                "awaiting_action_index": self.awaiting_action_index,
            },
        )
        if not self._is_awaiting_slot(step_id, action_index):
            logger.debug(
                "[session] user_confirmation non-awaiting slot",
                extra={
                    "session_id": self.session_id,
                    "step_id": step_id,
                    "action_index": action_index,
                    "expected_step_id": self.awaiting_step_id,
                    "expected_action_index": self.awaiting_action_index,
                },
            )
        if screen is not None:
            # The client waited for the post-action screen to settle before
            # sending this confirmation. Adopt it as latest_screen so the
            # next planner pass runs on a stable frame without a separate
            # request_screen round-trip.
            image = uploaded_image_from_snapshot(screen)
            self.latest_screen = image
            self.screen_is_stale = False
            self.screen_captured_at = datetime.now(UTC)
            self.confirmed_with_fresh_screen_step_ids.add(step_id)
            future = self.pending_screen
            if future is not None and not future.done():
                future.set_result(image)
        self.pending_step_confirmations[(step_id, action_index)] = (
            confirmed,
            (note or "").strip(),
        )
        self.step_event.set()
        await self._cancel_verification()

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
        await self._cancel_verification()
        self._emit_mode_summary()

    # -------- Top-level session coroutine --------

    def _emit_mode_summary(self) -> None:
        """One-line A/B comparison log emitted at session end. Pair with
        backend.tutorial_session_store closure to ensure it fires on all
        exit paths (normal completion, abandonment, crash)."""
        logger.info(
            "[session] mode_summary",
            extra={
                "session_id": self.session_id,
                "mode": self.step_tools_mode,
                "total_planner_calls": self._planner_calls,
                "total_planner_elapsed_ms": round(
                    self._planner_elapsed_ms_total, 2
                ),
                "steps_walked": len(self.completed_step_ids),
                "plan_steps_final": len(self.plan_steps),
            },
        )

    async def _run_session(self, refresh_screen: bool = False) -> None:
        try:
            if refresh_screen:
                await self._request_screen(
                    "Capturing the current screen alongside the user's message."
                )
                if self.grounding_strategy == "parallel":
                    self._kick_off_draft_plan()
            any_steps_walked = False
            user_initiated = refresh_screen
            while True:
                await self._plan_or_gate(user_initiated=user_initiated)
                user_initiated = False
                # Completion is now user-gated. Two paths can request it:
                #   (a) LLM called tutorial_request_completion in the agent
                #       loop — handled via self.pending_completion.
                #   (b) Plan tail ran out after at least one walked step —
                #       backend synthesises a reason and asks the user.
                if self.pending_completion is not None:
                    reason, source = self.pending_completion
                    self.pending_completion = None
                    confirmed = await self._propose_completion(reason, source)
                    if confirmed:
                        return
                    await self._request_fresh_screen_after_user_action()
                    continue
                unwalked = self._unwalked_steps()
                if not unwalked:
                    if not any_steps_walked:
                        return
                    # capped_head mode: head exhaustion is the expected
                    # signal to regrow the tactical head, NOT to end the
                    # tutorial. The planner is responsible for calling
                    # tutorial_request_completion when the goal is
                    # actually reached. Loop back to the planner unless
                    # we've grown the head without progress too many
                    # times in a row (defensive against an infinite loop
                    # where the planner keeps emitting nothing useful).
                    if self.step_tools_mode == "capped_head":
                        self._capped_head_empty_grows += 1
                        if self._capped_head_empty_grows <= 2:
                            logger.info(
                                "[session] capped_head regrowing tactical head",
                                extra={
                                    "session_id": self.session_id,
                                    "grow_attempts": self._capped_head_empty_grows,
                                },
                            )
                            continue
                    confirmed = await self._propose_completion(
                        "The planner has no more steps to suggest.",
                        "backend",
                    )
                    if confirmed:
                        return
                    await self._request_fresh_screen_after_user_action()
                    continue
                walk_started_completed = set(self.completed_step_ids)
                replan_requested = await self._walk_steps()
                any_steps_walked = True
                newly_completed = [
                    sid
                    for sid in self.completed_step_ids
                    if sid not in walk_started_completed
                ]
                if newly_completed:
                    # Real progress — reset the capped-head regrowth guard.
                    self._capped_head_empty_grows = 0
                needs_fresh_screen = replan_requested or self._completed_changed_screen(
                    newly_completed
                )
                if needs_fresh_screen:
                    await self._request_fresh_screen_after_user_action()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[session] crashed",
                extra={"session_id": self.session_id},
            )
            raise

    def _unwalked_steps(self) -> list[TutorialStep]:
        completed = set(self.completed_step_ids)
        return [s for s in self.plan_steps if s.step_id not in completed]

    def _last_completed_instruction(self) -> str | None:
        """Instruction text of the most recently completed step, for the
        verifier to check whether its intended effect is visible on
        screen. Returns None when nothing has been completed yet."""
        if not self.completed_step_ids:
            return None
        last_id = self.completed_step_ids[-1]
        for step in self.plan_steps:
            if step.step_id == last_id:
                return step.instruction
        return None

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

    def _consume_last_gate_elapsed_ms(self) -> float | None:
        """Read & clear the most recent gate timing so it's attributed to
        exactly one turn summary (the turn that immediately follows the gate)."""
        elapsed = getattr(self, "_last_gate_elapsed_ms", None)
        self._last_gate_elapsed_ms = None
        return elapsed

    async def _run_agent_loop(self) -> None:
        self.status = "planning"
        await self.emit(StatusChangedEvent(status="planning", label="Thinking"))
        # Block the first planner turn until the web-enriched draft plan is
        # ready. Without this, the LLM emits an optimistic hypothesis from
        # the goal alone and the draft (when it lands) competes with an
        # already-installed plan tail instead of seeding it.
        if not self.plan_steps and self.draft_plan is None:
            await self._await_draft_plan()
        logger.info(
            "[session] agent_loop start",
            extra={
                "session_id": self.session_id,
                "awaiting_step_id": self.awaiting_step_id,
                "plan_step_count": len(self.plan_steps),
                "completed_count": len(self.completed_step_ids),
                "screen_captured_at": (
                    self.screen_captured_at.isoformat()
                    if self.screen_captured_at else None
                ),
                "screen_is_stale": self.screen_is_stale,
                "grounding_strategy": self.grounding_strategy,
                "step_tools_mode": self.step_tools_mode,
            },
        )

        consecutive_screen_requests = 0
        last_screen_reason = ""

        for turn in range(MAX_AGENT_TURNS):
            turn_started_at = time.perf_counter()
            gate_elapsed_ms = self._consume_last_gate_elapsed_ms()
            merge_elapsed_ms = 0.0
            await self.emit(AgentTurnEvent(turn=turn + 1, max_turns=MAX_AGENT_TURNS))
            llm_started_at = time.perf_counter()
            try:
                tool_calls, text = await self._stream_llm_once()
            finally:
                llm_stream_elapsed_ms = round(
                    (time.perf_counter() - llm_started_at) * 1000, 2
                )
                self._planner_calls += 1
                self._planner_elapsed_ms_total += llm_stream_elapsed_ms
            logger.info(
                "[session] agent_loop turn",
                extra={
                    "session_id": self.session_id,
                    "turn": turn + 1,
                    "tool_calls": len(tool_calls),
                    "tool_call_names": [call.name for call in tool_calls],
                    "tool_call_args": [call.arguments for call in tool_calls],
                    "text_chars": len(text),
                },
            )

            def _log_turn_summary() -> None:
                logger.info(
                    "[session] turn summary",
                    extra={
                        "session_id": self.session_id,
                        "turn": turn + 1,
                        "gate_elapsed_ms": gate_elapsed_ms,
                        "llm_stream_elapsed_ms": llm_stream_elapsed_ms,
                        "merge_elapsed_ms": round(merge_elapsed_ms, 2),
                        "total_turn_elapsed_ms": round(
                            (time.perf_counter() - turn_started_at) * 1000, 2
                        ),
                    },
                )

            if not tool_calls:
                if self.screen_is_stale:
                    logger.info(
                        "[session] forcing request_screen on stale text-only turn",
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
                        _log_turn_summary()
                        return
                    await self._execute_screen_request(
                        TutorialToolCall(
                            name=REQUEST_SCREEN_TOOL_NAME,
                            arguments=json.dumps({"reason": synthetic_reason}),
                        )
                    )
                    _log_turn_summary()
                    continue
                if text.strip():
                    self.history.append(HistoryEntry(
                        role="assistant", content=text))
                    await self.emit(TextResponseEventLike(text=text))
                self.status = "ready"
                await self.emit(StatusChangedEvent(status="ready", label="Ready"))
                _log_turn_summary()
                return

            request_screen_call = first_request_screen_call(tool_calls)
            update_plan_calls = [
                c for c in tool_calls if is_update_plan_call(c)]
            request_completion_call = next(
                (c for c in tool_calls if is_request_completion_call(c)),
                None,
            )
            ask_user_call = next(
                (c for c in tool_calls if is_ask_user_call(c)),
                None,
            )
            unknown_calls = [
                c
                for c in tool_calls
                if not is_update_plan_call(c)
                and not is_request_screen_call(c)
                and not is_request_completion_call(c)
                and not is_ask_user_call(c)
            ]
            for call in unknown_calls:
                self.history.append(
                    HistoryEntry(
                        role="tool",
                        content=(
                            f"{call.name} rejected: unknown tool. Available "
                            f"tools are {UPDATE_PLAN_TOOL_NAME}, "
                            f"{REQUEST_SCREEN_TOOL_NAME}, "
                            f"{REQUEST_COMPLETION_TOOL_NAME}, and "
                            f"{ASK_USER_TOOL_NAME}."
                        ),
                    )
                )

            # tutorial_ask_user must be the sole tool call in its turn: it
            # is recorded as assistant/user dialogue, not a tool-call pair,
            # so it cannot be interleaved with other tool calls. When it
            # shares a turn with another tool, we drop it and let the rest
            # of the turn proceed normally.
            if ask_user_call is not None:
                other_calls_present = (
                    bool(update_plan_calls)
                    or request_screen_call is not None
                    or request_completion_call is not None
                )
                if other_calls_present:
                    self.history.append(
                        HistoryEntry(
                            role="tool",
                            content=(
                                f"{ASK_USER_TOOL_NAME} rejected: must be the "
                                "sole tool call in its turn. Since you "
                                "also called another tool, that signals "
                                "you had enough context to plan. The "
                                "ask_user call was dropped; other tools "
                                "are being processed."
                            ),
                        )
                    )
                    ask_user_call = None

            if ask_user_call is not None:
                try:
                    await self._execute_ask_user_call(ask_user_call)
                except TutorialToolCallError as error:
                    logger.warning(
                        "[session] invalid ask_user call",
                        extra={
                            "session_id": self.session_id,
                            "code": error.code,
                            "message": error.message,
                        },
                    )
                    self.history.append(
                        HistoryEntry(
                            role="tool",
                            content=(
                                f"{ASK_USER_TOOL_NAME} rejected: "
                                f"{error.message}. Proceed without asking."
                            ),
                        )
                    )
                _log_turn_summary()
                # The question was answered (history now has the Q&A) or
                # the call was rejected with a tool note. Loop again so the
                # planner can ask more, plan, or act on the answers.
                continue

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
                merge_started_at = time.perf_counter()
                try:
                    await self._execute_plan_update_call(update_plan_calls[-1])
                finally:
                    merge_elapsed_ms = (time.perf_counter() - merge_started_at) * 1000.0

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
                    _log_turn_summary()
                    return
                await self._execute_screen_request(request_screen_call)
                _log_turn_summary()
                # Loop again with the new screen available.
                continue

            consecutive_screen_requests = 0

            if request_completion_call is not None:
                self._record_completion_request(request_completion_call)

            # No request_screen this turn — agent loop is done.
            _log_turn_summary()
            return

        logger.warning(
            "[session] agent_loop hit MAX_AGENT_TURNS",
            extra={"session_id": self.session_id},
        )
        # Every other loop exit emits a terminal status; this one must too,
        # or the overlay is left spinning on "Thinking" with no signal to
        # leave it (e.g. a planner that keeps asking instead of planning).
        message = (
            "I wasn't able to finish planning this. Tell me a bit more and "
            "I'll try again."
        )
        self.history.append(HistoryEntry(role="assistant", content=message))
        await self.emit(TextResponseEventLike(text=message))
        self.status = "ready"
        await self.emit(StatusChangedEvent(status="ready", label="Ready"))

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
            "[session] agent_loop stalled on repeated request_screen",
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

        consume_started_at = time.perf_counter()
        logger.info(
            "[session] stream consume start",
            extra={"session_id": self.session_id},
        )
        producer = asyncio.create_task(asyncio.to_thread(produce_events))
        tool_calls: list[TutorialToolCall] = []
        text_parts: list[str] = []
        queue_wait_ms_total = 0.0
        plan_preview = IncrementalPlanPreview()
        preview_call_id: str | None = None
        preview_count = 0

        try:
            while True:
                wait_started = time.perf_counter()
                event = await queue.get()
                queue_wait_ms_total += (time.perf_counter() - wait_started) * 1000.0
                if event is None:
                    break
                if isinstance(event, Exception):
                    raise event
                if isinstance(event, LLMTextDelta):
                    text_parts.append(event.text)
                    await self.emit(TutorialTextDeltaEvent(text=event.text))
                elif isinstance(event, LLMToolCallArgsDelta):
                    if self.plan_stream_preview:
                        # A new tool-call id mid-turn means an earlier
                        # update_plan is being superseded; drop its preview
                        # rows. Only the last call is authoritative anyway.
                        if (
                            preview_call_id is not None
                            and event.call_id != preview_call_id
                        ):
                            plan_preview.reset()
                            await self.emit(PlanStreamResetEvent())
                        preview_call_id = event.call_id
                        for preview in plan_preview.feed(event.delta):
                            preview_count += 1
                            await self.emit(
                                PlanStepPreviewEvent(
                                    index=preview.index,
                                    instruction=preview.instruction,
                                    confidence=preview.confidence,
                                )
                            )
                elif isinstance(event, LLMToolCallEvent):
                    tool_calls.append(event.tool_call)
                elif isinstance(event, LLMWebSearchStarted):
                    await self.emit(WebSearchStartedEvent(query=event.query))
                elif isinstance(event, LLMWebSearchCompleted):
                    await self.emit(
                        WebSearchCompletedEvent(
                            query=event.query,
                            source_count=0,
                            sources=[],
                            elapsed_ms=event.elapsed_ms,
                        )
                    )
        finally:
            await producer

        logger.info(
            "[session] stream consume end",
            extra={
                "session_id": self.session_id,
                "elapsed_ms": round((time.perf_counter() - consume_started_at) * 1000, 2),
                "queue_wait_ms_total": round(queue_wait_ms_total, 2),
                "text_delta_count": len(text_parts),
                "tool_call_count": len(tool_calls),
                "plan_preview_count": preview_count,
            },
        )

        text = "".join(text_parts)
        if text_parts:
            logger.info(
                "[session] llm text concatenated",
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
            system_prompt=tool_stream_system_prompt(
                capped_head=self.step_tools_mode == "capped_head",
                planner_search=self.grounding_strategy == "planner",
            ),
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
            enable_search_grounding=self.grounding_strategy == "planner",
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
        draft_llm = self.fast_llm or self.llm
        snippets = await self._ground_with_events(goal, image, draft_llm)
        try:
            plan = await asyncio.to_thread(
                generate_draft_plan,
                draft_llm,
                goal,
                image,
                images,
                None,
                snippets,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[draft_plan] generation failed",
                extra={"session_id": self.session_id},
            )
            return
        # The session may have moved on to a new goal while we were
        # generating. Only adopt the draft if the goal still matches.
        if self.goal != goal:
            return
        self.draft_plan = plan
        await self.emit(DraftPlanReadyEvent(plan=plan))

    async def _ground_with_events(
        self,
        goal: str,
        image: UploadedImage | None,
        refiner_llm: MultimodalLLM,
    ) -> list[WebGroundSnippet]:
        if isinstance(self.web_ground, NullWebGroundProducer):
            return []
        if (
            isinstance(self.web_ground, EnrichmentSnippetsProducer)
            and image is not None
        ):
            return await self._ground_multimodal_with_events(goal, image)
        return await self._ground_single_query_with_events(goal, image, refiner_llm)

    async def _ground_single_query_with_events(
        self,
        goal: str,
        image: UploadedImage | None,
        refiner_llm: MultimodalLLM,
    ) -> list[WebGroundSnippet]:
        query = await asyncio.to_thread(
            refine_search_query, refiner_llm, goal, image
        )
        if not query:
            query = goal
        await self.emit(WebSearchStartedEvent(query=query))
        started_at = time.perf_counter()
        try:
            snippets = await asyncio.to_thread(self.web_ground.ground, query)
        except Exception:
            logger.exception(
                "[web_ground] failed",
                extra={"session_id": self.session_id, "query_chars": len(query)},
            )
            snippets = []
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        await self.emit(
            WebSearchCompletedEvent(
                query=query,
                source_count=len(snippets),
                sources=[
                    WebSearchSource(title=s.title, url=s.url, content=s.content)
                    for s in snippets
                ],
                elapsed_ms=elapsed_ms,
            )
        )
        return snippets

    async def _ground_multimodal_with_events(
        self,
        goal: str,
        image: UploadedImage,
    ) -> list[WebGroundSnippet]:
        """Hand the raw goal + screenshot to the enrichment layer.

        The enrichment layer identifies the environment, decomposes the
        goal into varying facets, and fans out a multi-query search whose
        results aggregate into one snippet set. We emit the joined query
        list on the events so the UI shows what was actually searched.
        """
        assert isinstance(self.web_ground, EnrichmentSnippetsProducer)
        producer = self.web_ground
        await self.emit(WebSearchStartedEvent(query=goal))
        started_at = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                producer.ground_multimodal, goal, image
            )
        except Exception:
            logger.exception(
                "[web_ground] multimodal failed",
                extra={"session_id": self.session_id, "goal_chars": len(goal)},
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            await self.emit(
                WebSearchCompletedEvent(
                    query=goal, source_count=0, sources=[], elapsed_ms=elapsed_ms,
                )
            )
            return []
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        display_query = " | ".join(result.queries_used) or goal
        logger.info(
            "[web_ground] multimodal completed",
            extra={
                "session_id": self.session_id,
                "queries_used": result.queries_used,
                "application": result.application,
                "environment": result.environment,
                "goal_facets": result.goal_facets,
                "snippet_count": len(result.snippets),
                "elapsed_ms": elapsed_ms,
            },
        )
        await self.emit(
            WebSearchCompletedEvent(
                query=display_query,
                source_count=len(result.snippets),
                sources=[
                    WebSearchSource(title=s.title, url=s.url, content=s.content)
                    for s in result.snippets
                ],
                elapsed_ms=elapsed_ms,
            )
        )
        return result.snippets

    # -------- Strict gate: verify next step before re-engaging planner --------

    async def _plan_or_gate(self, *, user_initiated: bool = False) -> None:
        """Decide whether to run the planner this iteration.

        Strict-gate semantics: on iterations where an existing plan still
        has unwalked steps and we have a screen, run the verifier on the
        next unwalked step. "Yes" → skip the planner entirely and let the
        walk advance. "No" (or no plan yet / no screen) → run the planner.
        On "no" the plan tail is truncated to the completed prefix so the
        planner regenerates from scratch.
        """
        unwalked = self._unwalked_steps()
        if user_initiated or not self.plan_steps or not unwalked or self.latest_screen is None:
            logger.info(
                "[session] gate skipped; running planner",
                extra={
                    "session_id": self.session_id,
                    "reason": (
                        "user_message" if user_initiated
                        else "no_plan" if not self.plan_steps
                        else "no_unwalked" if not unwalked
                        else "no_screen"
                    ),
                },
            )
            await self._run_agent_loop()
            return
        next_step = unwalked[0]
        if next_step.actions and next_step.actions[0].type == "user_choice":
            logger.info(
                "[session] gate skipped; next action is user_choice",
                extra={
                    "session_id": self.session_id,
                    "step_id": next_step.step_id,
                },
            )
            return
        verdict = await self._verify_step_blocking(next_step)
        if verdict.ok:
            logger.info(
                "[session] gate accepted; skipping planner",
                extra={
                    "session_id": self.session_id,
                    "step_id": next_step.step_id,
                    "reason": verdict.reason,
                },
            )
            return
        # Not ok: the verifier is advisory, not authoritative. Surface the
        # doubt as a decision the user owns rather than silently replanning.
        # No response defaults to "continue" — we never yank the user out of
        # a flow they may still be working through.
        if not await self._ask_continue_or_replan(next_step, verdict):
            logger.info(
                "[session] user kept current step past gate",
                extra={
                    "session_id": self.session_id,
                    "step_id": next_step.step_id,
                    "verdict": verdict.verdict,
                },
            )
            return
        logger.info(
            "[session] gate rejected; truncating tail and replanning",
            extra={
                "session_id": self.session_id,
                "step_id": next_step.step_id,
                "verdict": verdict.verdict,
                "reason": verdict.reason,
            },
        )
        if verdict.verdict == "diverged":
            note = (
                f"Screen does not match step {next_step.step_id} "
                f"({next_step.instruction!r}): {verdict.reason}. The user "
                "appears to be elsewhere in (or past) this flow. Re-plan "
                "from the current screen — drop steps the user has already "
                "completed, and adapt to where they actually are."
            )
        else:
            note = (
                f"Screen blocks step {next_step.step_id}: "
                f"{verdict.reason}. Re-plan from the current screen."
            )
        self.history.append(HistoryEntry(role="user", content=note))
        completed = set(self.completed_step_ids)
        self.plan_steps = [s for s in self.plan_steps if s.step_id in completed]
        self.prev_active_step_id = None
        await self._run_agent_loop()

    async def _verify_step_blocking(self, step: TutorialStep) -> VerifierVerdict:
        """Synchronous gate verification: emit start/verdict events, log,
        return the verdict. Fail-open on errors via classify_screen."""
        screen = self.latest_screen
        if screen is None:
            return VerifierVerdict(verdict="unsure", reason="no_screen")
        verifier_llm = self.verifier_llm or self.fast_llm or self.llm
        prev_instruction = self._last_completed_instruction()
        verifier_screen = await asyncio.to_thread(downscale_for_verifier, screen)
        await self.emit(InstructionVerificationStartedEvent(step_id=step.step_id))
        started_at = time.perf_counter()
        logger.info(
            "[verifier] gate start",
            extra={
                "session_id": self.session_id,
                "step_id": step.step_id,
                "instruction": step.instruction[:120],
                "previous_instruction": (prev_instruction or "")[:120],
                "goal": (self.goal or "")[:120],
                "screen_bytes": len(verifier_screen.data),
                "screen_bytes_original": len(screen.data),
                "screen_captured_at": (
                    self.screen_captured_at.isoformat()
                    if self.screen_captured_at else None
                ),
                "llm": "fast" if self.fast_llm is not None else "main",
            },
        )
        try:
            verdict = await asyncio.to_thread(
                classify_screen,
                verifier_llm,
                step.instruction,
                verifier_screen,
                self.goal,
                prev_instruction,
            )
        except asyncio.CancelledError:
            logger.info(
                "[verifier] gate cancelled",
                extra={
                    "session_id": self.session_id,
                    "step_id": step.step_id,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        except Exception:
            logger.exception(
                "[verifier] gate crashed",
                extra={"session_id": self.session_id, "step_id": step.step_id},
            )
            # Fail-open: don't lock the user out on a verifier glitch.
            return VerifierVerdict(verdict="unsure", reason="gate_error")
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        self._last_gate_elapsed_ms = elapsed_ms
        verdict = self._maybe_promote_via_expected_summary(step, verdict)
        logger.info(
            "[verifier] gate verdict",
            extra={
                "session_id": self.session_id,
                "step_id": step.step_id,
                "verdict": verdict.verdict,
                "ok": verdict.ok,
                "reason": verdict.reason,
                "elapsed_ms": elapsed_ms,
            },
        )
        await self.emit(
            InstructionVerifiedEvent(
                step_id=step.step_id,
                ok=verdict.ok,
                reason=verdict.reason,
                verdict=verdict.verdict,
                screen_summary=verdict.screen_summary or None,
            )
        )
        return verdict

    def _maybe_promote_via_expected_summary(
        self, step: TutorialStep, verdict: VerifierVerdict
    ) -> VerifierVerdict:
        """If the step carries an ``expected_screen_summary`` and the
        verifier reported a matching ``screen_summary``, override a
        non-``on_track`` verdict to ``on_track``.

        The verifier sometimes flags ``diverged`` or ``unsure`` for
        screens that are in fact the right state, especially when the
        instruction phrasing and visible UI label differ. A planner-
        emitted expectation is the cheapest second opinion we have."""
        expected = (step.expected_screen_summary or "").strip()
        actual = verdict.screen_summary.strip()
        if not expected or not actual:
            return verdict
        if verdict.verdict == "on_track":
            return verdict
        try:
            embeddings = self.embeddings_client.embed_batch([expected, actual])
        except Exception:
            logger.exception(
                "[verifier] screen_summary embedding failed",
                extra={"session_id": self.session_id, "step_id": step.step_id},
            )
            return verdict
        if len(embeddings) != 2:
            return verdict
        similarity = cosine(embeddings[0], embeddings[1])
        if similarity < EXPECTED_SCREEN_SIMILARITY_THRESHOLD:
            logger.info(
                "[verifier] expected_screen mismatch — keeping verdict",
                extra={
                    "session_id": self.session_id,
                    "step_id": step.step_id,
                    "verdict": verdict.verdict,
                    "similarity": round(similarity, 4),
                    "expected": expected[:120],
                    "actual": actual[:120],
                },
            )
            return verdict
        logger.info(
            "[verifier] expected_screen match — promoting to on_track",
            extra={
                "session_id": self.session_id,
                "step_id": step.step_id,
                "prior_verdict": verdict.verdict,
                "similarity": round(similarity, 4),
                "expected": expected[:120],
                "actual": actual[:120],
            },
        )
        return VerifierVerdict(
            verdict="on_track",
            reason=(
                f"expected_screen_summary matches (sim={similarity:.2f}); "
                f"prior verdict was {verdict.verdict}"
            ),
            screen_summary=verdict.screen_summary,
        )

    # How long the gate waits for the user's continue/replan decision before
    # defaulting to "continue". A backstop only — the overlay normally resolves
    # the modal well within this window (user tap or its own auto-dismiss). Kept
    # generous so a slow-to-decide user is never replanned out from under.
    _GATE_DECISION_TIMEOUT_S = 12.0

    async def _ask_continue_or_replan(
        self, step: TutorialStep, verdict: VerifierVerdict
    ) -> bool:
        """Surface a not-ok verdict as a user decision and wait for the call.

        Emits a ``VerificationHintEvent`` and awaits the user's response via
        ``step_event``. The decision is recorded by ``handle_user_hint_response``
        as ``pending_verification_replan`` (set => replan, unset => continue);
        a user action on the step also wakes us and leaves the slot unset.

        Returns ``True`` if the plan should be truncated and re-planned,
        ``False`` to continue the walk. No response within the backstop window
        defaults to ``False`` — the verifier only advises; it never commands.
        """
        self.pending_verification_replan = None
        self.awaiting_hint_response = step.step_id
        # auto_replanning is False: nothing is staged until the user chooses,
        # so timeout/no-response continues rather than replans.
        await self.emit(
            VerificationHintEvent(
                step_id=step.step_id,
                verdict=verdict.verdict,  # type: ignore[arg-type]
                reason=verdict.reason or "",
                auto_replanning=False,
            )
        )
        self.step_event.clear()
        try:
            await asyncio.wait_for(
                self.step_event.wait(), timeout=self._GATE_DECISION_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.info(
                "[session] gate decision timed out; continuing",
                extra={
                    "session_id": self.session_id,
                    "step_id": step.step_id,
                    "verdict": verdict.verdict,
                },
            )
        self.step_event.clear()
        self.awaiting_hint_response = None
        return self._consume_verification_replan() is not None

    # -------- Legacy parallel verifier (kept for cancellation API) --------

    def _start_verification(self, step: TutorialStep) -> None:
        """Spawn a per-instruction verification job.

        Uses ``latest_screen`` as captured at instruction entry — the
        main agent loop has already refreshed it. Running a parallel
        ``_request_screen`` would clobber the shared ``pending_screen``
        slot, so we deliberately reuse the latest frame.
        """
        if self.latest_screen is None:
            return
        # Supersede any in-flight verification (e.g. previous instruction
        # entered and finished before its verdict landed). Also drop any
        # open hint slot from the previous instruction — a late toast tap
        # on the old step shouldn't mutate the new instruction's replan
        # state. handle_user_hint_response's step_id check then drops the
        # late tap as stale.
        if self.verification_task is not None and not self.verification_task.done():
            self.verification_task.cancel()
        self.awaiting_hint_response = None
        self.verifying_step_id = step.step_id
        screen = self.latest_screen
        instruction = step.instruction
        self.verification_task = asyncio.create_task(
            self._run_verification(step.step_id, instruction, screen)
        )

    # Max times we'll re-classify a `pending` (mid-transition) screen
    # before giving up and treating it as `unsure`. Total wall-clock cost
    # is roughly _PENDING_RETRY_DELAY_S * (_PENDING_MAX_RETRIES - 1) plus
    # the LLM calls themselves; keep both small so a genuinely-stuck
    # screen doesn't park the verifier indefinitely.
    _PENDING_MAX_RETRIES = 3
    _PENDING_RETRY_DELAY_S = 1.5

    async def _run_verification(
        self,
        step_id: str,
        instruction: str,
        screen: UploadedImage,
    ) -> None:
        verifier_llm = self.verifier_llm or self.fast_llm or self.llm
        await self.emit(InstructionVerificationStartedEvent(step_id=step_id))
        started_at = time.perf_counter()
        logger.info(
            "[verifier] start",
            extra={
                "session_id": self.session_id,
                "step_id": step_id,
                "instruction": instruction[:120],
                "screen_bytes": len(screen.data),
                "screen_captured_at": (
                    self.screen_captured_at.isoformat()
                    if self.screen_captured_at else None
                ),
                "llm": "fast" if self.fast_llm is not None else "main",
            },
        )
        current_screen = screen
        try:
            verdict: VerifierVerdict | None = None
            for attempt in range(1, self._PENDING_MAX_RETRIES + 1):
                verdict = await asyncio.to_thread(
                    classify_screen,
                    verifier_llm,
                    instruction,
                    current_screen,
                    self.goal,
                    self._last_completed_instruction(),
                )
                if verdict.verdict != "pending":
                    break
                logger.info(
                    "[verifier] pending_retry",
                    extra={
                        "session_id": self.session_id,
                        "step_id": step_id,
                        "attempt": attempt,
                        "max": self._PENDING_MAX_RETRIES,
                        "reason": verdict.reason,
                    },
                )
                if attempt >= self._PENDING_MAX_RETRIES:
                    # Exhausted retries on a screen that won't settle.
                    # Degrade silently to `unsure` so the user is not
                    # interrupted by a hint they cannot act on.
                    verdict = VerifierVerdict(
                        verdict="unsure",
                        reason="pending_retries_exhausted",
                        screen_summary=verdict.screen_summary,
                        previous_step_visible_effect=verdict.previous_step_visible_effect,
                    )
                    break
                await asyncio.sleep(self._PENDING_RETRY_DELAY_S)
                if self.awaiting_step_id != step_id:
                    # User moved on while we were waiting; drop silently.
                    return
                if self.latest_screen is not None:
                    current_screen = self.latest_screen
            assert verdict is not None
        except asyncio.CancelledError:
            logger.info(
                "[verifier] cancelled",
                extra={
                    "session_id": self.session_id,
                    "step_id": step_id,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        except Exception:
            logger.exception(
                "[verifier] crashed",
                extra={"session_id": self.session_id, "step_id": step_id},
            )
            return
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        superseded = self.awaiting_step_id != step_id
        logger.info(
            "[verifier] verdict",
            extra={
                "session_id": self.session_id,
                "step_id": step_id,
                "verdict": verdict.verdict,
                "ok": verdict.ok,
                "reason": verdict.reason,
                "elapsed_ms": elapsed_ms,
                "superseded": superseded,
            },
        )
        # If the user moved on (or the instruction was replaced) while we
        # were waiting on the LLM, the verdict is stale — drop silently.
        if superseded:
            return
        await self.emit(
            InstructionVerifiedEvent(
                step_id=step_id, ok=verdict.ok, reason=verdict.reason
            )
        )
        if verdict.ok:
            return
        # "no" verdict. For diverged/blocked the verifier is high-confidence
        # wrong, so we stage the replan and only surface the hint so the user
        # can interject ("dismiss" to override). For unsure we hold the
        # replan back and require the user to acknowledge before mutating
        # the plan — verifier hunches alone aren't enough to interrupt.
        auto_replanning = verdict.verdict in ("diverged", "blocked")
        if auto_replanning and self.pending_verification_replan is None:
            # Do not overwrite an existing note (a user rejection is more
            # specific than a verifier hunch).
            self.pending_verification_replan = (
                f"Screen verification failed for {step_id}: {verdict.reason}. "
                "Re-plan from the current screen."
            )
        self.awaiting_hint_response = step_id
        await self.emit(
            VerificationHintEvent(
                step_id=step_id,
                verdict=verdict.verdict,  # type: ignore[arg-type]
                reason=verdict.reason or "",
                auto_replanning=auto_replanning,
            )
        )
        self.step_event.set()

    async def _cancel_verification(self) -> None:
        task = self.verification_task
        self.verifying_step_id = None
        if task is None or task.done():
            self.verification_task = None
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self.verification_task = None

    async def _await_draft_plan(self) -> None:
        task = self.draft_plan_task
        if task is None or task.done():
            return
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[session] await draft_plan failed",
                extra={"session_id": self.session_id},
            )

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
                "[session] rejected update_plan args",
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
                abandon_awaiting=arguments.abandon_awaiting,
            )
        except (PlanMergeError, ValueError) as error:
            logger.warning(
                "[session] rejected plan merge",
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
        self._assign_logical_ids()

        plan = plan_from_steps(self._display_goal(), self.plan_steps)
        refined_current = bool(
            candidates
            and candidates[0].refines_current
            and awaiting_in_prefix is not None
            and frozen_prefix_ids
            and frozen_prefix_ids[-1] == awaiting_in_prefix
        )
        frozen_prefix_len = (
            len(frozen_prefix_ids) - 1 if refined_current else len(frozen_prefix_ids)
        )
        await self.emit(
            PlanDiffEvent(
                frozen_prefix_len=frozen_prefix_len,
                new_tail_len=len(candidates),
                refined_current=refined_current,
                total_steps=len(self.plan_steps),
            )
        )
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

    def _assign_logical_ids(self) -> None:
        """Set ``logical_id`` on any plan step that lacks one.

        Refined steps keep the prior logical_id by virtue of carrying the
        same ``step_id`` (the merger reused it). New steps with a fresh
        ``step_id`` are embedded and matched against the cache of all
        prior logical steps; a hit reuses that logical_id (the planner
        rephrased the same logical step we already tried), a miss mints
        a new logical_id equal to the step_id.

        Fail-open: if the embeddings client returns nothing, we fall
        back to logical_id == step_id, which preserves today's behavior.
        """
        # Preserve logical_id on steps that already have one (refined
        # awaiting steps re-enter with the same step_id and therefore
        # the same logical_id we set last turn).
        new_steps: list[TutorialStep] = [
            step for step in self.plan_steps if step.logical_id is None
        ]
        if not new_steps:
            return
        fingerprints = [step_fingerprint(step) for step in new_steps]
        try:
            embeddings = self.embeddings_client.embed_batch(fingerprints)
        except Exception:
            logger.exception(
                "[session] embeddings call crashed; falling back to step_id",
                extra={"session_id": self.session_id},
            )
            embeddings = []

        for index, step in enumerate(new_steps):
            embedding = embeddings[index] if index < len(embeddings) else None
            logical_id = self._resolve_logical_id(step, embedding)
            step.logical_id = logical_id
            if embedding is not None and logical_id not in self.logical_step_embeddings:
                self.logical_step_embeddings[logical_id] = embedding

    def _resolve_logical_id(
        self, step: TutorialStep, embedding: list[float] | None
    ) -> str:
        if embedding is None or not self.logical_step_embeddings:
            return step.step_id
        best_id = step.step_id
        best_sim = LOGICAL_ID_SIMILARITY_THRESHOLD
        for existing_id, existing_embedding in self.logical_step_embeddings.items():
            sim = cosine(embedding, existing_embedding)
            if sim > best_sim:
                best_sim = sim
                best_id = existing_id
        if best_id != step.step_id:
            attempts = self.attempts_without_progress.get(best_id, 0)
            logger.info(
                "[session] logical_id reuse",
                extra={
                    "session_id": self.session_id,
                    "step_id": step.step_id,
                    "logical_id": best_id,
                    "similarity": round(best_sim, 4),
                    "attempts_without_progress": attempts,
                },
            )
        return best_id

    def _logical_id_for(self, step_id: str | None) -> str | None:
        if step_id is None:
            return None
        for step in self.plan_steps:
            if step.step_id == step_id:
                return step.logical_id or step.step_id
        return step_id

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
        active_logical = self._logical_id_for(active) or active
        prev_logical = self._logical_id_for(self.prev_active_step_id)
        if active_logical == prev_logical:
            self.attempts_without_progress[active_logical] = (
                self.attempts_without_progress.get(active_logical, 0) + 1
            )
        else:
            self.attempts_without_progress.pop(active_logical, None)
        self.prev_active_step_id = active

    def _record_completion_request(self, call: TutorialToolCall) -> None:
        """Stash an LLM completion request for the outer loop to act on.

        We don't emit anything from inside the agent loop — the proposal is
        emitted by ``_propose_completion`` after the loop returns, so any
        plan_update from the same turn is applied first.
        """
        try:
            reason = parse_request_completion_reason(call)
        except TutorialToolCallError as error:
            logger.warning(
                "[session] invalid request_completion call",
                extra={"session_id": self.session_id, "error": error.message},
            )
            self.history.append(
                HistoryEntry(
                    role="tool",
                    content=f"{call.name} rejected: {error.message}",
                )
            )
            return
        self.pending_completion = (reason, "llm")
        self.history.append(
            HistoryEntry(
                role="assistant",
                content=f"called {call.name}(reason={reason!r})",
            )
        )

    async def _propose_completion(self, reason: str, source: str) -> bool:
        """Ask the user whether the session is finished.

        Returns True if the user confirmed (caller should terminate), False
        if they rejected (caller should replan). On cancellation, raises.
        """
        cleaned_reason = reason.strip() or "Tutorial may be complete."
        loop = asyncio.get_running_loop()
        self.pending_completion_response = loop.create_future()
        self.status = "awaiting_completion"
        await self.emit(
            StatusChangedEvent(
                status="awaiting_completion",
                label="Confirm completion",
            )
        )
        await self.emit(
            CompletionProposedEvent(reason=cleaned_reason, source=source)
        )
        logger.info(
            "[session] completion_proposed",
            extra={
                "session_id": self.session_id,
                "source": source,
                "reason": cleaned_reason[:160],
            },
        )
        try:
            confirmed, note = await self.pending_completion_response
        finally:
            self.pending_completion_response = None

        logger.info(
            "[session] completion_response",
            extra={
                "session_id": self.session_id,
                "confirmed": confirmed,
                "note_chars": len(note or ""),
            },
        )
        if confirmed:
            self.history.append(
                HistoryEntry(
                    role="user",
                    content=(
                        f"User confirmed completion (proposal source={source}, "
                        f"reason={cleaned_reason!r})."
                    ),
                )
            )
            await self.emit(SessionCompletedEvent())
            self.status = "completed"
            return True

        # Rejection — record the user's note so the planner can re-engage
        # with a concrete reason to continue.
        note_text = note or ""
        if note_text:
            history_note = (
                f"User rejected the completion proposal (source={source}). "
                f"They said: {note_text}. Plan the next move from the "
                "current screen — do NOT propose completion again unless "
                "the screen gives a new reason."
            )
        else:
            history_note = (
                f"User rejected the completion proposal (source={source}) "
                "with no note. They are not done yet. Plan the next move "
                "from the current screen — do NOT propose completion again "
                "unless the screen gives a new reason."
            )
        self.history.append(HistoryEntry(role="user", content=history_note))
        return False

    async def _execute_ask_user_call(self, call: TutorialToolCall) -> None:
        """Emit a clarifying-question batch and block until the user replies.

        On resolution, the question prompts and the user's answers are
        appended to ``self.history`` as a single assistant/user pair so
        the next planner turn sees them as natural dialogue context.
        """
        arguments = parse_ask_user_arguments(call)  # may raise; caller handles
        batch_id = uuid.uuid4().hex
        question_ids = tuple(q.question_id for q in arguments.questions)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, str]] = loop.create_future()
        self.pending_question_batch_id = batch_id
        self.pending_question_ids = question_ids
        self.pending_question_response = future

        await self.emit(
            AssistantQuestionEvent(
                batch_id=batch_id,
                reason=arguments.reason,
                questions=[
                    AssistantQuestion(
                        question_id=q.question_id,
                        prompt=q.question,
                        response_mode=q.response_mode,
                        options=list(q.options),
                        allows_custom_answer=True,
                    )
                    for q in arguments.questions
                ],
            )
        )
        self.status = "needs_answer"
        await self.emit(StatusChangedEvent(status="needs_answer", label="Waiting for you"))
        logger.info(
            "[session] ask_user awaiting",
            extra={
                "session_id": self.session_id,
                "batch_id": batch_id,
                "question_ids": list(question_ids),
                "reason": arguments.reason,
            },
        )

        try:
            answers = await future
        finally:
            self.pending_question_batch_id = None
            self.pending_question_ids = None
            self.pending_question_response = None

        prompt_lines = [f"I need to clarify {len(arguments.questions)} thing(s) before planning:"]
        for index, q in enumerate(arguments.questions, start=1):
            prompt_lines.append(f"  {index}. {q.question}")
        answer_lines = []
        for index, q in enumerate(arguments.questions, start=1):
            answer_lines.append(f"  {index}. {answers[q.question_id]}")
        self.history.append(
            HistoryEntry(role="assistant", content="\n".join(prompt_lines))
        )
        self.history.append(
            HistoryEntry(role="user", content="\n".join(answer_lines))
        )
        logger.info(
            "[session] ask_user resolved",
            extra={
                "session_id": self.session_id,
                "batch_id": batch_id,
                "answer_chars_total": sum(len(v) for v in answers.values()),
            },
        )
    async def _execute_screen_request(self, call: TutorialToolCall) -> None:
        try:
            reason = parse_request_screen_reason(call)
        except TutorialToolCallError as error:
            logger.warning(
                "[session] invalid request_screen call",
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
        request_started = time.perf_counter()
        logger.info(
            "[session] screen_request start",
            extra={
                "session_id": self.session_id,
                "request_id": request_id,
                "reason": reason[:160],
            },
        )

        try:
            await self.pending_screen
        finally:
            self.pending_screen = None
            self.pending_screen_request_id = None
            logger.info(
                "[session] screen_request end",
                extra={
                    "session_id": self.session_id,
                    "request_id": request_id,
                    "elapsed_ms": round(
                        (time.perf_counter() - request_started) * 1000, 2
                    ),
                },
            )

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
            # Step completed normally. If it had any user-confirmation
            # action, break the walk so the agent re-validates against a
            # fresh screen before the next step. The tail is preserved —
            # we are not replanning, just gating.
            completed_step = next(
                (s for s in self.plan_steps if s.step_id == step.step_id),
                None,
            )
            if completed_step is not None and any(
                a.requires_confirmation for a in completed_step.actions
            ):
                return True

        return False

    async def _await_step(self, step: TutorialStep) -> str | None:
        self.awaiting_step_id = step.step_id
        step_index = self._plan_index(step.step_id)
        # Verification now runs as a blocking gate in `_plan_or_gate`
        # before each agent_loop call, not in parallel during the walk.
        try:
            # Re-resolve the live step each iteration; a mid-await
            # refines_current merge may have replaced the actions list while
            # keeping the same step_id.
            action_index = 0
            while True:
                current = next(
                    (s for s in self.plan_steps if s.step_id == step.step_id),
                    None,
                )
                if current is None:
                    # The agent abandoned this step (abandon_awaiting=true)
                    # or otherwise removed it mid-walk. Drop the walk so the
                    # outer loop re-enters _run_agent_loop.
                    return (
                        f"step {step.step_id} was abandoned by a plan update; "
                        "re-planning from the current screen."
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
        had_user_confirmation = any(a.requires_confirmation for a in current.actions)
        client_shipped_fresh_screen = (
            current.step_id in self.confirmed_with_fresh_screen_step_ids
        )
        self.confirmed_with_fresh_screen_step_ids.discard(current.step_id)
        if not client_shipped_fresh_screen and (
            had_user_confirmation
            or any(a.type in SCREEN_CHANGING_ACTION_TYPES for a in current.actions)
        ):
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
        current_step = next(
            (s for s in self.plan_steps if s.step_id == step_id), None
        )
        total_actions = len(current_step.actions) if current_step is not None else 0
        await self.emit(
            StepProgressEvent(
                step_id=step_id,
                step_index=step_index,
                total_steps=len(self.plan_steps),
                action_index=action_index,
                total_actions=total_actions,
            )
        )

        while slot not in self.pending_step_starts:
            replan = self._consume_verification_replan()
            if replan is not None:
                return _ActionOutcome(replan_note=replan)
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
            replan = self._consume_verification_replan()
            if replan is not None:
                return _ActionOutcome(replan_note=replan)
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

    def _consume_verification_replan(self) -> str | None:
        note = self.pending_verification_replan
        if note is None:
            return None
        self.pending_verification_replan = None
        return note

    def handle_user_hint_response(
        self,
        step_id: str,
        action: Literal["acknowledge_off", "dismiss", "timeout"],
    ) -> None:
        """Resolve an open VerificationHintEvent.

        Stale responses (the toast was for a different step, or no toast is
        open) are dropped silently — the overlay may race a timeout against
        a user tap, and we don't want either to clobber the other.
        """
        if self.awaiting_hint_response != step_id:
            return
        self.awaiting_hint_response = None
        if action == "acknowledge_off":
            # User confirmed something is off — stage a replan if the
            # verifier hadn't already (i.e. an `unsure` verdict).
            if self.pending_verification_replan is None:
                self.pending_verification_replan = (
                    f"User acknowledged off-track hint for step {step_id}. "
                    "Re-plan from the current screen."
                )
            self.step_event.set()
            return
        if action == "dismiss":
            # User explicitly overrode the verifier; drop any staged replan
            # so diverged/blocked verdicts honor the user's "it's fine."
            self.pending_verification_replan = None
            self.step_event.set()
            return
        # timeout: no state change. Whatever the verifier staged stands —
        # unsure leaves pending_verification_replan unset (continue);
        # diverged/blocked has it set (auto-replan fires on next loop tick).
        self.step_event.set()

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
            future = self.pending_completion_response
            if future is not None and not future.done():
                future.cancel()
            self.pending_completion_response = None
            self.pending_completion = None
            self.pending_step_starts.clear()
            self.pending_step_confirmations.clear()
            self.step_event.clear()
            self.awaiting_step_id = None
            self.awaiting_action_index = None
            self.pending_verification_replan = None
            self.awaiting_hint_response = None
        await self._cancel_verification()

    def _next_screen_request_id(self) -> str:
        self.screen_request_counter += 1
        return f"screen_{self.screen_request_counter:03}"

    # -------- Read-only views --------

    def current_plan(self) -> TutorialPlan | None:
        if not self.plan_steps:
            return None
        return plan_from_steps(self._display_goal(), self.plan_steps)

    def _display_goal(self) -> str:
        """Goal text shown in the UI — prefer the planner-refined title."""
        if self.draft_plan is not None:
            refined = self.draft_plan.goal.strip()
            if refined:
                return refined
        return self.goal or ""


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
            "Web-enriched draft plan (produced by a search-grounded planner "
            "using live web sources for this goal). This is the AUTHORITATIVE "
            "starting plan for your first tutorial_update_plan call. Derive "
            "your plan from these steps — keep the shape, ordering, and "
            "wording wherever possible. You may only deviate from a step "
            "when the latest screen actively contradicts it (UI not present, "
            "different layout, user already past it); cite the contradiction "
            "in plan_reasoning when you do. Do NOT invent a parallel plan "
            "from the screen alone — the draft has web evidence the screen "
            "does not. If a step has no visible UI yet, still include it; "
            "the verifier will gate it when its turn arrives."
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
            attempts_key = awaiting_step.logical_id or awaiting_step_id
            attempts = attempts_without_progress.get(attempts_key, 0)
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
        awaiting_step = next(
            (s for s in plan_steps if s.step_id == awaiting_step_id), None
        )
        attempts_key = (
            awaiting_step.logical_id or awaiting_step_id
            if awaiting_step is not None
            else awaiting_step_id
        )
        attempts = attempts_without_progress.get(attempts_key, 0)
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
