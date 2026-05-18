from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import Iterator
from typing import Any

from backend.llm import LLMRequest, LLMStreamEvent, LLMTextDelta, LLMToolCallEvent
from backend.tutorial_session import TutorialSession
from backend.tutorial_session_events import (
    AwaitingConfirmationEvent,
    InstructionVerifiedEvent,
    PlanReadyEvent,
    PlanUpdatedEvent,
    ScreenRequestedEvent,
    ScreenSnapshot,
    SessionCompletedEvent,
    StepReadyEvent,
    TextResponseEventLike,
    TutorialTextDeltaEvent,
    client_session_event_adapter,
)
from backend.tutorial_tools import TutorialToolCall


def update_plan_call(*items: dict[str, Any], reasoning: str = "first hypothesis") -> TutorialToolCall:
    return TutorialToolCall(
        name="tutorial_update_plan",
        arguments=json.dumps({"plan_reasoning": reasoning, "plan": list(items)}),
    )


def click_item(
    human_text: str = "Click New.",
    description: str = "Green New button.",
    confidence: float = 0.9,
    refines_current: bool = False,
) -> dict[str, Any]:
    return {
        "human_text": human_text,
        "confidence": confidence,
        "refines_current": refines_current,
        "actions": [{"kind": "click", "agent_description": description}],
    }


CLICK_PLAN_CALL = update_plan_call(click_item())
REQUEST_SCREEN_CALL = TutorialToolCall(
    name="tutorial_request_screen",
    arguments='{"reason": "Need to see current screen."}',
)


