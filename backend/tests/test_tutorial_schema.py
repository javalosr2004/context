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

        self.assertEqual(plan.steps[0].actions[0].type, "click")

    def test_accepts_multi_action_step(self) -> None:
        plan = parse_tutorial_plan(
            build_plan_json(
                """
{
  "step_id": "step_001",
  "instruction": "Open new repo flow.",
  "actions": [
    {
      "type": "click",
      "target": {"kind": "element", "label": "New", "role": "button"},
      "requires_confirmation": true
    },
    {
      "type": "type",
      "target": {"kind": "element", "label": "Repo name"},
      "text": "demo",
      "requires_confirmation": true
    }
  ],
  "confidence": 0.9
}
""".strip()
            )
        )
        self.assertEqual(len(plan.steps[0].actions), 2)

    def test_rejects_empty_actions_list(self) -> None:
        with self.assertRaises(TutorialPlanValidationError):
            parse_tutorial_plan(
                build_plan_json(
                    """
{
  "step_id": "step_001",
  "instruction": "Empty.",
  "actions": [],
  "confidence": 0.9
}
""".strip()
                )
            )

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
  "actions": [{
    "type": "submit",
    "target": {"kind": "element", "label": "Create repository"},
    "requires_confirmation": false
  }],
  "confidence": 0.86
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
  "actions": [{
    "type": "type",
    "target": {"kind": "element", "label": "Repository name"},
    "payload": {"text": "context-demo"},
    "requires_confirmation": false
  }],
  "confidence": 0.86
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
  "actions": [{
    "type": "confirm",
    "requires_confirmation": false
  }],
  "confidence": 0.86
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
  "actions": [{
    "type": "click",
    "requires_confirmation": true
  }],
  "confidence": 0.9
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
  "actions": [{
    "type": "wait",
    "requires_confirmation": false
  }],
  "confidence": 0.9
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
""".strip()


if __name__ == "__main__":
    unittest.main()
