from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterator
from typing import Any

from backend.instruction_verifier import VerifierVerdict
from backend.llm import LLMRequest, LLMStreamEvent
from backend.tutorial_schema import ActionTarget, TutorialAction, TutorialStep
from backend.tutorial_session import TutorialSession
from backend.tutorial_session_events import (
    UserHintResponseEvent,
    VerificationHintEvent,
    client_session_event_adapter,
)
from backend.tutorial_tools import TutorialToolCall


class _InertLLM:
    """LLM stub that satisfies the MultimodalLLM protocol without ever
    being called. handle_user_hint_response is pure state mutation, so the
    session never reaches the LLM during these tests."""

    def complete_text(self, request: LLMRequest) -> str:  # pragma: no cover
        raise AssertionError("LLM should not be invoked in hint state tests")

    def stream_text(self, request: LLMRequest) -> Iterator[str]:  # pragma: no cover
        raise AssertionError("LLM should not be invoked in hint state tests")

    def stream_tutorial_tool_calls(  # pragma: no cover
        self, request: LLMRequest
    ) -> Iterator[TutorialToolCall]:
        raise AssertionError("LLM should not be invoked in hint state tests")

    def stream_tutorial_events(  # pragma: no cover
        self, request: LLMRequest
    ) -> Iterator[LLMStreamEvent]:
        raise AssertionError("LLM should not be invoked in hint state tests")


async def _noop_emit(event: Any) -> None:  # pragma: no cover
    pass


def _fresh_session() -> TutorialSession:
    return TutorialSession(
        session_id="s_hint",
        llm=_InertLLM(),  # type: ignore[arg-type]
        emit=_noop_emit,
    )


