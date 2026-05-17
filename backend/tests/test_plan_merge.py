from __future__ import annotations

import unittest

from backend.plan_merge import (
    PlanMergeError,
    TailCandidate,
    assign_initial_handles,
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


def candidate(handle: str | None, template: TutorialStep) -> TailCandidate:
    return TailCandidate(step_handle=handle, step_template=template)


class MergePlanTailTests(unittest.TestCase):
    def test_append_to_empty_plan(self) -> None:
        result = merge_plan_tail(
            current_plan_steps=[],
            frozen_prefix_ids=[],
            prior_handle_index={},
            new_tail=[
                candidate(None, make_step("ignored", action_type="click")),
                candidate(None, make_step("ignored", action_type="type")),
            ],
            step_counter=0,
            handle_counter=0,
        )

        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002"],
        )
        self.assertEqual(set(result.handle_index.keys()), {"h_001", "h_002"})
        self.assertEqual(result.step_counter, 2)
        self.assertEqual(result.handle_counter, 2)

    def test_full_rewrite_after_one_completed_step(self) -> None:
        existing = [
            make_step("step_001", action_type="click"),
            make_step("step_002", action_type="type"),  # will be replaced
        ]
        prior_handles = {"h_007": existing[1]}

        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001"],
            prior_handle_index=prior_handles,
            new_tail=[
                candidate(None, make_step("ignored", action_type="scroll")),
                candidate(None, make_step("ignored", action_type="confirm")),
            ],
            step_counter=2,
            handle_counter=7,
        )

        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_003", "step_004"],
        )
        self.assertEqual(set(result.handle_index.keys()), {"h_008", "h_009"})

    def test_keep_handle_preserves_step_id_and_handle(self) -> None:
        existing = [
            make_step("step_001", action_type="click"),
            make_step("step_002", action_type="type"),
        ]
        prior_handles = {"h_010": existing[1]}

        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001"],
            prior_handle_index=prior_handles,
            new_tail=[
                candidate(
                    "h_010",
                    make_step("ignored", action_type="type", confidence=0.4),
                ),
                candidate(None, make_step("ignored", action_type="press_key")),
            ],
            step_counter=2,
            handle_counter=10,
        )

        # Kept step keeps id step_002; new step mints step_003.
        self.assertEqual(
            [s.step_id for s in result.plan_steps],
            ["step_001", "step_002", "step_003"],
        )
        # Kept handle reused; new handle minted from h_011.
        self.assertIn("h_010", result.handle_index)
        self.assertIn("h_011", result.handle_index)
        # In-place refinement: confidence updated from template payload.
        self.assertAlmostEqual(result.handle_index["h_010"].confidence, 0.4)

    def test_modifying_frozen_step_via_handle_is_rejected(self) -> None:
        existing = [make_step("step_001", action_type="click")]
        prior_handles = {"h_001": existing[0]}

        with self.assertRaises(PlanMergeError) as cm:
            merge_plan_tail(
                current_plan_steps=existing,
                frozen_prefix_ids=["step_001"],
                prior_handle_index=prior_handles,
                new_tail=[candidate("h_001", make_step("ignored"))],
                step_counter=1,
                handle_counter=1,
            )
        self.assertIn("frozen prefix", str(cm.exception))

    def test_duplicate_handle_is_rejected(self) -> None:
        existing = [
            make_step("step_001", action_type="click"),
            make_step("step_002", action_type="type"),
        ]
        prior_handles = {"h_005": existing[1]}

        with self.assertRaises(PlanMergeError) as cm:
            merge_plan_tail(
                current_plan_steps=existing,
                frozen_prefix_ids=["step_001"],
                prior_handle_index=prior_handles,
                new_tail=[
                    candidate("h_005", make_step("ignored", action_type="type")),
                    candidate("h_005", make_step("ignored", action_type="type")),
                ],
                step_counter=2,
                handle_counter=5,
            )
        self.assertIn("Duplicate", str(cm.exception))

    def test_unknown_handle_is_rejected(self) -> None:
        with self.assertRaises(PlanMergeError) as cm:
            merge_plan_tail(
                current_plan_steps=[make_step("step_001")],
                frozen_prefix_ids=["step_001"],
                prior_handle_index={},
                new_tail=[candidate("h_999", make_step("ignored"))],
                step_counter=1,
                handle_counter=0,
            )
        self.assertIn("Unknown", str(cm.exception))

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
                prior_handle_index={},
                new_tail=[candidate(None, make_step("ignored"))],
                step_counter=3,
                handle_counter=0,
            )

    def test_step_counter_monotonic_across_rejection(self) -> None:
        # Simulates: model proposed step_001..step_003; user rejected step_002.
        # New tail issues steps starting at step_004, never reusing 002 or 003.
        existing = [make_step("step_001")]
        result = merge_plan_tail(
            current_plan_steps=existing,
            frozen_prefix_ids=["step_001"],
            prior_handle_index={},
            new_tail=[
                candidate(None, make_step("ignored")),
                candidate(None, make_step("ignored")),
            ],
            step_counter=3,  # 3 IDs already minted
            handle_counter=3,
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
                prior_handle_index={},
                new_tail=[candidate(None, bad)],
                step_counter=0,
                handle_counter=0,
            )

    def test_large_plan_round_trips(self) -> None:
        tail = [candidate(None, make_step("ignored")) for _ in range(60)]
        result = merge_plan_tail(
            current_plan_steps=[],
            frozen_prefix_ids=[],
            prior_handle_index={},
            new_tail=tail,
            step_counter=0,
            handle_counter=0,
        )
        self.assertEqual(len(result.plan_steps), 60)
        self.assertEqual(len(result.handle_index), 60)

    def test_awaiting_step_in_prefix_cannot_be_rewritten(self) -> None:
        # awaiting step_002 is in the frozen prefix; model tries to rewrite it.
        existing = [
            make_step("step_001"),
            make_step("step_002"),
        ]
        prior_handles = {"h_002": existing[1]}
        with self.assertRaises(PlanMergeError):
            merge_plan_tail(
                current_plan_steps=existing,
                frozen_prefix_ids=["step_001", "step_002"],
                prior_handle_index=prior_handles,
                new_tail=[candidate("h_002", make_step("ignored"))],
                step_counter=2,
                handle_counter=2,
            )


class AssignInitialHandlesTests(unittest.TestCase):
    def test_mints_handles_in_order(self) -> None:
        steps = [make_step("step_001"), make_step("step_002")]
        index, counter = assign_initial_handles(steps, handle_counter=0)
        self.assertEqual(counter, 2)
        self.assertEqual(set(index.keys()), {"h_001", "h_002"})
        self.assertIs(index["h_001"], steps[0])
        self.assertIs(index["h_002"], steps[1])


if __name__ == "__main__":
    unittest.main()
