from __future__ import annotations

import unittest
from collections.abc import Iterator

from backend.llm import LLMRequest
from backend.tutorial_guide import (
    TUTORIAL_CREATOR_SYSTEM_PROMPT,
    TUTORIAL_PLAN_SYSTEM_PROMPT,
    TutorialGuide,
    TutorialPlanRequest,
    TutorialStreamRequest,
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
    def __init__(self, complete_response: str = VALID_PLAN_JSON) -> None:
        self.complete_response = complete_response
        self.requests: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self.complete_response

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        self.requests.append(request)
        return iter(["first", " second"])


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


if __name__ == "__main__":
    unittest.main()
