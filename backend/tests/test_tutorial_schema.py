from __future__ import annotations

import unittest

from backend.tutorial_schema import TutorialPlanValidationError, parse_tutorial_plan


def build_plan_json(step_json: str) -> str:
    return f"""
{{
  "schema_version": "tutorial_plan.v1",
  "goal": "Create a new GitHub repository",
  "summary": "Create a repository from the GitHub UI.",
  "steps": [
    {step_json}
  ]
}}
""".strip()


class TutorialSchemaTests(unittest.TestCase):
    def test_accepts_valid_click_action(self) -> None:
        plan = parse_tutorial_plan(build_plan_json(valid_click_step_json()))

        self.assertEqual(plan.steps[0].action.type, "click")

    def test_accepts_valid_plan_with_trailing_llm_text(self) -> None:
        raw_plan = f"{build_plan_json(valid_click_step_json())}\n\n}}"

        plan = parse_tutorial_plan(raw_plan)

        self.assertEqual(plan.steps[0].action.type, "click")

    def test_rejects_unknown_action_type(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
                build_plan_json(
                    """
{
  "step_id": "step_001",
  "instruction": "Submit the form.",
  "action": {
    "type": "submit",
    "target": {
      "kind": "element",
      "label": "Create repository"
    }
  },
  "confidence": 0.86,
  "requires_confirmation": false
}
""".strip()
                )
            )

    def test_rejects_generic_payload_field(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
                build_plan_json(
                    """
{
  "step_id": "step_001",
  "instruction": "Type the repository name.",
  "action": {
    "type": "type",
    "target": {
      "kind": "element",
      "label": "Repository name"
    },
    "payload": {
      "text": "context-demo"
    }
  },
  "confidence": 0.86,
  "requires_confirmation": false
}
""".strip()
                )
            )

    def test_normalizes_confirmation_for_confirm_actions(self) -> None:
        plan = parse_tutorial_plan(
            build_plan_json(
                """
{
  "step_id": "step_001",
  "instruction": "Confirm the page looks correct.",
  "action": {
    "type": "confirm",
    "question": "Do you see the repository form?",
    "expected_screen": "The repository form is visible."
  },
  "confidence": 0.86,
  "requires_confirmation": false
}
""".strip()
            )
        )

        self.assertTrue(plan.steps[0].requires_confirmation)

    def test_normalizes_confirmation_for_low_confidence_steps(self) -> None:
        plan = parse_tutorial_plan(
            build_plan_json(
                """
{
  "step_id": "step_001",
  "instruction": "Click the likely matching button.",
  "action": {
    "type": "click",
    "target": {
      "kind": "element",
      "description": "button near the top right"
    }
  },
  "confidence": 0.69,
  "requires_confirmation": false
}
""".strip()
            )
        )

        self.assertTrue(plan.steps[0].requires_confirmation)


def valid_click_step_json() -> str:
    return """
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
""".strip()


if __name__ == "__main__":
    unittest.main()
