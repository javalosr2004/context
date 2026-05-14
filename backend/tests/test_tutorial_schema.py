from __future__ import annotations

import unittest

from backend.tutorial_schema import (
    TutorialPlanValidationError,
    parse_tutorial_plan,
    tutorial_plan_response_schema,
)


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

    def test_rejects_invalid_json_without_extracting_fragments(self) -> None:
        raw_plan = f"{build_plan_json(valid_click_step_json())}\n\n}}"

        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(raw_plan)

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

    def test_rejects_confirm_actions_without_confirmation(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
                build_plan_json(
                    """
{
  "step_id": "step_001",
  "instruction": "Confirm the page looks correct.",
  "action": {
    "type": "confirm"
  },
  "confidence": 0.86,
  "requires_confirmation": false
}
""".strip()
                )
            )

    def test_rejects_low_confidence_steps_without_confirmation(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
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

    def test_rejects_pointer_action_without_target(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
                build_plan_json(
                    """
{
  "step_id": "step_001",
  "instruction": "Click the button.",
  "action": {
    "type": "click"
  },
  "confidence": 0.9,
  "requires_confirmation": false
}
""".strip()
                )
            )

    def test_rejects_wait_without_duration(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
                build_plan_json(
                    """
{
  "step_id": "step_001",
  "instruction": "Wait for loading to finish.",
  "action": {
    "type": "wait"
  },
  "confidence": 0.9,
  "requires_confirmation": false
}
""".strip()
                )
            )

    def test_response_schema_exposes_action_enum(self) -> None:
        schema = tutorial_plan_response_schema()
        action_schema = schema["$defs"]["TutorialAction"]

        self.assertIn("description", action_schema["properties"]["type"])
        self.assertIn("click", action_schema["properties"]["type"]["enum"])
        self.assertIn("press_key", action_schema["properties"]["type"]["enum"])

    def test_response_schema_removes_gemini_unsupported_keywords(self) -> None:
        schema_text = str(tutorial_plan_response_schema())

        self.assertNotIn("additionalProperties", schema_text)
        self.assertNotIn("additional_properties", schema_text)
        self.assertNotIn("'default'", schema_text)


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