class ScriptedLLM:
    """LLM stub that returns a pre-scripted list of event lists, one per call."""

    def __init__(self, script: list[list[LLMStreamEvent]]) -> None:
        self.script = list(script)
        self.requests: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:
        # Used by the draft-plan task; return a minimal valid draft so the
        # background task succeeds without distorting the agent loop.
        return (
            '{"schema_version":"draft_plan.v1","goal":"x","steps":'
            '[{"instruction":"step","kind":"other"}]}'
        )

    def stream_text(self, request: LLMRequest) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError

    def stream_tutorial_tool_calls(  # pragma: no cover
        self, request: LLMRequest
    ) -> Iterator[TutorialToolCall]:
        raise NotImplementedError

    def stream_tutorial_events(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        self.requests.append(request)
        if not self.script:
            raise AssertionError("ScriptedLLM exhausted: no more turns scripted")
        events = self.script.pop(0)
        return iter(events)


async def collect_events(emit_target: list[Any]) -> Any:
    async def emit(event: Any) -> None:
        emit_target.append(event)
    return emit


class TutorialSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_message_event_accepts_uploaded_images(self) -> None:
        event = client_session_event_adapter.validate_python(
            {
                "type": "user_message",
                "text": "Use this image.",
                "uploaded_images": [
                    {"mime_type": "image/png", "data_base64": tiny_png_base64()}
                ],
            }
        )

        self.assertEqual(event.text, "Use this image.")
        self.assertEqual(len(event.uploaded_images), 1)

    async def test_text_only_response_emits_text_response_and_no_plan(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM([[LLMTextDelta(text="RunPod is a cloud GPU host.")]])
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("What is RunPod?")
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        plan_events = [e for e in events if isinstance(e, PlanReadyEvent)]
        self.assertEqual(len(text_events), 1)
        self.assertEqual(text_events[0].text, "RunPod is a cloud GPU host.")
        self.assertEqual(plan_events, [])
        self.assertEqual(session.plan_steps, [])

    async def test_text_only_response_preserves_boundary_whitespace(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM([[LLMTextDelta(text="\n\nA formatted answer.\n\n")]])
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Format this.")
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        self.assertEqual(len(text_events), 1)
        self.assertEqual(text_events[0].text, "\n\nA formatted answer.\n\n")

    async def test_text_deltas_stream_before_final_text_response(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [[LLMTextDelta(text="First "), LLMTextDelta(text="second.")]]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Explain this.")
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        delta_events = [e for e in events if isinstance(e, TutorialTextDeltaEvent)]
        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        self.assertEqual([event.text for event in delta_events], ["First ", "second."])
        self.assertEqual(len(text_events), 1)
        self.assertEqual(text_events[0].text, "First second.")
        self.assertLess(events.index(delta_events[0]), events.index(text_events[0]))

    async def test_update_plan_emits_plan_ready_and_awaits_confirmation(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_PLAN_CALL)],
                [LLMTextDelta(text="Looks done.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await send_next_requested_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")

        plan_events = [e for e in events if isinstance(e, PlanReadyEvent)]
        self.assertEqual(len(plan_events), 1)
        self.assertEqual(len(plan_events[0].plan.steps), 1)
        self.assertEqual(plan_events[0].plan.steps[0].instruction, "Click New.")

        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: any(
            isinstance(e, AwaitingConfirmationEvent) for e in events
        ))
        await session.handle_user_confirmation("step_001", action_index=0, confirmed=True, note=None)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertIn(SessionCompletedEvent(), events)

    async def test_completed_screen_changing_step_triggers_fresh_screen(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_PLAN_CALL)],
                [LLMTextDelta(text="The new screen is visible.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await send_next_requested_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation("step_001", action_index=0, confirmed=True, note=None)
        await wait_until(
            lambda: session.pending_screen_request_id is not None
        )

        self.assertEqual(len(llm.requests), 1)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(len(llm.requests[1].images), 1)

    async def test_request_screen_in_same_turn_runs_before_walk_resumes(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                # Turn 1: emit plan + immediately request a screen to verify.
                [
                    LLMToolCallEvent(tool_call=CLICK_PLAN_CALL),
                    LLMToolCallEvent(tool_call=REQUEST_SCREEN_CALL),
                ],
                # Turn 2 (after fresh screen from turn-1 request): text means
                # 'continue walking' — agent loop returns and walk resumes.
                [LLMTextDelta(text="Now I can continue.")],
                # Turn 3 (after the post-confirmation fresh screen): text -> done.
                [LLMTextDelta(text="All done.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await send_next_requested_screen(session, events)
        # The screen request after the update_plan call should arrive before
        # the walk hands the step to the user.
        await send_next_requested_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation("step_001", action_index=0, confirmed=True, note=None)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertGreaterEqual(len(llm.requests), 2)

    async def test_request_screen_suspends_loop_until_screen_arrives(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=REQUEST_SCREEN_CALL)],
                [LLMTextDelta(text="Now I can see the page.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Help me deploy.")
        await send_next_requested_screen(session, events)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        self.assertEqual(len(text_events), 1)
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(len(llm.requests[1].images), 1)

    async def test_user_uploaded_images_are_attached_to_planner_request(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM([[LLMTextDelta(text="I can use that reference.")]])
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message(
            "Use this reference image.",
            [
                ScreenSnapshot(
                    mime_type="image/png",
                    data_base64=tiny_png_base64(),
                )
            ],
        )
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(len(llm.requests[0].images), 2)
        self.assertEqual(llm.requests[0].images[0].filename, "screen")
        self.assertEqual(llm.requests[0].images[1].filename, "uploaded_image_001")
        self.assertIn("uploaded_reference_images", llm.requests[0].user_text)

    async def test_step_rejection_clears_tail_handles(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_PLAN_CALL)],
                [LLMTextDelta(text="Got it. Let me rethink.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await send_next_requested_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_001", action_index=0, confirmed=False, note="That button is gone."
        )
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(session.plan_steps, [])
        # step_counter remains monotonic so the next plan gets fresh IDs.
        self.assertEqual(session.step_counter, 1)

    async def test_plan_steps_minted_after_first_emission(self) -> None:
        events: list[Any] = []
        first_call = update_plan_call(
            click_item(human_text="Click A.", description="Button A."),
            click_item(human_text="Click B.", description="Button B."),
        )
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=first_call)],
                [LLMTextDelta(text="ok")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Walk me through it.")
        await send_next_requested_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")

        self.assertEqual(session.step_counter, 2)
        self.assertEqual([s.step_id for s in session.plan_steps], ["step_001", "step_002"])

    async def test_unknown_tool_call_is_logged_and_ignored(self) -> None:
        events: list[Any] = []
        unknown = TutorialToolCall(name="tutorial_click", arguments="{}")
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=unknown)],
                [LLMTextDelta(text="ignored")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("hi")
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(session.plan_steps, [])
        plan_ready = [e for e in events if isinstance(e, PlanReadyEvent)]
        self.assertEqual(plan_ready, [])


class InstructionVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_verdict_triggers_replan_and_truncates_plan(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_PLAN_CALL)],
                # After verifier-driven replan, agent finishes with text.
                [LLMTextDelta(text="Replanning.")],
            ]
        )
        fast_llm = _FixedTextLLM(
            '{"verdict":"no","reason":"wrong app in foreground"}'
        )
        session = TutorialSession(
            session_id="s1",
            llm=llm,
            fast_llm=fast_llm,
            emit=await collect_events(events),
        )

        await session.handle_user_message("Click New.")
        await send_next_requested_screen(session, events)
        # After plan emission, _await_step kicks off verification.
        # The "no" verdict should drop the plan tail without any user input.
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        verified = [e for e in events if isinstance(e, InstructionVerifiedEvent)]
        self.assertTrue(verified)
        self.assertFalse(verified[0].ok)
        # Plan tail dropped because verification rejected it before user acted.
        self.assertEqual(session.plan_steps, [])
        # Replan note made it into the history.
        self.assertTrue(
            any(
                "Screen verification failed" in entry.content
                for entry in session.history
                if entry.role == "user"
            )
        )

    async def test_yes_verdict_does_not_disturb_walk(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_PLAN_CALL)],
                [LLMTextDelta(text="Done.")],
            ]
        )
        fast_llm = _FixedTextLLM('{"verdict":"yes","reason":"matches"}')
        session = TutorialSession(
            session_id="s1",
            llm=llm,
            fast_llm=fast_llm,
            emit=await collect_events(events),
        )

        await session.handle_user_message("Click New.")
        await send_next_requested_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_001", action_index=0, confirmed=True, note=None
        )
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        verified = [e for e in events if isinstance(e, InstructionVerifiedEvent)]
        self.assertTrue(verified and verified[0].ok)
        self.assertEqual(session.completed_step_ids, ["step_001"])

    async def test_user_input_cancels_in_flight_verifier(self) -> None:
        # Direct unit test of _cancel_verification on a pending asyncio task.
        # Avoids spinning up the full session to keep the test process from
        # stranding a blocked executor thread.
        async def never() -> None:
            await asyncio.sleep(60)

        session = TutorialSession(
            session_id="s1",
            llm=ScriptedLLM([]),
            emit=await collect_events([]),
        )
        session.verifying_step_id = "step_001"
        session.verification_task = asyncio.create_task(never())

        await session.handle_step_started("step_001", action_index=0)

        self.assertIsNone(session.verifying_step_id)
        self.assertIsNone(session.verification_task)


