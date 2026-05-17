"""Pure merge logic for `tutorial_update_plan`.

The session owns the plan as ``frozen_prefix + live_tail``. Each turn the
model proposes a fresh full tail; this module computes the new plan,
validates the model's contract, and assigns stable identifiers.

Contract enforced here (so the session loop stays simple):
    - ``frozen_prefix_ids`` MUST be a contiguous prefix of the current plan.
    - A tail candidate that echoes a ``step_handle`` MUST reference a step
      that existed in the previous tail and is NOT in the frozen prefix.
    - No handle may appear twice in one new tail.
    - Each materialized step MUST pass ``validate_step_semantics``.

Handles are how the model says "this is the same logical step as last
turn." The merge preserves the kept step's ``step_id`` and handle, but
adopts the new payload from the candidate template — so a handle echo
without payload changes is a no-op, and a handle echo with new payload is
in-place refinement.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.tutorial_schema import TutorialStep, validate_step_semantics


HANDLE_PREFIX = "h_"
STEP_ID_PREFIX = "step_"


class PlanMergeError(ValueError):
    pass


@dataclass(frozen=True)
class TailCandidate:
    """A model-proposed tail item, pre-materialized except for ``step_id``.

    ``step_template.step_id`` is ignored by the merger; the real id comes
    from either the kept handle's prior step or a freshly minted counter.
    """

    step_handle: str | None
    step_template: TutorialStep


@dataclass(frozen=True)
class PlanMergeResult:
    plan_steps: list[TutorialStep]
    handle_index: dict[str, TutorialStep]
    step_counter: int
    handle_counter: int


def merge_plan_tail(
    current_plan_steps: list[TutorialStep],
    frozen_prefix_ids: list[str],
    prior_handle_index: dict[str, TutorialStep],
    new_tail: list[TailCandidate],
    step_counter: int,
    handle_counter: int,
) -> PlanMergeResult:
    _require_contiguous_prefix(current_plan_steps, frozen_prefix_ids)
    _validate_handles(new_tail, prior_handle_index, frozen_prefix_ids)

    frozen_steps = list(current_plan_steps[: len(frozen_prefix_ids)])
    new_steps: list[TutorialStep] = list(frozen_steps)
    new_handle_index: dict[str, TutorialStep] = {}
    next_step_counter = step_counter
    next_handle_counter = handle_counter

    for candidate in new_tail:
        if candidate.step_handle is not None:
            kept = prior_handle_index[candidate.step_handle]
            step_id = kept.step_id
            handle = candidate.step_handle
        else:
            next_step_counter += 1
            step_id = f"{STEP_ID_PREFIX}{next_step_counter:03d}"
            next_handle_counter += 1
            handle = f"{HANDLE_PREFIX}{next_handle_counter:03d}"

        merged = candidate.step_template.model_copy(update={"step_id": step_id})
        validate_step_semantics(merged)
        new_steps.append(merged)
        new_handle_index[handle] = merged

    return PlanMergeResult(
        plan_steps=new_steps,
        handle_index=new_handle_index,
        step_counter=next_step_counter,
        handle_counter=next_handle_counter,
    )


def assign_initial_handles(
    plan_steps: list[TutorialStep],
    handle_counter: int,
) -> tuple[dict[str, TutorialStep], int]:
    """Mint handles for steps that don't yet have one (used on first emit)."""
    handle_index: dict[str, TutorialStep] = {}
    counter = handle_counter
    for step in plan_steps:
        counter += 1
        handle_index[f"{HANDLE_PREFIX}{counter:03d}"] = step
    return handle_index, counter


def _require_contiguous_prefix(
    current_plan_steps: list[TutorialStep],
    frozen_prefix_ids: list[str],
) -> None:
    if len(frozen_prefix_ids) > len(current_plan_steps):
        raise PlanMergeError(
            "frozen_prefix_ids is longer than the current plan; "
            f"prefix={len(frozen_prefix_ids)}, plan={len(current_plan_steps)}."
        )
    for index, frozen_id in enumerate(frozen_prefix_ids):
        actual_id = current_plan_steps[index].step_id
        if actual_id != frozen_id:
            raise PlanMergeError(
                f"frozen_prefix_ids[{index}]={frozen_id!r} does not match "
                f"plan step at that index ({actual_id!r}); the prefix must "
                "be contiguous from the start of the plan."
            )


def _validate_handles(
    new_tail: list[TailCandidate],
    prior_handle_index: dict[str, TutorialStep],
    frozen_prefix_ids: list[str],
) -> None:
    frozen_set = set(frozen_prefix_ids)
    seen: set[str] = set()
    for candidate in new_tail:
        handle = candidate.step_handle
        if handle is None:
            continue
        if handle in seen:
            raise PlanMergeError(
                f"Duplicate step_handle {handle!r} in new tail; each handle "
                "may appear at most once."
            )
        seen.add(handle)
        if handle not in prior_handle_index:
            raise PlanMergeError(
                f"Unknown step_handle {handle!r}; only handles from the "
                "previous turn's tail may be echoed."
            )
        kept_step_id = prior_handle_index[handle].step_id
        if kept_step_id in frozen_set:
            raise PlanMergeError(
                f"step_handle {handle!r} references step {kept_step_id!r} "
                "which is in the frozen prefix and cannot be modified. "
                "Omit it; the prefix is preserved automatically."
            )
