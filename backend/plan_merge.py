"""Pure merge logic for `tutorial_update_plan`.

The session owns the plan as ``frozen_prefix + live_tail``. Each turn the
model proposes a fresh full tail; this module computes the new plan and
validates the model's contract.

Identity for the last frozen step is carried across turns via a single
one-bit signal: if the first tail candidate has ``refines_current=True``,
the merged step inherits ``frozen_prefix_ids[-1]``'s ``step_id`` (and
therefore its ``attempts_without_progress`` counter and UI cursor
identity). Otherwise the entire frozen prefix is retained as-is and the
new tail is appended after it with fresh ``step_id``s.

Contract enforced here:
    - ``frozen_prefix_ids`` MUST be a contiguous prefix of the current plan.
    - ``refines_current=True`` is only legal on ``new_tail[0]``.
    - ``refines_current=True`` requires a non-empty ``frozen_prefix_ids``
      (there must be a step to refine).
    - Each materialized step MUST pass ``validate_step_semantics``.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.tutorial_schema import TutorialStep, validate_step_semantics


STEP_ID_PREFIX = "step_"


class PlanMergeError(ValueError):
    pass


@dataclass(frozen=True)
class TailCandidate:
    """A model-proposed tail item, pre-materialized except for ``step_id``.

    ``step_template.step_id`` is ignored by the merger; the real id is
    either inherited from ``frozen_prefix_ids[-1]`` (when
    ``refines_current`` is true on tail[0]) or freshly minted from the
    counter.
    """

    refines_current: bool
    step_template: TutorialStep


@dataclass(frozen=True)
class PlanMergeResult:
    plan_steps: list[TutorialStep]
    step_counter: int


def merge_plan_tail(
    current_plan_steps: list[TutorialStep],
    frozen_prefix_ids: list[str],
    new_tail: list[TailCandidate],
    step_counter: int,
) -> PlanMergeResult:
    _require_contiguous_prefix(current_plan_steps, frozen_prefix_ids)
    _validate_refines(new_tail, frozen_prefix_ids)

    refines = bool(new_tail and new_tail[0].refines_current)
    # When refining, the last frozen step is dropped from the retained
    # prefix because the merged tail[0] takes its slot (with the same
    # step_id).
    retained_count = len(frozen_prefix_ids) - 1 if refines else len(frozen_prefix_ids)
    inherited_step_id = frozen_prefix_ids[-1] if refines else None
    new_steps: list[TutorialStep] = list(current_plan_steps[:retained_count])
    next_step_counter = step_counter

    for index, candidate in enumerate(new_tail):
        if index == 0 and refines:
            assert inherited_step_id is not None  # guaranteed by _validate_refines
            step_id = inherited_step_id
        else:
            next_step_counter += 1
            step_id = f"{STEP_ID_PREFIX}{next_step_counter:03d}"
        merged = candidate.step_template.model_copy(update={"step_id": step_id})
        validate_step_semantics(merged)
        new_steps.append(merged)

    return PlanMergeResult(plan_steps=new_steps, step_counter=next_step_counter)


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


def _validate_refines(
    new_tail: list[TailCandidate],
    frozen_prefix_ids: list[str],
) -> None:
    refining = [i for i, c in enumerate(new_tail) if c.refines_current]
    if not refining:
        return
    if refining != [0]:
        raise PlanMergeError(
            "refines_current=true is only allowed on the first tail item; "
            f"found on indices {refining}."
        )
    if not frozen_prefix_ids:
        raise PlanMergeError(
            "refines_current=true requires a non-empty frozen prefix; "
            "there is no prior step to refine."
        )
