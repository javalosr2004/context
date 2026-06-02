from __future__ import annotations

import json
import unittest
from typing import Any

from backend.tutorial_tools import (
    ASK_USER_TOOL_NAME,
    INVALID_TOOL_ARGUMENTS,
    INVALID_TOOL_CALL,
    REQUEST_COMPLETION_TOOL_NAME,
    REQUEST_SCREEN_TOOL_NAME,
    UPDATE_PLAN_TOOL_NAME,
    TutorialToolCall,
    TutorialToolCallError,
    candidates_from_arguments,
    is_ask_user_call,
    is_request_completion_call,
    is_request_screen_call,
    is_update_plan_call,
    openai_tutorial_tool_definitions,
    parse_ask_user_arguments,
    parse_request_completion_reason,
    parse_request_screen_reason,
    parse_update_plan_arguments,
)


def _update_plan_args(plan: list[dict[str, Any]]) -> str:
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

    def test_openai_tool_definitions_expose_four_tools(self) -> None:
        defs = openai_tutorial_tool_definitions()
        names = {tool["name"] for tool in defs}
        self.assertEqual(
            names,
            {
                UPDATE_PLAN_TOOL_NAME,
                REQUEST_SCREEN_TOOL_NAME,
                REQUEST_COMPLETION_TOOL_NAME,
                ASK_USER_TOOL_NAME,
            },
        )

    def test_parse_request_screen_reason(self) -> None:
        call = TutorialToolCall(
            name=REQUEST_SCREEN_TOOL_NAME,
            arguments='{"reason": "verify the click landed"}',
        )
        self.assertEqual(parse_request_screen_reason(call), "verify the click landed")

    def test_request_completion_call_helpers(self) -> None:
        call = TutorialToolCall(
            name=REQUEST_COMPLETION_TOOL_NAME,
            arguments='{"reason": "Signup confirmation visible."}',
        )
        self.assertTrue(is_request_completion_call(call))
        self.assertFalse(is_request_completion_call(
            TutorialToolCall(name=UPDATE_PLAN_TOOL_NAME, arguments="{}")
        ))
        self.assertEqual(
            parse_request_completion_reason(call),
            "Signup confirmation visible.",
        )

    def test_parse_request_completion_rejects_empty_reason(self) -> None:
        call = TutorialToolCall(
            name=REQUEST_COMPLETION_TOOL_NAME,
            arguments='{"reason": ""}',
        )
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_request_completion_reason(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_ARGUMENTS)


def _click_payload(description: str = "Green New button.") -> dict[str, Any]:
    return {"kind": "click", "agent_description": description}


def _plan_item(
    *actions: dict[str, Any],
    human_text: str = "Do the thing.",
    confidence: float = 0.9,
    refines_current: bool = False,
) -> dict[str, Any]:
    return {
        "human_text": human_text,
        "confidence": confidence,
        "refines_current": refines_current,
        "actions": list(actions),
    }


class UpdatePlanParsingTests(unittest.TestCase):
    def test_parse_click_item(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [_plan_item(_click_payload(), human_text="Click New.")]
            ),
        )
        args = parse_update_plan_arguments(call)
        candidates = candidates_from_arguments(args)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertFalse(candidate.refines_current)
        actions = candidate.step_template.actions
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "click")
        self.assertEqual(actions[0].target.description, "Green New button.")
        self.assertTrue(actions[0].requires_confirmation)
        self.assertEqual(candidate.step_template.confidence, 0.9)

    def test_parse_multi_action_item(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    _plan_item(
                        {
                            "kind": "type",
                            "copiable_text": "context-demo",
                            "agent_description": "Repository name field.",
                        },
                        {"kind": "press_key", "key": "Enter"},
                        human_text="Name the repo and submit.",
                    )
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        actions = candidates[0].step_template.actions
        self.assertEqual([a.type for a in actions], ["type", "press_key"])
        self.assertEqual(actions[0].text, "context-demo")
        self.assertTrue(actions[0].requires_confirmation)
        self.assertFalse(actions[1].requires_confirmation)

    def test_parse_scroll_item_infers_direction(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    _plan_item(
                        {
                            "kind": "scroll",
                            "expected_end_state": "The Billing section is visible.",
                        },
                        human_text="Scroll down to billing.",
                        confidence=0.7,
                    )
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        self.assertEqual(candidates[0].step_template.actions[0].direction, "down")

    def test_refines_current_passthrough(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    _plan_item(
                        {"kind": "press_key", "key": "Enter"},
                        human_text="Press Enter.",
                        confidence=0.95,
                        refines_current=True,
                    )
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
                    _plan_item(
                        # missing copiable_text + agent_description
                        {"kind": "type"},
                        human_text="Type.",
                        confidence=0.8,
                    )
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
                [_plan_item(_click_payload("x"), human_text="   ")]
            ),
        )
        with self.assertRaises(TutorialToolCallError) as error:
            parse_update_plan_arguments(call)
        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_empty_actions_list(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    {
                        "human_text": "Nothing to do.",
                        "confidence": 0.9,
                        "refines_current": False,
                        "actions": [],
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

    def test_parse_user_choice_item(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    _plan_item(
                        {
                            "kind": "user_choice",
                            "prompt": "Type the username you want to use.",
                        },
                        human_text="Pick a username.",
                        confidence=0.8,
                    )
                ]
            ),
        )
        candidates = candidates_from_arguments(parse_update_plan_arguments(call))
        action = candidates[0].step_template.actions[0]
        self.assertEqual(action.type, "user_choice")
        self.assertEqual(action.prompt, "Type the username you want to use.")
        self.assertIsNone(action.target)
        self.assertTrue(action.requires_confirmation)

    def test_user_choice_without_prompt_is_rejected(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    _plan_item(
                        {"kind": "user_choice"},
                        human_text="Pick something.",
                        confidence=0.7,
                    )
                ]
            ),
        )
        with self.assertRaises(TutorialToolCallError) as error:
            parse_update_plan_arguments(call)
        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_confirm_action_kind_is_rejected(self) -> None:
        call = TutorialToolCall(
            name=UPDATE_PLAN_TOOL_NAME,
            arguments=_update_plan_args(
                [
                    _plan_item(
                        {"kind": "confirm"},
                        human_text="Check the page.",
                        confidence=0.6,
                    )
                ]
            ),
        )
        with self.assertRaises(TutorialToolCallError) as error:
            parse_update_plan_arguments(call)
        self.assertEqual(error.exception.code, INVALID_TOOL_ARGUMENTS)


