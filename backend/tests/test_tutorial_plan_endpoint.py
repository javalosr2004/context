from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.main import create_app, get_tutorial_guide
from backend.tutorial_guide import TutorialPlanRequest
from backend.tutorial_schema import (
    TutorialPlan,
    TutorialPlanValidationError,
    parse_tutorial_plan,
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
      "actions": [
        {
          "type": "click",
          "target": {
            "kind": "element",
            "label": "New repository",
            "role": "button"
          },
          "requires_confirmation": false
        }
      ],
      "confidence": 0.86
    }
  ]
}
""".strip()


class StubTutorialGuide:
    def __init__(self) -> None:
        self.requests: list[TutorialPlanRequest] = []

    def create_plan(self, request: TutorialPlanRequest) -> TutorialPlan:
        self.requests.append(request)
        return parse_tutorial_plan(VALID_PLAN_JSON)


class InvalidTutorialGuide:
    def create_plan(self, request: TutorialPlanRequest) -> TutorialPlan:
        raise TutorialPlanValidationError("LLM returned an invalid tutorial plan.")


class TutorialPlanEndpointTests(unittest.TestCase):
    def test_create_tutorial_plan_returns_validated_plan(self) -> None:
        app = create_app()
        guide = StubTutorialGuide()
        app.dependency_overrides[get_tutorial_guide] = lambda: guide
        client = TestClient(app)

        response = client.post(
            "/tutorials/plan",
            data={
                "conversation_id": "conversation-1",
                "text": "Show me how to create a repo.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schema_version"], "tutorial_plan.v1")
        self.assertEqual(guide.requests[0].conversation_id, "conversation-1")
        self.assertEqual(guide.requests[0].text, "Show me how to create a repo.")

    def test_create_tutorial_plan_rejects_invalid_llm_plan(self) -> None:
        app = create_app()
        app.dependency_overrides[get_tutorial_guide] = lambda: InvalidTutorialGuide()
        client = TestClient(app)

        with self.assertLogs("backend.main", level="ERROR"):
            response = client.post(
                "/tutorials/plan",
                data={
                    "conversation_id": "conversation-1",
                    "text": "Show me how to create a repo.",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "LLM returned an invalid tutorial plan.")


if __name__ == "__main__":
    unittest.main()
