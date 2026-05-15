from __future__ import annotations

import unittest
from collections.abc import Iterator

from backend.llm import LLMRequest
from backend.tutorial_tools import TutorialToolCall
from backend.tutorial_guide import (
    TUTORIAL_CREATOR_SYSTEM_PROMPT,
    TUTORIAL_PLAN_SYSTEM_PROMPT,
    TUTORIAL_SESSION_PLANNER_SYSTEM_PROMPT,
    TutorialGuide,
    TutorialPlanRequest,
    TutorialSessionPlanRequest,
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

VALID_READY_REPLY_JSON = f"""
{{
  "type": "ready",
  "plan": {VALID_PLAN_JSON}
}}
""".strip()

VALID_NEEDS_CONTEXT_REPLY_JSON = """
{
  "type": "needs_context",
  "question": "Which repository should I use?"
}
""".strip()


class FakeLLM:
    def __init__(
        self,
        complete_responses: list[str] | None = None,
        tool_calls: list[TutorialToolCall] | None = None,
    ) -> None:
        self.complete_responses = (
            [VALID_PLAN_JSON] if complete_responses is None else complete_responses
        )
        self.tool_calls = tool_calls or []
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


class TutorialGuideTests(unittest.TestCase):
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
        self.assertIn("Invalid JSON", llm.requests[1].user_text)
        self.assertIsNotNone(llm.requests[1].response_schema)

    def test_create_session_planner_reply_accepts_ready_reply(self) -> None:
        llm = FakeLLM(complete_responses=[VALID_READY_REPLY_JSON])
        guide = TutorialGuide(llm)

        reply = guide.create_session_planner_reply(
            TutorialSessionPlanRequest(
                session_id="session-1",
                goal="Show me how to create a repo.",
                messages=[{"role": "user", "content": "Show me how to create a repo."}],
                latest_screen=None,
            )
        )

        self.assertEqual(reply.type, "ready")
        self.assertEqual(len(llm.requests), 2)
        self.assertEqual(
            llm.requests[1].system_prompt,
            TUTORIAL_SESSION_PLANNER_SYSTEM_PROMPT,
        )
        self.assertIn("Show me how to create a repo.", llm.requests[1].user_text)
        self.assertEqual(llm.requests[1].response_mime_type, "application/json")
        self.assertIsNotNone(llm.requests[1].response_schema)

    def test_create_session_planner_reply_uses_streamed_tool_calls(self) -> None:
        llm = FakeLLM(
            complete_responses=[],
            tool_calls=[
                TutorialToolCall(
                    name="tutorial_click",
                    arguments=(
                        '{"human_text":"Click New.","agent_description":"A green New button."}'
                    ),
                )
            ],
        )
        guide = TutorialGuide(llm)

        reply = guide.create_session_planner_reply(
            TutorialSessionPlanRequest(
                session_id="session-1",
                goal="Create a repo.",
                messages=[{"role": "user", "content": "Create a repo."}],
                latest_screen=None,
            )
        )

        self.assertEqual(reply.type, "ready")
        self.assertEqual(reply.plan.steps[0].instruction, "Click New.")
        self.assertEqual(reply.plan.steps[0].action.type, "click")
        self.assertEqual(
            reply.plan.steps[0].action.target.description,
            "A green New button.",
        )

    def test_create_session_planner_reply_accepts_context_question(self) -> None:
        llm = FakeLLM(complete_responses=[VALID_NEEDS_CONTEXT_REPLY_JSON])
        guide = TutorialGuide(llm)

        reply = guide.create_session_planner_reply(
            TutorialSessionPlanRequest(
                session_id="session-1",
                goal="Show me how to create a repo.",
                messages=[],
                latest_screen=None,
            )
        )

        self.assertEqual(reply.type, "needs_context")
        self.assertEqual(reply.question, "Which repository should I use?")

    def test_create_session_planner_reply_includes_all_session_messages(self) -> None:
        llm = FakeLLM(complete_responses=[VALID_READY_REPLY_JSON])
        guide = TutorialGuide(llm)
        messages = [
            {"role": "user", "content": f"message {index}"}
            for index in range(1, 11)
        ]

        guide.create_session_planner_reply(
            TutorialSessionPlanRequest(
                session_id="session-1",
                goal="Show me how to create a repo.",
                messages=messages,
                latest_screen=None,
            )
        )

        self.assertIn("- user: message 1", llm.requests[0].user_text)
        self.assertIn("- user: message 10", llm.requests[0].user_text)

    def test_plan_generation_prompt_does_not_duplicate_json_schema(self) -> None:
        prompt = plan_generation_prompt(
            prompt="Create a tutorial plan.",
            attempt=0,
            error_text="",
            last_text="",
        )

        self.assertEqual(prompt, "Create a tutorial plan.")
        self.assertNotIn("schema_version", TUTORIAL_PLAN_SYSTEM_PROMPT)
        self.assertNotIn("JSON shape", TUTORIAL_PLAN_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
