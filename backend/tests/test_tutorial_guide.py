from __future__ import annotations

import unittest
from collections.abc import Iterator

from backend.llm import LLMRequest, LLMStreamEvent, LLMToolCallEvent
from backend.tutorial_tools import TutorialToolCall
from backend.tutorial_guide import (
    TUTORIAL_CREATOR_SYSTEM_PROMPT,
    TUTORIAL_PLAN_SYSTEM_PROMPT,
    TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT,
    TutorialGuide,
    TutorialPlanRequest,
    TutorialStreamRequest,
)
from backend.tutorial_schema import TutorialPlanValidationError

VALID_PLAN_JSON = """
{
  "schema_version": "tutorial_plan.v1",
  "goal": "Create a new GitHub repository",
  "summary": "Open the repository creation flow and fill out the form.",
  "steps": [
    {
      "step_id": "step_001",
      "instruction": "Click the New repository button.",
      "actions": [{
        "type": "click",
        "target": {
          "kind": "element",
          "label": "New repository",
          "role": "button"
        },
        "requires_confirmation": true
      }],
      "confidence": 0.86
    }
  ]
}
""".strip()


class FakeLLM:
    def __init__(
        self,
        complete_responses: list[str] | None = None,
        tool_calls: list[TutorialToolCall] | None = None,
        stream_events: list[LLMStreamEvent] | None = None,
    ) -> None:
        self.complete_responses = (
            [VALID_PLAN_JSON] if complete_responses is None else complete_responses
        )
        self.tool_calls = tool_calls or []
        self.stream_events = stream_events
        self.requests: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self.complete_responses.pop(0)

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        self.requests.append(request)
        return iter(["first", " second"])

    def stream_tutorial_tool_calls(
        self,
        request: LLMRequest,
    ) -> Iterator[TutorialToolCall]:
        self.requests.append(request)
        return iter(self.tool_calls)

    def stream_tutorial_events(
        self,
        request: LLMRequest,
    ) -> Iterator[LLMStreamEvent]:
        self.requests.append(request)
        if self.stream_events is not None:
            return iter(self.stream_events)
        return iter(LLMToolCallEvent(tool_call=call) for call in self.tool_calls)


class TutorialGuideTests(unittest.TestCase):
    def test_creator_prompt_supports_conversation_mode(self) -> None:
        self.assertIn("Conversational help", TUTORIAL_CREATOR_SYSTEM_PROMPT)
        self.assertIn("not only a tutorial generator", TUTORIAL_CREATOR_SYSTEM_PROMPT)
        self.assertIn("Never announce or describe the internal route", TUTORIAL_CREATOR_SYSTEM_PROMPT)

    def test_tool_stream_prompt_lists_core_tools(self) -> None:
        self.assertIn("tutorial_update_plan", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("tutorial_request_screen", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("tutorial_request_completion", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("tutorial_ask_user", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("refines_current", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("user_choice", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)

    def test_stream_tutorial_maps_domain_request_to_llm_request(self) -> None:
        llm = FakeLLM()
        guide = TutorialGuide(llm)

        tokens = list(
            guide.stream_tutorial(
                TutorialStreamRequest(
                    conversation_id="conversation-1",
                    text="Show me how to create a repo.",
                    images=[],
                )
            )
        )

        self.assertEqual(tokens, ["first", " second"])
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(llm.requests[0].system_prompt, TUTORIAL_CREATOR_SYSTEM_PROMPT)
        self.assertEqual(llm.requests[0].user_text, "Show me how to create a repo.")
        self.assertEqual(llm.requests[0].images, [])
        self.assertTrue(llm.requests[0].enable_search_grounding)
        self.assertIsNone(llm.requests[0].response_mime_type)

    def test_create_plan_requests_json_and_validates_response(self) -> None:
        llm = FakeLLM()
        guide = TutorialGuide(llm)

        plan = guide.create_plan(
            TutorialPlanRequest(
                conversation_id="conversation-1",
                text="Show me how to create a repo.",
                images=[],
            )
        )

        self.assertEqual(plan.schema_version, "tutorial_plan.v1")
        self.assertEqual(plan.steps[0].actions[0].type, "click")
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(llm.requests[0].system_prompt, TUTORIAL_PLAN_SYSTEM_PROMPT)
        self.assertIn("Show me how to create a repo.", llm.requests[0].user_text)
        self.assertEqual(llm.requests[0].images, [])
        self.assertFalse(llm.requests[0].enable_search_grounding)
        self.assertEqual(llm.requests[0].response_mime_type, "application/json")
        self.assertIsNotNone(llm.requests[0].response_schema)
        self.assertEqual(llm.requests[0].temperature, 0)

    def test_create_plan_raises_on_invalid_json_without_retrying(self) -> None:
        llm = FakeLLM(complete_responses=["not-json"])
        guide = TutorialGuide(llm)

        with self.assertLogs("backend.tutorial_guide", level="ERROR"):
            with self.assertRaises(TutorialPlanValidationError):
                guide.create_plan(
                    TutorialPlanRequest(
                        conversation_id="conversation-1",
                        text="Show me how to create a repo.",
                        images=[],
                    )
                )

        self.assertEqual(len(llm.requests), 1)


if __name__ == "__main__":
    unittest.main()
