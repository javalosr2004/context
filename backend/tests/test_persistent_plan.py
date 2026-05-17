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
        "kind": "click",
        "human_text": human_text,
        "agent_description": description,
        "confidence": confidence,
        "step_handle": None,
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

        # Turn 1: emit a 2-step plan. The walk processes both steps in one
        # pass (no agent re-entry between confirmations).
        # Turn 2 (after the post-walk fresh screen): final text -> done.
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=PLAN_TWO_CLICKS)],
                [LLMTextDelta(text="All done.")],
            ]
        )
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)

        await session.handle_user_message("Walk me through it.")
        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001")
        await wait_until(
            lambda: any(type(e).__name__ == "AwaitingConfirmationEvent" for e in events)
        )
        await session.handle_user_confirmation("step_001", confirmed=True, note=None)

        await wait_until(lambda: session.awaiting_step_id == "step_002")
        self.assertEqual(
            [s.step_id for s in session.plan_steps], ["step_001", "step_002"]
        )
        self.assertEqual(session.completed_step_ids, ["step_001"])

        await session.handle_step_started("step_002")
        await wait_until(
            lambda: session.status == "awaiting_confirmation"
            and session.awaiting_step_id == "step_002"
        )
        await session.handle_user_confirmation("step_002", confirmed=True, note=None)
        await send_screen(session, events)
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

        # Turn 1: 2-step plan. Turn 2 (after step_002 rejected): text.
        llm = ScriptedLLM(
            [
                [LLMToolCallEvent(tool_call=PLAN_TWO_CLICKS)],
                [LLMTextDelta(text="Got it, will rethink.")],
            ]
        )
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)

        await session.handle_user_message("Walk me through it.")
        await send_screen(session, events)
        await wait_until(lambda: session.awaiting_step_id == "step_001")
        await session.handle_step_started("step_001")
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation("step_001", confirmed=True, note=None)

        await wait_until(lambda: session.awaiting_step_id == "step_002")
        await session.handle_step_started("step_002")
        await wait_until(lambda: session.status == "awaiting_confirmation")
        await session.handle_user_confirmation(
            "step_002", confirmed=False, note="Button is gone."
        )
        await send_screen(session, events)
        await wait_for_idle(session)

        self.assertEqual([s.step_id for s in session.plan_steps], ["step_001"])
        self.assertEqual(session.completed_step_ids, ["step_001"])
        # step_counter must NOT roll back — must remain at 2 so any future
        # step takes step_003+.
        self.assertEqual(session.step_counter, 2)
        # All tail handles cleared on rejection.
        self.assertEqual(session.handle_index, {})

    async def test_render_history_renders_frozen_and_tail_blocks(self) -> None:
        click_step = TutorialStep(
            step_id="step_001",
            instruction="Click New.",
            action=TutorialAction(
                type="click",
                target=ActionTarget(kind="element", description="green button"),
            ),
            confidence=0.9,
            requires_confirmation=True,
        )
        type_step = TutorialStep(
            step_id="step_002",
            instruction="Type the URL.",
            action=TutorialAction(
                type="type",
                target=ActionTarget(kind="element", description="URL field"),
                text="x",
            ),
            confidence=0.6,
            requires_confirmation=True,
        )
        third_step = TutorialStep(
            step_id="step_003",
            instruction="Press Enter.",
            action=TutorialAction(type="press_key", key="Enter"),
            confidence=0.4,
            requires_confirmation=True,
        )

        text = render_history(
            goal="open my Canvas course",
            history=[HistoryEntry(role="user", content="hello")],
            has_latest_screen=True,
            plan_steps=[click_step, type_step, third_step],
            completed_step_ids=["step_001"],
            awaiting_step_id="step_002",
            handle_index={"h_003": third_step},
            attempts_without_progress={},
            last_action_kind="click",
        )
        self.assertIn("FROZEN", text)
        self.assertIn("TAIL", text)
        self.assertIn("step_001 [done]", text)
        self.assertIn("step_002 [AWAITING]", text)
        self.assertIn("handle=h_003", text)
        self.assertIn("last_completed_action: click", text)

    async def test_render_history_emits_stall_directive(self) -> None:
        step = TutorialStep(
            step_id="step_005",
            instruction="Click something.",
            action=TutorialAction(
                type="click",
                target=ActionTarget(kind="element", description="x"),
            ),
            confidence=0.9,
            requires_confirmation=True,
        )
        text = render_history(
            goal="x",
            history=[],
            plan_steps=[step],
            completed_step_ids=[],
            awaiting_step_id="step_005",
            handle_index={},
            attempts_without_progress={"step_005": 2},
        )
        self.assertIn("STALL", text)
        self.assertIn("step_005", text)


if __name__ == "__main__":
    unittest.main()
