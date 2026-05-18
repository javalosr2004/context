"""Pure merge logic for `tutorial_update_plan`.

The session owns the plan as ``frozen_prefix + live_tail``. Each turn the
model proposes a fresh full tail; this module computes the new plan and
validates the model's contract.

Identity for the currently-awaiting step is carried across turns via a
single one-bit signal: if the first tail candidate has
``refines_current=True`` AND the awaiting step is the last entry in
``frozen_prefix_ids``, the merged step inherits the awaiting step's
``step_id`` (and therefore its ``attempts_without_progress`` counter and
UI cursor identity). Otherwise ``refines_current`` is silently dropped
and ``new_tail`` is appended after the entire frozen prefix with fresh
``step_id``s — a completed step is never rewritten.

Contract enforced here:
    - ``frozen_prefix_ids`` MUST be a contiguous prefix of the current plan.
    - ``refines_current=True`` is only legal on ``new_tail[0]``.
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
    either inherited from the awaiting step (when ``refines_current`` is
    true on tail[0] and the awaiting step is the last frozen entry) or
    freshly minted from the counter.
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
    awaiting_step_id: str | None,
    new_tail: list[TailCandidate],
    step_counter: int,
    abandon_awaiting: bool = False,
) -> PlanMergeResult:
    _require_contiguous_prefix(current_plan_steps, frozen_prefix_ids)
    _validate_refines_position(new_tail)

    if abandon_awaiting:
        if new_tail and new_tail[0].refines_current:
            raise PlanMergeError(
                "abandon_awaiting=true is mutually exclusive with "
                "refines_current=true on the first tail item."
            )
        if awaiting_step_id is None:
            raise PlanMergeError(
                "abandon_awaiting=true requires a live awaiting step."
            )
        if not frozen_prefix_ids or frozen_prefix_ids[-1] != awaiting_step_id:
            raise PlanMergeError(
                "abandon_awaiting=true requires the awaiting step to be the "
                "last frozen prefix entry."
            )

    # Honor refines_current only when there's a live awaiting step at the
    # tail of the frozen prefix. Otherwise drop the bit and append — never
    # rewrite a completed step.
    refines = (
        bool(new_tail)
        and new_tail[0].refines_current
        and awaiting_step_id is not None
        and bool(frozen_prefix_ids)
        and frozen_prefix_ids[-1] == awaiting_step_id
        and not abandon_awaiting
    )
    if abandon_awaiting:
        retained_count = len(frozen_prefix_ids) - 1
    else:
        retained_count = len(frozen_prefix_ids) - 1 if refines else len(frozen_prefix_ids)
    new_steps: list[TutorialStep] = list(current_plan_steps[:retained_count])
    next_step_counter = step_counter

    for index, candidate in enumerate(new_tail):
        if index == 0 and refines:
            assert awaiting_step_id is not None
            step_id = awaiting_step_id
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


def _validate_refines_position(new_tail: list[TailCandidate]) -> None:
    refining = [i for i, c in enumerate(new_tail) if c.refines_current]
    if refining and refining != [0]:
        raise PlanMergeError(
            "refines_current=true is only allowed on the first tail item; "
            f"found on indices {refining}."
        )
