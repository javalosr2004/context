from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterator
from typing import Any

from backend.llm import LLMRequest, LLMStreamEvent, LLMTextDelta, LLMToolCallEvent
from backend.tutorial_session import TutorialSession
from backend.tutorial_session_events import (
    AwaitingConfirmationEvent,
    PlanReadyEvent,
    ScreenRequestedEvent,
    ScreenSnapshot,
    SessionCompletedEvent,
    StepReadyEvent,
    TextResponseEventLike,
    TutorialActionEvent,
    TutorialTextDeltaEvent,
)
from backend.tutorial_tools import TutorialToolCall


CLICK_CALL = TutorialToolCall(
    name="tutorial_click",
    arguments='{"human_text": "Click New.", "agent_description": "Green New button."}',
)
REQUEST_SCREEN_CALL = TutorialToolCall(
    name="tutorial_request_screen",
    arguments='{"reason": "Need to see current screen."}',
)


class ScriptedLLM:
    """LLM stub that returns a pre-scripted list of event lists, one per call."""

    def __init__(self, script: list[list[LLMStreamEvent]]) -> None:
        self.script = list(script)
        self.requests: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:  # pragma: no cover
        raise NotImplementedError

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
    async def test_text_only_response_emits_text_response_and_no_plan(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM([[LLMTextDelta(text="RunPod is a cloud GPU host.")]])
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("What is RunPod?")
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
        await wait_for_idle(session)

        delta_events = [e for e in events if isinstance(e, TutorialTextDeltaEvent)]
        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        self.assertEqual([event.text for event in delta_events], ["First ", "second."])
        self.assertEqual(len(text_events), 1)
        self.assertEqual(text_events[0].text, "First second.")
        self.assertLess(events.index(delta_events[0]), events.index(text_events[0]))

    async def test_action_tool_call_produces_plan_and_awaits_confirmation(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_CALL)],
                [LLMTextDelta(text="Looks done.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await wait_until(lambda: session.awaiting_step_id == "step_001")

        action_events = [e for e in events if isinstance(e, TutorialActionEvent)]
        plan_events = [e for e in events if isinstance(e, PlanReadyEvent)]
        self.assertEqual(len(action_events), 1)
        self.assertEqual(action_events[0].step.instruction, "Click New.")
        self.assertEqual(len(plan_events), 1)

        await session.handle_step_started("step_001")
        await wait_until(lambda: any(
            isinstance(e, AwaitingConfirmationEvent) for e in events
        ))
        await session.handle_user_confirmation("step_001", confirmed=True, note=None)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertIn(
            SessionCompletedEvent(),
            events,
        )

    async def test_action_tool_call_requests_fresh_screen_before_next_turn(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_CALL)],
                [LLMTextDelta(text="The new screen is visible.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001")
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation("step_001", confirmed=True, note=None)
        await wait_until(
            lambda: any(isinstance(e, ScreenRequestedEvent) for e in events)
        )

        self.assertEqual(len(llm.requests), 1)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(len(llm.requests[1].images), 1)

    async def test_request_screen_mixed_with_actions_waits_until_after_action(self) -> None:
        events: list[Any] = []
        llm = ScriptedLLM(
            [
                [
                    LLMToolCallEvent(tool_call=CLICK_CALL),
                    LLMToolCallEvent(tool_call=REQUEST_SCREEN_CALL),
                ],
                [LLMTextDelta(text="Now I can continue.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        self.assertFalse(any(isinstance(e, ScreenRequestedEvent) for e in events))

        await session.handle_step_started("step_001")
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation("step_001", confirmed=True, note=None)
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(len(llm.requests), 2)

    async def test_request_screen_suspends_loop_until_screen_arrives(self) -> None:
        events: list[Any] = []
        # First call asks for a screen. Second call (after screen) emits no tool calls.
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
        await wait_until(
            lambda: any(isinstance(e, ScreenRequestedEvent) for e in events)
        )

        screen_event = next(
            e for e in events if isinstance(e, ScreenRequestedEvent)
        )
        await session.handle_user_screen(
            screen_event.request_id,
            ScreenSnapshot(mime_type="image/png", data_base64=tiny_png_base64()),
        )
        await wait_for_idle(session)

        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        self.assertEqual(len(text_events), 1)
        self.assertEqual(len(llm.requests), 2)
        # Second LLM call should have received the latest screen as an image.
        self.assertEqual(len(llm.requests[1].images), 1)

    async def test_step_rejection_reruns_agent_loop(self) -> None:
        events: list[Any] = []
        # First call: one click. Second call (after rejection): no tool calls.
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=CLICK_CALL)],
                [LLMTextDelta(text="Got it. Let me know what you see.")],
            ]
        )
        session = TutorialSession(
            session_id="s1", llm=llm, emit=await collect_events(events)
        )

        await session.handle_user_message("Click New.")
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001")
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_001", confirmed=False, note="That button is gone."
        )
        await send_next_requested_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual(len(llm.requests), 2)
        text_events = [e for e in events if isinstance(e, TextResponseEventLike)]
        self.assertEqual(len(text_events), 1)


async def wait_for_idle(session: TutorialSession) -> None:
    task = session.current_task
    if task is None:
        return
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
    screen_event = next(
        e
        for e in events
        if isinstance(e, ScreenRequestedEvent)
        and e.request_id == session.pending_screen_request_id
    )
    await session.handle_user_screen(
        screen_event.request_id,
        ScreenSnapshot(mime_type="image/png", data_base64=tiny_png_base64()),
    )


def tiny_png_base64() -> str:
    # 1x1 transparent PNG.
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAen"
        "k1AAAAABJRU5ErkJggg=="
    )


if __name__ == "__main__":
    unittest.main()