class TutorialAskUserTests(unittest.TestCase):
    def _call(self, **kwargs: Any) -> TutorialToolCall:
        return TutorialToolCall(
            name=ASK_USER_TOOL_NAME,
            arguments=json.dumps(kwargs),
        )

    def test_is_ask_user_call_dispatch(self) -> None:
        ask_call = self._call(reason="ambiguous goal", questions=[])
        self.assertTrue(is_ask_user_call(ask_call))
        self.assertFalse(
            is_ask_user_call(
                TutorialToolCall(name=UPDATE_PLAN_TOOL_NAME, arguments="{}")
            )
        )

    def test_parse_options_question(self) -> None:
        call = self._call(
            reason="Which email client are you using?",
            questions=[
                {
                    "question_id": "client",
                    "question": "Which email client?",
                    "response_mode": "options",
                    "options": ["Mail", "Gmail", "Outlook"],
                }
            ],
        )
        args = parse_ask_user_arguments(call)
        self.assertEqual(len(args.questions), 1)
        self.assertEqual(args.questions[0].response_mode, "options")
        self.assertEqual(args.questions[0].options, ["Mail", "Gmail", "Outlook"])

    def test_parse_free_text_question(self) -> None:
        call = self._call(
            reason="Need the user's preferred name.",
            questions=[
                {
                    "question_id": "name",
                    "question": "What name should appear on the account?",
                    "response_mode": "free_text",
                    "options": [],
                }
            ],
        )
        args = parse_ask_user_arguments(call)
        self.assertEqual(args.questions[0].response_mode, "free_text")
        self.assertEqual(args.questions[0].options, [])

    def test_options_mode_requires_two_options(self) -> None:
        call = self._call(
            reason="x",
            questions=[
                {
                    "question_id": "q",
                    "question": "Which?",
                    "response_mode": "options",
                    "options": ["only-one"],
                }
            ],
        )
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_ask_user_arguments(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_free_text_mode_rejects_options(self) -> None:
        call = self._call(
            reason="x",
            questions=[
                {
                    "question_id": "q",
                    "question": "What?",
                    "response_mode": "free_text",
                    "options": ["nope"],
                }
            ],
        )
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_ask_user_arguments(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_duplicate_question_ids(self) -> None:
        call = self._call(
            reason="x",
            questions=[
                {
                    "question_id": "dup",
                    "question": "First?",
                    "response_mode": "options",
                    "options": ["A", "B"],
                },
                {
                    "question_id": "dup",
                    "question": "Second?",
                    "response_mode": "options",
                    "options": ["A", "B"],
                },
            ],
        )
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_ask_user_arguments(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_more_than_four_questions(self) -> None:
        call = self._call(
            reason="x",
            questions=[
                {
                    "question_id": f"q{i}",
                    "question": f"Q{i}?",
                    "response_mode": "options",
                    "options": ["A", "B"],
                }
                for i in range(5)
            ],
        )
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_ask_user_arguments(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_empty_questions(self) -> None:
        call = self._call(reason="x", questions=[])
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_ask_user_arguments(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_ARGUMENTS)

    def test_rejects_wrong_tool_name(self) -> None:
        call = TutorialToolCall(name=UPDATE_PLAN_TOOL_NAME, arguments="{}")
        with self.assertRaises(TutorialToolCallError) as ctx:
            parse_ask_user_arguments(call)
        self.assertEqual(ctx.exception.code, INVALID_TOOL_CALL)


if __name__ == "__main__":
    unittest.main()
