from __future__ import annotations

import json
import unittest
from typing import Any

from backend.plan_arg_stream import IncrementalPlanPreview, PlanStepPreview


def _click_item(human_text: str, description: str, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "refines_current": False,
        "human_text": human_text,
        "confidence": confidence,
        "expected_screen_summary": None,
        "actions": [
            {
                "kind": "click",
                "requires_confirmation": True,
                "agent_description": description,
            }
        ],
    }


def _args(plan: list[dict[str, Any]], **extra: Any) -> str:
    payload = {"plan_reasoning": "why", "abandon_awaiting": False, "plan": plan}
    payload.update(extra)
    return json.dumps(payload)


def _feed_in_chunks(raw: str, size: int) -> list[PlanStepPreview]:
    preview = IncrementalPlanPreview()
    out: list[PlanStepPreview] = []
    for start in range(0, len(raw), size):
        out.extend(preview.feed(raw[start : start + size]))
    return out


class IncrementalPlanPreviewTests(unittest.TestCase):
    def test_yields_each_item_once_in_order(self) -> None:
        raw = _args(
            [
                _click_item("Open Settings.", "the Settings button", 0.95),
                _click_item("Click Billing.", "the Billing row", 0.6),
                _click_item("Press Save.", "the Save button", 0.3),
            ]
        )
        previews = IncrementalPlanPreview().feed(raw)
        self.assertEqual(
            [(p.index, p.instruction, p.confidence) for p in previews],
            [
                (0, "Open Settings.", 0.95),
                (1, "Click Billing.", 0.6),
                (2, "Press Save.", 0.3),
            ],
        )

    def test_byte_boundary_splits_are_stable(self) -> None:
        raw = _args(
            [
                _click_item("Open Settings.", "the Settings button", 0.95),
                _click_item("Click Billing.", "the Billing row", 0.6),
            ]
        )
        expected = [
            (0, "Open Settings.", 0.95),
            (1, "Click Billing.", 0.6),
        ]
        # Split at every possible chunk size; result must be identical and
        # each item must surface exactly once.
        for size in range(1, len(raw) + 1):
            previews = _feed_in_chunks(raw, size)
            self.assertEqual(
                [(p.index, p.instruction, p.confidence) for p in previews],
                expected,
                msg=f"chunk size {size}",
            )

    def test_braces_and_quotes_inside_strings_do_not_miscount(self) -> None:
        raw = _args(
            [
                _click_item(
                    'Type the literal {"weird": "value"} into the box.',
                    'the field labelled "Config {json}"',
                    0.8,
                ),
                _click_item("Next step.", "the Next button", 0.7),
            ]
        )
        for size in (1, 3, 7, len(raw)):
            previews = _feed_in_chunks(raw, size)
            self.assertEqual(len(previews), 2, msg=f"chunk size {size}")
            self.assertEqual(previews[0].index, 0)
            self.assertIn("weird", previews[0].instruction)
            self.assertEqual(previews[1].instruction, "Next step.")

    def test_escaped_backslash_before_quote(self) -> None:
        instruction = 'Path is C:\\temp\\ and a quote \\" here'
        raw = _args([_click_item(instruction, "the folder field", 0.5)])
        previews = _feed_in_chunks(raw, 2)
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0].instruction, instruction)

    def test_truncated_tail_yields_valid_prefix_without_raising(self) -> None:
        raw = _args(
            [
                _click_item("First.", "first", 0.9),
                _click_item("Second.", "second", 0.8),
            ]
        )
        # Cut mid-way through the second item.
        cut = raw.index("Second")
        preview = IncrementalPlanPreview()
        previews = preview.feed(raw[:cut])
        self.assertEqual([p.instruction for p in previews], ["First."])
        # Garbage continuation must not raise.
        self.assertEqual(preview.feed("!!! not json"), [])

    def test_plan_field_not_last(self) -> None:
        # plan_reasoning mentions "plan" and "[" inside a string; the array
        # is the first STRUCTURAL bracket at depth 1 regardless of order.
        raw = json.dumps(
            {
                "plan_reasoning": "my plan is a [list] of {steps}",
                "plan": [_click_item("Only step.", "the button", 0.9)],
                "abandon_awaiting": False,
            }
        )
        previews = _feed_in_chunks(raw, 4)
        self.assertEqual([p.instruction for p in previews], ["Only step."])

    def test_reset_starts_fresh(self) -> None:
        preview = IncrementalPlanPreview()
        first = preview.feed(_args([_click_item("A.", "a", 0.9)]))
        self.assertEqual([p.instruction for p in first], ["A."])
        preview.reset()
        second = preview.feed(_args([_click_item("B.", "b", 0.8)]))
        self.assertEqual([(p.index, p.instruction) for p in second], [(0, "B.")])

    def test_multi_action_item_only_completes_at_outer_close(self) -> None:
        item = {
            "refines_current": False,
            "human_text": "Fill the form and submit.",
            "confidence": 0.85,
            "expected_screen_summary": "the signup form",
            "actions": [
                {
                    "kind": "type",
                    "requires_confirmation": True,
                    "copiable_text": "hello",
                    "agent_description": "the name field",
                },
                {"kind": "press_key", "requires_confirmation": False, "key": "Enter"},
            ],
        }
        raw = _args([item, _click_item("Done.", "the done button", 0.5)])
        previews = _feed_in_chunks(raw, 5)
        self.assertEqual(
            [p.instruction for p in previews],
            ["Fill the form and submit.", "Done."],
        )

    def test_empty_and_noise_deltas(self) -> None:
        preview = IncrementalPlanPreview()
        self.assertEqual(preview.feed(""), [])
        self.assertEqual(preview.feed('{"plan_reasoning":"x",'), [])
        self.assertEqual(preview.feed(""), [])


if __name__ == "__main__":
    unittest.main()
