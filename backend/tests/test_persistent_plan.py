"""Persistent plan state across walks.

Covers:
- plan_steps and completed_step_ids survive walk boundaries
- step_counter is monotonic across walks (no ID collisions after rejection)
- PlanReadyEvent fires once; subsequent plan changes emit PlanUpdatedEvent
- Confirmations are not dropped when they race a walk transition
- render_history renders the new FROZEN/TAIL plan block
"""

from __future__ import annotations

import asyncio
import base64
import json
import unittest
from collections.abc import Iterator
from typing import Any

from backend.llm import LLMRequest, LLMStreamEvent, LLMTextDelta, LLMToolCallEvent
from backend.tutorial_schema import ActionTarget, TutorialAction, TutorialStep
from backend.tutorial_session import HistoryEntry, TutorialSession, render_history
from backend.tutorial_session_events import (
    CompletionProposedEvent,
    PlanReadyEvent,
    PlanUpdatedEvent,
    ScreenRequestedEvent,
    ScreenSnapshot,
    SessionCompletedEvent,
)
from backend.tutorial_tools import TutorialToolCall


def update_plan_call(*items: dict[str, Any], reasoning: str = "hypothesis") -> TutorialToolCall:
    return TutorialToolCall(
        name="tutorial_update_plan",
        arguments=json.dumps({"plan_reasoning": reasoning, "plan": list(items)}),
    )


def click_item(human_text: str, description: str, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "human_text": human_text,
        "confidence": confidence,
        "refines_current": False,
        "actions": [{"kind": "click", "agent_description": description}],
    }


PLAN_TWO_CLICKS = update_plan_call(
    click_item("Click New.", "Green New button."),
    click_item("Click Next.", "Blue Next button.", confidence=0.85),
)
PLAN_ONE_CLICK = update_plan_call(click_item("Click New.", "Green New button."))


def tiny_png() -> str:
    data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc"
        b"\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return base64.b64encode(data).decode()


class ScriptedLLM:
    def __init__(self, script: list[list[LLMStreamEvent]]) -> None:
        self.script = list(script)
        self.requests: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:
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
            raise AssertionError("ScriptedLLM exhausted")
        return iter(self.script.pop(0))


async def wait_until(predicate, timeout: float = 2.0) -> None:
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(0.01)
        elapsed += 0.01
        if elapsed > timeout:
            raise AssertionError("Timed out waiting for predicate")


async def wait_for_idle(session: TutorialSession) -> None:
    for task in (session.current_task, session.draft_plan_task):
        if task is None:
            continue
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass


async def send_screen(session: TutorialSession, events: list[Any]) -> None:
    await wait_until(
        lambda: any(
            isinstance(e, ScreenRequestedEvent)
            and e.request_id == session.pending_screen_request_id
            for e in events
        )
    )
    request_id = session.pending_screen_request_id
    assert request_id is not None
    await session.handle_user_screen(
        request_id,
        ScreenSnapshot(mime_type="image/png", data_base64=tiny_png()),
    )
    await wait_until(lambda: session.pending_screen_request_id != request_id)


class PersistentPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_survives_walks_and_emits_one_plan_ready(self) -> None:
        events: list[Any] = []

        async def emit(event: Any) -> None:
            events.append(event)

        # Turn 1: emit a 2-step plan.
        # Walk bails after step_001 (requires_confirmation=true on click)
        # so the agent re-validates against a fresh screen before step_002.
        # Turn 2: text-only continuation, walker resumes on step_002.
        # Turn 3: final text after step_002.
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=PLAN_TWO_CLICKS)],
                [LLMTextDelta(text="Looks good, continuing.")],
                [LLMTextDelta(text="All done.")],
            ]
        )
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)

        await session.handle_user_message("Walk me through it.")
        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(
            lambda: any(type(e).__name__ == "AwaitingConfirmationEvent" for e in events)
        )
        await session.handle_user_confirmation("step_001", action_index=0, confirmed=True, note=None)

        # Walker bails after step_001 -> screen request -> turn 2.
        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_002")
        self.assertEqual(
            [s.step_id for s in session.plan_steps], ["step_001", "step_002"]
        )
        self.assertEqual(session.completed_step_ids, ["step_001"])

        await session.handle_step_started("step_002", action_index=0)
        await wait_until(
            lambda: session.status == "awaiting_confirmation"
            and session.awaiting_step_id == "step_002"
        )
        await session.handle_user_confirmation("step_002", action_index=0, confirmed=True, note=None)
        await send_screen(session, events)
        await wait_until(
            lambda: any(isinstance(e, CompletionProposedEvent) for e in events)
        )
        await session.handle_user_completion_response(confirmed=True, note=None)
        await wait_for_idle(session)

        plan_ready = [e for e in events if isinstance(e, PlanReadyEvent)]
        plan_updated = [e for e in events if isinstance(e, PlanUpdatedEvent)]
        self.assertEqual(len(plan_ready), 1, "plan_ready fires only once")
        # PlanUpdatedEvent fires per update_plan call, not per walk. This
        # test only emits update_plan once, so zero updates is correct.
        self.assertEqual(len(plan_updated), 0)
        self.assertIn(SessionCompletedEvent(), events)
        self.assertEqual(session.completed_step_ids, ["step_001", "step_002"])

    async def test_rejection_truncates_plan_but_keeps_completed_prefix(self) -> None:
        events: list[Any] = []

        async def emit(event: Any) -> None:
            events.append(event)

        # Turn 1: 2-step plan.
        # Walker bails after step_001 (requires_confirmation=true), screen
        # check, turn 2 emits intermediate text, walker resumes on step_002,
        # which the user rejects. Turn 3 emits the rethink text.
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=PLAN_TWO_CLICKS)],
                [LLMTextDelta(text="Continuing.")],
                [LLMTextDelta(text="Got it, will rethink.")],
            ]
        )
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)

        await session.handle_user_message("Walk me through it.")
        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation("step_001", action_index=0, confirmed=True, note=None)

        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_002")
        await session.handle_step_started("step_002", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_002", action_index=0, confirmed=False, note="Button is gone."
        )
        await send_screen(session, events)
        await wait_until(
            lambda: any(isinstance(e, CompletionProposedEvent) for e in events)
        )
        await session.handle_user_completion_response(confirmed=True, note=None)
        await wait_for_idle(session)

        self.assertEqual([s.step_id for s in session.plan_steps], ["step_001"])
        self.assertEqual(session.completed_step_ids, ["step_001"])
        # step_counter must NOT roll back — must remain at 2 so any future
        # step takes step_003+.
        self.assertEqual(session.step_counter, 2)

    async def test_render_history_renders_frozen_and_tail_blocks(self) -> None:
        click_step = TutorialStep(
            step_id="step_001",
            instruction="Click New.",
            actions=[
                TutorialAction(
                    type="click",
                    target=ActionTarget(kind="element", description="green button"),
                    requires_confirmation=True,
                )
            ],
            confidence=0.9,
        )
        type_step = TutorialStep(
            step_id="step_002",
            instruction="Type the URL.",
            actions=[
                TutorialAction(
                    type="type",
                    target=ActionTarget(kind="element", description="URL field"),
                    text="x",
                    requires_confirmation=True,
                )
            ],
            confidence=0.6,
        )
        third_step = TutorialStep(
            step_id="step_003",
            instruction="Press Enter.",
            actions=[
                TutorialAction(
                    type="press_key", key="Enter", requires_confirmation=False
                )
            ],
            confidence=0.4,
        )

        text = render_history(
            goal="open my Canvas course",
            history=[HistoryEntry(role="user", content="hello")],
            has_latest_screen=True,
            plan_steps=[click_step, type_step, third_step],
            completed_step_ids=["step_001"],
            awaiting_step_id="step_002",
            attempts_without_progress={},
            last_action_kind="click",
        )
        self.assertIn("COMPLETED", text)
        self.assertIn("AWAITING", text)
        self.assertIn("TAIL", text)
        self.assertIn("step_001 [done]", text)
        self.assertIn("step_002", text)
        self.assertIn("step_003", text)
        self.assertIn("last_completed_action: click", text)

    async def test_render_history_awaiting_single_action_step(self) -> None:
        step = TutorialStep(
            step_id="step_001",
            instruction="Click New.",
            actions=[
                TutorialAction(
                    type="click",
                    target=ActionTarget(kind="element", description="x"),
                    requires_confirmation=True,
                )
            ],
            confidence=0.9,
        )
        text = render_history(
            goal="x",
            history=[],
            plan_steps=[step],
            completed_step_ids=[],
            awaiting_step_id="step_001",
            awaiting_action_index=0,
        )
        self.assertIn("AWAITING", text)
        self.assertIn("[click]", text)
        self.assertNotIn("action 1/1", text)

    async def test_render_history_awaiting_multi_action_step(self) -> None:
        step = TutorialStep(
            step_id="step_001",
            instruction="Name and submit.",
            actions=[
                TutorialAction(
                    type="type",
                    target=ActionTarget(kind="element", description="name field"),
                    text="demo",
                    requires_confirmation=True,
                ),
                TutorialAction(
                    type="press_key", key="Enter", requires_confirmation=False
                ),
            ],
            confidence=0.9,
        )
        text = render_history(
            goal="x",
            history=[],
            plan_steps=[step],
            completed_step_ids=[],
            awaiting_step_id="step_001",
            awaiting_action_index=1,
        )
        self.assertIn("action 2/2", text)
        self.assertIn("[press_key]", text)
        self.assertIn("type,press_key", text)

    async def test_render_history_emits_stall_directive(self) -> None:
        step = TutorialStep(
            step_id="step_005",
            instruction="Click something.",
            actions=[
                TutorialAction(
                    type="click",
                    target=ActionTarget(kind="element", description="x"),
                    requires_confirmation=True,
                )
            ],
            confidence=0.9,
        )
        text = render_history(
            goal="x",
            history=[],
            plan_steps=[step],
            completed_step_ids=[],
            awaiting_step_id="step_005",
            attempts_without_progress={"step_005": 2},
        )
        self.assertIn("STALL", text)
        self.assertIn("step_005", text)


class MultiActionWalkTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_action_step_walks_action_by_action(self) -> None:
        events: list[Any] = []

        async def emit(event: Any) -> None:
            events.append(event)

        two_action_call = update_plan_call(
            {
                "human_text": "Name and submit the repo.",
                "confidence": 0.9,
                "refines_current": False,
                "actions": [
                    {
                        "kind": "type",
                        "copiable_text": "demo",
                        "agent_description": "Name field.",
                    },
                    {"kind": "press_key", "key": "Enter"},
                ],
            }
        )
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=two_action_call)],
                [LLMTextDelta(text="All done.")],
            ]
        )
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)

        await session.handle_user_message("Walk me.")
        await send_screen(session, events)
        await wait_until(
            lambda: session.awaiting_step_id == "step_001"
            and session.awaiting_action_index == 0
        )
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_001", action_index=0, confirmed=True, note=None
        )

        # press_key has requires_confirmation=False by default; it should
        # auto-advance once started.
        await wait_until(lambda: session.awaiting_action_index == 1)
        await session.handle_step_started("step_001", action_index=1)
        await wait_until(lambda: "step_001" in session.completed_step_ids)

        await send_screen(session, events)
        await wait_until(
            lambda: any(isinstance(e, CompletionProposedEvent) for e in events)
        )
        await session.handle_user_completion_response(confirmed=True, note=None)
        await wait_for_idle(session)

        self.assertEqual(session.completed_step_ids, ["step_001"])
        self.assertIn(SessionCompletedEvent(), events)

    async def test_action_rejection_truncates_plan(self) -> None:
        events: list[Any] = []

        async def emit(event: Any) -> None:
            events.append(event)

        three_action_call = update_plan_call(
            {
                "human_text": "Open settings, scroll, click save.",
                "confidence": 0.9,
                "refines_current": False,
                "actions": [
                    {"kind": "click", "agent_description": "Settings gear."},
                    {
                        "kind": "scroll",
                        "expected_end_state": "Save button is visible.",
                    },
                    {"kind": "click", "agent_description": "Save button."},
                ],
            }
        )
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=three_action_call)],
                [LLMTextDelta(text="Got it, replanning.")],
            ]
        )
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)

        await session.handle_user_message("Help.")
        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_action_index == 0)
        await session.handle_step_started("step_001", action_index=0)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_001", action_index=0, confirmed=True, note=None
        )

        await wait_until(lambda: session.awaiting_action_index == 1)
        await session.handle_step_started("step_001", action_index=1)
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_001", action_index=1, confirmed=False, note="Save not visible."
        )
        await send_screen(session, events)
        await wait_until(
            lambda: any(isinstance(e, CompletionProposedEvent) for e in events)
        )
        await session.handle_user_completion_response(confirmed=True, note=None)
        await wait_for_idle(session)

        # Step never completed; truncated.
        self.assertEqual(session.completed_step_ids, [])
        self.assertEqual(session.plan_steps, [])


if __name__ == "__main__":
    unittest.main()
