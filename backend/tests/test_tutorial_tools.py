from __future__ import annotations

import unittest

from backend.tutorial_tools import (
    INVALID_TOOL_ARGUMENTS,
    INVALID_TOOL_CALL,
    TutorialToolCall,
    TutorialToolCallError,
    step_from_tool_call,
)


class TutorialToolTests(unittest.TestCase):
    def test_click_tool_converts_to_tutorial_step(self) -> None:
        step = step_from_tool_call(
            TutorialToolCall(
                name="tutorial_click",
                arguments=(
                    '{"human_text":"Click the New button.",'
                    '"agent_description":"A green New button in the toolbar.",'
                    '"confidence":0.82}'
                ),
            ),
            index=0,
        )

        self.assertEqual(step.step_id, "step_001")
        self.assertEqual(step.instruction, "Click the New button.")
        self.assertEqual(step.action.type, "click")
        self.assertEqual(
            step.action.target.description,
            "A green New button in the toolbar.",
        )
        self.assertEqual(step.confidence, 0.82)
        self.assertTrue(step.requires_confirmation)

    def test_type_tool_converts_copiable_text(self) -> None:
        step = step_from_tool_call(
            TutorialToolCall(
                name="tutorial_type",
                arguments=(
                    '{"human_text":"Type the repo name.",'
                    '"copiable_text":"context-demo",'
                    '"agent_description":"The repository name text field.",'
                    '"confidence":0.75}'
                ),
            ),
            index=1,
        )

        self.assertEqual(step.step_id, "step_002")
        self.assertEqual(step.action.type, "type")
        self.assertEqual(step.action.text, "context-demo")
        self.assertEqual(
            step.action.target.description,
            "The repository name text field.",
        )
        self.assertEqual(step.confidence, 0.75)
        self.assertTrue(step.requires_confirmation)

    def test_scroll_tool_converts_expected_end_state_to_target(self) -> None:
        step = step_from_tool_call(
            TutorialToolCall(
                name="tutorial_scroll",
                arguments=(
                    '{"human_text":"Scroll down to billing.",'
                    '"expected_end_state":"The Billing section is visible.",'
                    '"confidence":0.7}'
                ),
            ),
            index=2,
        )

        self.assertEqual(step.step_id, "step_003")
        self.assertEqual(step.action.type, "scroll")
        self.assertEqual(step.action.direction, "down")
        self.assertEqual(
            step.action.target.description,
            "The Billing section is visible.",
        )
        self.assertEqual(step.confidence, 0.7)
        self.assertTrue(step.requires_confirmation)

    def test_rejects_missing_copiable_text_for_type_tool(self) -> None:
        with self.assertRaises(TutorialToolCallError) as error:
            step_from_tool_call(
                TutorialToolCall(
                    name="tutorial_type",
                    arguments=(
                        '{"human_text":"Type the repo name.",'
                        '"agent_description":"The repository name text field."}'
                    ),
                ),
                index=0,
            )

        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_blank_human_text(self) -> None:
        with self.assertRaises(TutorialToolCallError) as error:
            step_from_tool_call(
                TutorialToolCall(
                    name="tutorial_click",
                    arguments=(
                        '{"human_text":"   ",'
                        '"agent_description":"A green New button."}'
                    ),
                ),
                index=0,
            )

        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_unknown_tool_name(self) -> None:
        with self.assertRaises(TutorialToolCallError) as error:
            step_from_tool_call(
                TutorialToolCall(
                    name="tutorial_event",
                    arguments='{"human_text":"Click New."}',
                ),
                index=0,
            )

        self.assertEqual(error.exception.code, INVALID_TOOL_CALL)


if __name__ == "__main__":
    unittest.main()