class _FixedTextLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def complete_text(self, request: LLMRequest) -> str:
        return self.raw

    def stream_text(self, request: LLMRequest):  # pragma: no cover
        raise NotImplementedError

    def stream_tutorial_tool_calls(self, request: LLMRequest):  # pragma: no cover
        raise NotImplementedError

    def stream_tutorial_events(self, request: LLMRequest):  # pragma: no cover
        raise NotImplementedError


async def wait_for_idle(session: TutorialSession) -> None:
    for task in (session.current_task, session.draft_plan_task):
        if task is None:
            continue
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed > timeout:
            raise AssertionError("Timed out waiting for predicate")


async def send_next_requested_screen(
    session: TutorialSession,
    events: list[Any],
) -> None:
    await wait_until(
        lambda: any(
            isinstance(e, ScreenRequestedEvent)
            and e.request_id == session.pending_screen_request_id
            for e in events
        )
    )
    request_id = session.pending_screen_request_id
    screen_event = next(
        e
        for e in events
        if isinstance(e, ScreenRequestedEvent)
        and e.request_id == request_id
    )
    await session.handle_user_screen(
        screen_event.request_id,
        ScreenSnapshot(mime_type="image/png", data_base64=tiny_png_base64()),
    )
    await wait_until(lambda: session.pending_screen_request_id != request_id)


def tiny_png_base64() -> str:
    # 1x1 transparent PNG.
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAen"
        "k1AAAAABJRU5ErkJggg=="
    )


if __name__ == "__main__":
    unittest.main()
