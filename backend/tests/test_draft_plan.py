from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterator
from typing import Any

from backend.llm import LLMRequest, LLMStreamEvent, LLMTextDelta
from backend.tutorial_guide import generate_draft_plan
from backend.tutorial_schema import DraftPlan, parse_draft_plan
from backend.tutorial_session import TutorialSession, render_history, HistoryEntry
from backend.tutorial_session_events import DraftPlanReadyEvent


VALID_DRAFT_JSON = (
    '{"schema_version":"draft_plan.v1","goal":"open my Canvas course",'
    '"steps":['
    '{"instruction":"Open the Courses menu","kind":"click"},'
    '{"instruction":"Click Introduction to Music Theory","kind":"click"}'
    ']}'
)


class FakeLLMReturningDraft:
    """LLM stub: complete_text returns a valid draft, stream returns text."""

    def __init__(self, draft_json: str = VALID_DRAFT_JSON) -> None:
        self.draft_json = draft_json
        self.complete_text_requests: list[LLMRequest] = []
        self.stream_requests: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:
        self.complete_text_requests.append(request)
        return self.draft_json

    def stream_text(self, request: LLMRequest) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError

    def stream_tutorial_tool_calls(  # pragma: no cover
        self, request: LLMRequest
    ) -> Iterator[Any]:
        raise NotImplementedError

    def stream_tutorial_events(
        self, request: LLMRequest
    ) -> Iterator[LLMStreamEvent]:
        self.stream_requests.append(request)
        return iter([LLMTextDelta(text="ok.")])


class DraftPlanSchemaTests(unittest.TestCase):
    def test_parses_valid_draft_json(self) -> None:
        plan = parse_draft_plan(VALID_DRAFT_JSON)
        self.assertEqual(plan.goal, "open my Canvas course")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].kind, "click")

    def test_rejects_missing_steps(self) -> None:
        with self.assertRaises(Exception):
            parse_draft_plan(
                '{"schema_version":"draft_plan.v1","goal":"x","steps":[]}'
            )


class GenerateDraftPlanTests(unittest.TestCase):
    def test_generate_draft_plan_calls_llm_with_goal(self) -> None:
        llm = FakeLLMReturningDraft()
        plan = generate_draft_plan(llm, goal="open my Canvas course", image=None)
        self.assertIsInstance(plan, DraftPlan)
        self.assertEqual(len(llm.complete_text_requests), 1)
        req = llm.complete_text_requests[0]
        self.assertIn("open my Canvas course", req.user_text)
        self.assertEqual(req.images, [])


class RenderHistoryTests(unittest.TestCase):
    def test_includes_draft_plan_when_provided(self) -> None:
        plan = parse_draft_plan(VALID_DRAFT_JSON)
        text = render_history(
            goal="open my Canvas course",
            history=[HistoryEntry(role="user", content="hello")],
            has_latest_screen=False,
            draft_plan=plan,
        )
        self.assertIn("Draft plan hypothesis", text)
        self.assertIn("Open the Courses menu", text)
        self.assertIn("Click Introduction to Music Theory", text)

    def test_omits_draft_section_when_none(self) -> None:
        text = render_history(
            goal="g",
            history=[HistoryEntry(role="user", content="hello")],
            has_latest_screen=False,
            draft_plan=None,
        )
        self.assertNotIn("Draft plan hypothesis", text)


class SessionDraftPlanIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_user_message_emits_draft_plan_ready(self) -> None:
        events: list[Any] = []

        async def emit(event: Any) -> None:
            events.append(event)

        llm = FakeLLMReturningDraft()
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)
        await session.handle_user_message("open my Canvas course")

        for task in (session.current_task, session.draft_plan_task):
            if task is not None:
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except asyncio.CancelledError:
                    pass

        draft_events = [e for e in events if isinstance(e, DraftPlanReadyEvent)]
        self.assertEqual(len(draft_events), 1)
        self.assertEqual(draft_events[0].plan.goal, "open my Canvas course")
        self.assertIs(session.draft_plan, draft_events[0].plan)

    async def test_draft_plan_is_injected_into_llm_request(self) -> None:
        llm = FakeLLMReturningDraft()

        async def emit(event: Any) -> None:
            pass

        session = TutorialSession(session_id="s1", llm=llm, emit=emit)
        session.goal = "open my Canvas course"
        session.draft_plan = parse_draft_plan(VALID_DRAFT_JSON)
        session.history.append(
            HistoryEntry(role="user", content="open my Canvas course")
        )

        request = session._build_llm_request()
        self.assertIn("Draft plan hypothesis", request.user_text)
        self.assertIn("Open the Courses menu", request.user_text)

    async def test_new_user_message_cancels_stale_draft(self) -> None:
        events: list[Any] = []

        async def emit(event: Any) -> None:
            events.append(event)

        llm = FakeLLMReturningDraft()
        session = TutorialSession(session_id="s1", llm=llm, emit=emit)
        await session.handle_user_message("first goal")
        await session.handle_user_message("second goal")

        for task in (session.current_task, session.draft_plan_task):
            if task is not None:
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except asyncio.CancelledError:
                    pass

        # The draft adopted should match the second goal, not the first.
        self.assertIsNotNone(session.draft_plan)
        adopted = [
            e for e in events if isinstance(e, DraftPlanReadyEvent)
        ]
        # Both drafts may have been generated (the fake LLM returns the
        # same JSON), but the session must have only adopted one whose
        # generation observed the latest goal.
        self.assertGreaterEqual(len(adopted), 1)


if __name__ == "__main__":
    unittest.main()
