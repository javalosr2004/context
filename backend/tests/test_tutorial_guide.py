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
    plan_generation_prompt,
)

VALID_PLAN_JSON = """
{
  "schema_version": "tutorial_plan.v1",
  "goal": "Create a new GitHub repository",
  "summary": "Open the repository creation flow and fill out the form.",
  "steps": [
    {
      "step_id": "step_001",
      "instruction": "Click the New repository button.",
      "action": {
        "type": "click",
        "target": {
          "kind": "element",
          "label": "New repository",
          "role": "button"
        }
      },
      "confidence": 0.86,
      "requires_confirmation": false
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

    def test_tool_stream_prompt_describes_loop_and_tool_rules(self) -> None:
        self.assertIn("agent loop", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("tutorial_update_plan", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("tutorial_request_screen", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("FROZEN", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("step_handle", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)

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
        self.assertEqual(plan.steps[0].action.type, "click")
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(llm.requests[0].system_prompt, TUTORIAL_PLAN_SYSTEM_PROMPT)
        self.assertIn("Show me how to create a repo.", llm.requests[0].user_text)
        self.assertEqual(llm.requests[0].images, [])
        self.assertFalse(llm.requests[0].enable_search_grounding)
        self.assertEqual(llm.requests[0].response_mime_type, "application/json")
        self.assertIsNotNone(llm.requests[0].response_schema)
        self.assertEqual(llm.requests[0].temperature, 0)

    def test_create_plan_retries_with_validation_error_context(self) -> None:
        llm = FakeLLM(complete_responses=["not-json", VALID_PLAN_JSON])
        guide = TutorialGuide(llm)

        with self.assertLogs("backend.tutorial_guide", level="WARNING"):
            plan = guide.create_plan(
                TutorialPlanRequest(
                    conversation_id="conversation-1",
                    text="Show me how to create a repo.",
                    images=[],
                )
            )

        self.assertEqual(plan.schema_version, "tutorial_plan.v1")
        self.assertEqual(len(llm.requests), 2)
        self.assertIn("Fix the previous JSON", llm.requests[1].user_text)
        self.assertIn("not-json", llm.requests[1].user_text)
        self.assertIsNotNone(llm.requests[1].response_schema)

    def test_plan_generation_prompt_does_not_duplicate_json_schema(self) -> None:
        prompt = plan_generation_prompt(
            prompt="Create a tutorial plan.",
            attempt=0,
            error_text="",
            last_text="",
        )

        self.assertEqual(prompt, "Create a tutorial plan.")
        self.assertNotIn("schema_version", TUTORIAL_PLAN_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