class HintResponseDecisionTableTests(unittest.TestCase):
    """Pure-logic coverage of handle_user_hint_response's decision table.

    The behavior under test (see backend/tutorial_session.py):
      - acknowledge_off: always stage a replan (idempotent on already-staged).
      - dismiss: clear any staged replan (user override).
      - timeout: no state change (verdict-dependent replan stands as staged
        by _run_verification — unsure=unset, diverged/blocked=set).
      - stale step_id: silently dropped.
    """

    def test_acknowledge_off_stages_replan_when_unsure(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        # unsure verdict path: _run_verification does NOT pre-stage replan.
        session.pending_verification_replan = None

        session.handle_user_hint_response("step_42", "acknowledge_off")

        self.assertIsNone(session.awaiting_hint_response)
        note = session.pending_verification_replan
        self.assertIsNotNone(note)
        assert note is not None  # pyright narrowing
        self.assertIn("step_42", note)

    def test_acknowledge_off_preserves_existing_replan_note(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        # diverged/blocked verdict path: _run_verification pre-stages.
        # The user clicking "off" should not clobber the verifier's note,
        # which is more specific than the generic acknowledgement note.
        session.pending_verification_replan = "verifier said diverged"

        session.handle_user_hint_response("step_42", "acknowledge_off")

        self.assertIsNone(session.awaiting_hint_response)
        self.assertEqual(
            session.pending_verification_replan, "verifier said diverged"
        )

    def test_dismiss_clears_staged_replan(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        # diverged/blocked verdict path: replan is staged. User explicitly
        # overrides by dismissing — the user knows better than the verifier.
        session.pending_verification_replan = "verifier said diverged"

        session.handle_user_hint_response("step_42", "dismiss")

        self.assertIsNone(session.awaiting_hint_response)
        self.assertIsNone(session.pending_verification_replan)

    def test_dismiss_when_no_replan_staged_is_noop(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        session.pending_verification_replan = None  # unsure path

        session.handle_user_hint_response("step_42", "dismiss")

        self.assertIsNone(session.awaiting_hint_response)
        self.assertIsNone(session.pending_verification_replan)

    def test_timeout_leaves_unsure_replan_unstaged(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        session.pending_verification_replan = None  # unsure path

        session.handle_user_hint_response("step_42", "timeout")

        self.assertIsNone(session.awaiting_hint_response)
        self.assertIsNone(session.pending_verification_replan)

    def test_timeout_preserves_diverged_replan_note(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        session.pending_verification_replan = "verifier said diverged"

        session.handle_user_hint_response("step_42", "timeout")

        self.assertIsNone(session.awaiting_hint_response)
        self.assertEqual(
            session.pending_verification_replan, "verifier said diverged"
        )

    def test_stale_step_id_is_dropped_silently(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = "step_42"
        session.pending_verification_replan = "verifier said diverged"

        # Late tap from a previous step's toast — should not mutate state.
        session.handle_user_hint_response("step_old", "dismiss")

        self.assertEqual(session.awaiting_hint_response, "step_42")
        self.assertEqual(
            session.pending_verification_replan, "verifier said diverged"
        )

    def test_no_open_hint_is_dropped_silently(self) -> None:
        session = _fresh_session()
        session.awaiting_hint_response = None
        session.pending_verification_replan = "something else staged"

        session.handle_user_hint_response("step_42", "acknowledge_off")

        # No open hint means no resolution to apply; state is untouched.
        self.assertIsNone(session.awaiting_hint_response)
        self.assertEqual(
            session.pending_verification_replan, "something else staged"
        )


def _step(step_id: str) -> TutorialStep:
    return TutorialStep(
        step_id=step_id,
        instruction="open the settings panel",
        actions=[
            TutorialAction(
                type="click",
                target=ActionTarget(kind="element", description="settings"),
                requires_confirmation=True,
            )
        ],
        confidence=0.9,
    )


async def _wait_for_open_hint(session: TutorialSession, step_id: str) -> None:
    # Spin until the gate has emitted the hint and is parked on step_event.
    for _ in range(1000):
        if session.awaiting_hint_response == step_id:
            return
        await asyncio.sleep(0)
    raise AssertionError("hint never opened")


class GateDecisionTests(unittest.IsolatedAsyncioTestCase):
    """The gate surfaces a not-ok verdict as a user decision and returns
    True only when a replan is wanted. The verifier is advisory: no response
    defaults to continue (False)."""

    async def test_dismiss_continues(self) -> None:
        session = _fresh_session()
        verdict = VerifierVerdict(verdict="diverged", reason="elsewhere")

        async def respond() -> None:
            await _wait_for_open_hint(session, "step_1")
            session.handle_user_hint_response("step_1", "dismiss")

        replan, _ = await asyncio.gather(
            session._ask_continue_or_replan(_step("step_1"), verdict),
            respond(),
        )
        self.assertFalse(replan)
        self.assertIsNone(session.awaiting_hint_response)
        self.assertIsNone(session.pending_verification_replan)

    async def test_acknowledge_off_replans(self) -> None:
        session = _fresh_session()
        verdict = VerifierVerdict(verdict="diverged", reason="elsewhere")

        async def respond() -> None:
            await _wait_for_open_hint(session, "step_1")
            session.handle_user_hint_response("step_1", "acknowledge_off")

        replan, _ = await asyncio.gather(
            session._ask_continue_or_replan(_step("step_1"), verdict),
            respond(),
        )
        self.assertTrue(replan)
        self.assertIsNone(session.awaiting_hint_response)

    async def test_no_response_defaults_to_continue(self) -> None:
        session = _fresh_session()
        session._GATE_DECISION_TIMEOUT_S = 0.05
        verdict = VerifierVerdict(verdict="blocked", reason="modal in the way")

        replan = await session._ask_continue_or_replan(_step("step_1"), verdict)

        self.assertFalse(replan)
        self.assertIsNone(session.awaiting_hint_response)


class HintEventWireFormatTests(unittest.TestCase):
    def test_verification_hint_serializes_with_discriminator(self) -> None:
        event = VerificationHintEvent(
            step_id="step_42",
            verdict="unsure",
            reason="screen looks similar but title differs",
            auto_replanning=False,
        )
        payload = event.model_dump()
        self.assertEqual(payload["type"], "verification_hint")
        self.assertEqual(payload["verdict"], "unsure")
        self.assertFalse(payload["auto_replanning"])

    def test_user_hint_response_round_trips_through_adapter(self) -> None:
        # Confirms UserHintResponseEvent is wired into ClientSessionEvent.
        raw = {
            "type": "user_hint_response",
            "step_id": "step_42",
            "action": "acknowledge_off",
        }
        event = client_session_event_adapter.validate_python(raw)
        self.assertIsInstance(event, UserHintResponseEvent)
        self.assertEqual(event.step_id, "step_42")
        self.assertEqual(event.action, "acknowledge_off")

    def test_user_hint_response_rejects_unknown_action(self) -> None:
        raw = {
            "type": "user_hint_response",
            "step_id": "step_42",
            "action": "not_a_real_action",
        }
        with self.assertRaises(Exception):
            client_session_event_adapter.validate_python(raw)


if __name__ == "__main__":
    unittest.main()
