# remove-spaghetti

Running list of dead code, redundant scaffolding, and "left in for one commit"
artifacts to prune in a follow-up. Each entry: what to remove, where it lives,
and why it's still around today.

## Parallel instruction verifier (superseded by strict gate)

**Files:** `backend/tutorial_session.py`

After the strict-gate change (commit `7717c446`), the planner is gated by a
synchronous verifier call in `_plan_or_gate`. The original parallel verifier
(spawned from `_await_step`, racing user input) is no longer fired but the
scaffolding is still in place.

To remove:

- `TutorialSession.verifying_step_id` field
- `TutorialSession.verification_task` field
- `TutorialSession.pending_verification_replan` field
- `_start_verification(step)` method
- `_run_verification(...)` method (the parallel variant — `_verify_step_blocking` replaces it)
- `_cancel_verification()` method
- `_consume_verification_replan()` method
- The two `replan = self._consume_verification_replan()` checks inside the wait loops in `_await_action`
- The `await self._cancel_verification()` calls inside `handle_step_started`, `handle_user_confirmation`, `shutdown`, and `_cancel_current_task`
- The `pending_verification_replan = None` line inside `_cancel_current_task`'s finally block
- `test_legacy_cancel_verification_clears_task` in `backend/tests/test_tutorial_session.py`

Kept for one commit so the cancellation API stayed stable across the gate
refactor. Once we're confident the gate is the only verifier path, all of
the above is dead code.
