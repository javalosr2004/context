from __future__ import annotations

import json
import unittest

from backend.tutorial_tools import (
    INVALID_TOOL_ARGUMENTS,
    INVALID_TOOL_CALL,
    REQUEST_SCREEN_TOOL_NAME,
    UPDATE_PLAN_TOOL_NAME,
    TutorialToolCall,
    TutorialToolCallError,
    candidates_from_arguments,
    is_request_screen_call,
    is_update_plan_call,
    openai_tutorial_tool_definitions,
    parse_request_screen_reason,
    parse_update_plan_arguments,
)


def _update_plan_args(plan: list[dict]) -> str:
    return json.dumps({"plan_reasoning": "test", "plan": plan})


class TutorialToolDispatchTests(unittest.TestCase):
    def test_tool_names_partition(self) -> None:
        update_call = TutorialToolCall(name=UPDATE_PLAN_TOOL_NAME, arguments="{}")
        screen_call = TutorialToolCall(
            name=REQUEST_SCREEN_TOOL_NAME, arguments='{"reason": "x"}'
        )
        self.assertTrue(is_update_plan_call(update_call))
        self.assertFalse(is_request_screen_call(update_call))
        self.assertTrue(is_request_screen_call(screen_call))
        self.assertFalse(is_update_plan_call(screen_call))

    def test_openai_tool_definitions_expose_two_tools(self) -> None:
        defs = openai_tutorial_tool_definitions()
        names = {tool["name"] for tool in defs}
        self.assertEqual(names, {UPDATE_PLAN_TOOL_NAME, REQUEST_SCREEN_TOOL_NAME})

    def test_parse_request_screen_reason(self) -> None:
        call = TutorialToolCall(
            name=REQUEST_SCREEN_TOOL_NAME,
            arguments='{"reason": "verify the click landed"}',
        )
        self.assertEqual(parse_request_screen_reason(call), "verify the click landed")


class UpdatePlanParsingTests(unittest.TestCase):
    def test_parse_click_item(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "click",
                        "human_text": "Click New.",
                        "agent_description": "Green New button.",
                        "confidence": 0.9,
                        "refines_current": False,
                    }
                ]
            ),
        )
        args = parse_update_plan_arguments(call)
        candidates = candidates_from_arguments(args)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertFalse(candidate.refines_current)
        self.assertEqual(candidate.step_template.action.type, "click")
        self.assertEqual(
            candidate.step_template.action.target.description, "Green New button."
        )
        self.assertEqual(candidate.step_template.confidence, 0.9)

    def test_parse_type_item(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "type",
                        "human_text": "Type the repo name.",
                        "copiable_text": "context-demo",
                        "agent_description": "Repository name field.",
                        "confidence": 0.75,
                        "refines_current": False,
                    }
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        self.assertEqual(candidates[0].step_template.action.type, "type")
        self.assertEqual(candidates[0].step_template.action.text, "context-demo")

    def test_parse_scroll_item_infers_direction(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "scroll",
                        "human_text": "Scroll down to billing.",
                        "expected_end_state": "The Billing section is visible.",
                        "confidence": 0.7,
                        "refines_current": False,
                    }
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        self.assertEqual(candidates[0].step_template.action.direction, "down")

    def test_refines_current_passthrough(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "press_key",
                        "human_text": "Press Enter.",
                        "key": "Enter",
                        "confidence": 0.95,
                        "refines_current": True,
                    }
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        self.assertTrue(candidates[0].refines_current)

    def test_rejects_missing_required_field(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "type",
                        "human_text": "Type.",
                        # missing copiable_text + agent_description
                        "confidence": 0.8,
                        "refines_current": False,
                    }
                ]
            ),
        )
        with self.assertRaises(TutorialToolCallError) as error:
            parse_update_plan_arguments(call)
        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_blank_human_text(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "click",
                        "human_text": "   ",
                        "agent_description": "x",
                        "confidence": 0.9,
                        "refines_current": False,
                    }
                ]
            ),
        )
        with self.assertRaises(TutorialToolCallError) as error:
            parse_update_plan_arguments(call)
        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_wrong_tool_name(self) -> None:
        call = TutorialToolCall(name="tutorial_click", arguments="{}")
        with self.assertRaises(TutorialToolCallError) as error:
            parse_update_plan_arguments(call)
        self.assertEqual(error.exception.code, INVALID_TOOL_CALL)

    def test_low_confidence_step_requires_confirmation(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "kind": "press_key",
                        "human_text": "Press Tab.",
                        "key": "Tab",
                        "confidence": 0.4,
                        "refines_current": False,
                    }
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        self.assertTrue(candidates[0].step_template.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
