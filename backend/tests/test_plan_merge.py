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


def make_action(action_type: str) -> TutorialAction:
    if action_type == "click":
        return TutorialAction(
            type="click",
            target=ActionTarget(kind="element", description="something"),
            requires_confirmation=True,
        )
    if action_type == "type":
        return TutorialAction(
            type="type",
            target=ActionTarget(kind="element", description="a field"),
            text="hello",
            requires_confirmation=True,
        )
    if action_type == "press_key":
        return TutorialAction(
            type="press_key", key="Enter", requires_confirmation=False
        )
    if action_type == "wait":
        return TutorialAction(
            type="wait", duration_ms=500, requires_confirmation=False
        )
    if action_type == "scroll":
        return TutorialAction(
            type="scroll",
            target=ActionTarget(kind="screen", description="the bottom"),
            direction="down",
            requires_confirmation=True,
        )
    raise ValueError(f"unsupported action_type {action_type!r}")


def make_step(
    step_id: str,
    *,
    action_type: str = "click",
    confidence: float = 0.9,
    instruction: str | None = None,
    actions: list[TutorialAction] | None = None,
) -> TutorialStep:
    return TutorialStep(
        step_id=step_id,
        instruction=instruction or f"do {action_type}",
        actions=actions if actions is not None else [make_action(action_type)],
        confidence=confidence,
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
                candidate(make_step("ignored", action_type="wait")),
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
        refined = result.plan_steps[1]
        self.assertEqual(refined.step_id, "step_002")
        self.assertAlmostEqual(refined.confidence, 0.4)
        self.assertEqual(result.step_counter, 4)

    def test_refines_current_false_appends_after_awaiting(self) -> None:
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
        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002", "step_003"],
        )

    def test_refines_current_without_awaiting_downgrades_to_append(self) -> None:
        # No awaiting step → refines_current is silently dropped. The
        # completed step is NOT rewritten; the new step is appended with a
        # fresh id (even if the human_text looks duplicative).
        existing = [
            make_step("step_001", action_type="click"),
            make_step("step_002", action_type="type", confidence=0.9),
        ]
        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001", "step_002"],
            awaiting_step_id=None,
            new_tail=[
                candidate(
                    make_step("ignored", action_type="type", confidence=0.3),
                    refines_current=True,
                ),
            ],
            step_counter=2,
        )
        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002", "step_003"],
        )
        # step_002 is untouched (still confidence 0.9).
        self.assertAlmostEqual(result.plan_steps[1].confidence, 0.9)
        # The new step inherited the refined payload.
        self.assertAlmostEqual(result.plan_steps[2].confidence, 0.3)

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
        existing = [make_step("step_001")]
        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001"],
            awaiting_step_id=None,
            new_tail=[
                candidate(make_step("ignored")),
                candidate(make_step("ignored")),
            ],
            step_counter=3,
        )
        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_004", "step_005"],
        )

    def test_invalid_step_semantics_propagates(self) -> None:
        bad = TutorialStep(
            step_id="ignored",
            instruction="bad",
            actions=[TutorialAction(type="type", requires_confirmation=True)],
            confidence=0.9,
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
