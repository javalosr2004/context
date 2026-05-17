from __future__ import annotations

import unittest

from backend.plan_merge import (
    PlanMergeError,
    TailCandidate,
    merge_plan_tail,
)
from backend.tutorial_schema import (
    ActionTarget,
    TutorialAction,
    TutorialStep,
)


def make_step(
    step_id: str,
    *,
    action_type: str = "click",
    instruction: str | None = None,
    confidence: float = 0.85,
) -> TutorialStep:
    if action_type == "click":
        action = TutorialAction(
            type="click",
            target=ActionTarget(kind="element", description="something"),
        )
    elif action_type == "type":
        action = TutorialAction(
            type="type",
            target=ActionTarget(kind="element", description="a field"),
            text="hello",
        )
    elif action_type == "press_key":
        action = TutorialAction(type="press_key", key="Enter")
    elif action_type == "wait":
        action = TutorialAction(type="wait", duration_ms=500)
    elif action_type == "scroll":
        action = TutorialAction(
            type="scroll",
            target=ActionTarget(kind="screen", description="the bottom"),
            direction="down",
        )
    elif action_type == "confirm":
        action = TutorialAction(type="confirm")
    else:
        raise ValueError(f"unsupported action_type {action_type!r}")

    return TutorialStep(
        step_id=step_id,
        instruction=instruction or f"do {action_type}",
        action=action,
        confidence=confidence,
        requires_confirmation=True,
    )


def candidate(template: TutorialStep, *, refines_current: bool = False) -> TailCandidate:
    return TailCandidate(refines_current=refines_current, step_template=template)


class MergePlanTailTests(unittest.TestCase):
    def test_append_to_empty_plan(self) -> None:
        result = merge_plan_tail(
            current_plan_steps=[],
            frozen_prefix_ids=[],
            awaiting_step_id=None,
            new_tail=[
                candidate(make_step("ignored", action_type="click")),
                candidate(make_step("ignored", action_type="type")),
            ],
            step_counter=0,
        )

        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002"],
        )
        self.assertEqual(result.step_counter, 2)

    def test_full_rewrite_after_one_completed_step(self) -> None:
        existing = [
            make_step("step_001", action_type="click"),
            make_step("step_002", action_type="type"),  # will be replaced
        ]

        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001"],
            awaiting_step_id=None,
            new_tail=[
                candidate(make_step("ignored", action_type="scroll")),
                candidate(make_step("ignored", action_type="confirm")),
            ],
            step_counter=2,
        )

        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_003", "step_004"],
        )

    def test_refines_current_preserves_awaiting_step_id(self) -> None:
        existing = [
            make_step("step_001", action_type="click"),
            make_step("step_002", action_type="type"),  # awaiting
            make_step("step_003", action_type="scroll"),  # old tail
        ]

        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001", "step_002"],
            awaiting_step_id="step_002",
            new_tail=[
                candidate(
                    make_step("ignored", action_type="type", confidence=0.4),
                    refines_current=True,
                ),
                candidate(make_step("ignored", action_type="press_key")),
            ],
            step_counter=3,
        )

        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002", "step_004"],
        )
        # Refined step adopted new payload (confidence 0.4) under same id.
        refined = result.plan_steps[1]
        self.assertEqual(refined.step_id, "step_002")
        self.assertAlmostEqual(refined.confidence, 0.4)
        self.assertEqual(result.step_counter, 4)

    def test_refines_current_false_preserves_awaiting_step(self) -> None:
        existing = [
            make_step("step_001"),
            make_step("step_002"),
        ]
        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001", "step_002"],
            awaiting_step_id="step_002",
            new_tail=[candidate(make_step("ignored", action_type="scroll"))],
            step_counter=2,
        )
        # Awaiting step retained; new tail appended after it.
        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002", "step_003"],
        )

    def test_refines_current_without_awaiting_is_rejected(self) -> None:
        with self.assertRaises(PlanMergeError) as cm:
            merge_plan_tail(
                current_plan_steps=[],
                frozen_prefix_ids=[],
                awaiting_step_id=None,
                new_tail=[
                    candidate(make_step("ignored"), refines_current=True),
                ],
                step_counter=0,
            )
        self.assertIn("awaiting", str(cm.exception))

    def test_refines_current_on_non_first_item_is_rejected(self) -> None:
        existing = [make_step("step_001")]
        with self.assertRaises(PlanMergeError) as cm:
            merge_plan_tail(
                current_plan_steps=existing,
                frozen_prefix_ids=["step_001"],
                awaiting_step_id="step_001",
                new_tail=[
                    candidate(make_step("ignored")),
                    candidate(make_step("ignored"), refines_current=True),
                ],
                step_counter=1,
            )
        self.assertIn("first tail item", str(cm.exception))

    def test_non_contiguous_frozen_prefix_is_rejected(self) -> None:
        existing = [
            make_step("step_001"),
            make_step("step_002"),
            make_step("step_003"),
        ]
        with self.assertRaises(PlanMergeError):
            merge_plan_tail(
                current_plan_steps=existing,
                frozen_prefix_ids=["step_001", "step_003"],  # skips step_002
                awaiting_step_id=None,
                new_tail=[candidate(make_step("ignored"))],
                step_counter=3,
            )

    def test_step_counter_monotonic_across_rejection(self) -> None:
        # Simulates: model proposed step_001..step_003; user rejected step_002.
        # New tail issues steps starting at step_004, never reusing 002 or 003.
        existing = [make_step("step_001")]
        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001"],
            awaiting_step_id=None,
            new_tail=[
                candidate(make_step("ignored")),
                candidate(make_step("ignored")),
            ],
            step_counter=3,  # 3 IDs already minted
        )
        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_004", "step_005"],
        )

    def test_invalid_step_semantics_propagates(self) -> None:
        bad = TutorialStep(
            step_id="ignored",
            instruction="bad",
            action=TutorialAction(type="type"),  # missing text + target
            confidence=0.9,
            requires_confirmation=True,
        )
        with self.assertRaises(ValueError):
            merge_plan_tail(
                current_plan_steps=[],
                frozen_prefix_ids=[],
                awaiting_step_id=None,
                new_tail=[candidate(bad)],
                step_counter=0,
            )

    def test_large_plan_round_trips(self) -> None:
        tail = [candidate(make_step("ignored")) for _ in range(60)]
        result = merge_plan_tail(
            current_plan_steps=[],
            frozen_prefix_ids=[],
            awaiting_step_id=None,
            new_tail=tail,
            step_counter=0,
        )
        self.assertEqual(len(result.plan_steps), 60)


if __name__ == "__main__":
    unittest.main()
