# Scroll-Until-Visual: Design Plan

## Intent

Today, `scroll` is a planner-emitted `TutorialAction` with a `direction` and an
implicit displacement. The replay runtime executes it as a one-shot scroll
gesture. This is fragile: the recording's pixel distance rarely matches the
replay environment (different viewport, zoom, content reflow), so the target
the user was scrolling to reveal often ends up off-screen or scrolled past.

The new model: `scroll` stays a first-class planner step, but its semantics
shift from **"scroll N pixels in direction D"** to **"scroll in direction D
until visual target X is on screen"**. The step becomes a closed loop with a
vision-based termination condition. The runtime owns *how* to scroll; the plan
owns *what to scroll toward*.

This keeps the planner honest — every emitted scroll step must name what it
expects to reveal — and makes replay robust to environmental drift.

## Schema Change

`backend/tutorial_schema.py` — `TutorialAction`:

- Keep `type: "scroll"` and `direction`.
- **Add** `until: ActionTarget | None` — same shape as `target` on a click
  step (semantic description + optional anchor crop). This is what grounding
  evaluates each sample tick.
- Drop the implicit displacement contract. The runtime owns tick size and
  budget; the plan no longer implies "how far."
- Validation: `scroll` requires both `direction` and `until` (replaces the
  current "scroll requires direction" check at `tutorial_schema.py:287`).

Back-compat: legacy plans with `scroll` actions lacking `until` are treated as
no-ops at replay time (logged + skipped). No migration script needed if no
saved plans are in active use; otherwise emit a one-time warning.

## Planner Prompt Change

`backend/tutorial_guide.py` — when emitting a scroll step, the model must
populate `until` with the thing it expects to become visible (typically the
target of the *next* click step). This coupling is the point: scroll exists
in the plan to reveal something specific, and the plan must name it.

Open call: `until` is kept explicit rather than auto-derived from the next
step's `target`. Reason: standalone orientation scrolls ("scroll until you
see the pricing table") should be expressible without an immediately-following
click.

## Runtime: Scroll-Until-Visual State Machine

Owns the loop in the renderer (Electron overlay). The Rust backend exposes two
primitives the renderer calls per tick: `scroll_tick(direction, delta)` (see
`electron/rust-backend/src/mouse/mod.rs:79`) and `capture_frame()`. Grounding
calls go to the existing Python `ground(frame, target_description)` endpoint
used for click steps.

### States

```
IDLE → BURST → SETTLE → SAMPLE → (found?   DONE
                                  no-progress?  FLIP_DIR or ESCALATE
                                  else:    BURST)
```

### Per-state behavior

**BURST** (default 400ms)
- Every ~16ms: `rust.scroll_tick(direction, tick_delta_px)`
- On timer end → SETTLE

**SETTLE** (default 120ms)
- No scroll, no capture. Lets layout/animation quiesce so the sampled frame
  is clean.
- On timer end → SAMPLE

**SAMPLE**
- `frame_now = rust.capture_frame()`
- Pixel-diff vs. `last_burst_start_frame`:
  - If `changed_pixel_ratio < 0.5%`: `stagnant_ticks += 1`
  - If `stagnant_ticks >= 2`: end-of-region in this direction →
    FLIP_DIR (if we haven't already) or ESCALATE.
- If `grounding_in_flight == true`: skip this sample, do **not** queue.
  → BURST.
- Else: set `grounding_in_flight = true`, store
  `last_burst_start_frame = frame_now`, fire
  `ground(frame_now, action.until).then(handleResult)` **non-blocking**.
- Immediately → BURST. Scroll continues during the grounding round-trip.

**handleResult(result)**
- If aborted (step changed, user paused): drop result silently.
- `grounding_in_flight = false`
- If `result.found`: cancel both timers, freeze scroll → DONE.
- Else: no-op. Next SAMPLE will fire another call.

**FLIP_DIR**
- Reverse `direction` once per step. Reset `stagnant_ticks`.
- Resume from BURST.

**ESCALATE**
- Hit `max_total_ticks` or end-of-region in both directions.
- Surface to the user via the existing low-confidence confirmation path:
  "I couldn't find X — does this look right, or should I keep trying?"

### Why this satisfies the two constraints

- **Bounded call rate**: at most one grounding call in flight at any moment;
  new ones only start at SAMPLE boundaries (~every `burst_ms + settle_ms` ≈
  520ms in defaults). Hard ceiling ≈ 2 calls/sec, usually less because
  grounding latency exceeds the cycle.
- **Snappy on match**: `handleResult` cancels timers the instant `found`
  returns. Scrolling continues *during* the grounding round-trip (BURST
  resumes immediately at SAMPLE), so there's no idle wait — but the moment
  grounding answers `found`, scrolling stops on the next event-loop tick.

### Cancellation & cleanup

Wrap the machine in an `AbortController`. On step transition to DONE, on user
pause, or on session teardown:

1. Clear both timers.
2. `signal.aborted = true` so any still-in-flight grounding response is
   dropped in `handleResult`.
3. Ensure no scroll tick is queued in Rust IPC.

This is non-negotiable — a leaked timer or late grounding callback will
fire `scroll_tick` after the user has moved on.

## Tuning Knobs

Exposed as runtime config, not hard-coded:

| Knob                          | Default | Notes                                  |
|-------------------------------|---------|----------------------------------------|
| `burst_ms`                    | 400     | Continuous-scroll burst length         |
| `settle_ms`                   | 120     | Quiesce time before sampling           |
| `tick_delta_px`               | 60–80   | Per-tick scroll delta, platform-tuned  |
| `stagnant_pixel_ratio`        | 0.005   | Below this = "nothing moved"           |
| `stagnant_ticks_before_flip`  | 2       | Avoid sticky-header false positives    |
| `max_total_ticks_per_step`    | 20      | Hard budget before ESCALATE            |

## End-of-Region Detection

Pixel-diff between `last_burst_start_frame` and the post-settle frame, with
two refinements:

1. **Threshold, not exact equality** — animated content (video, spinners,
   blinking carets) creates a small steady-state diff. Below `~0.5%` changed
   pixels is treated as "no scroll progress."
2. **Two consecutive stagnant ticks** before declaring end-of-region. A single
   tick can land exactly on a sticky-header boundary and look static even mid-
   scroll.

AX-based scroll position queries (`AXValue`/`AXMaxValue`) are explicitly out
of scope for MVP — permission cost is high, coverage on web views and custom
scrollers is poor, and locating "the right scroll container" under the cursor
is its own problem.

## Implementation Order

1. **Schema** — add `until: ActionTarget | None` to `TutorialAction` in
   `tutorial_schema.py`. Update validation. Regenerate ts-rs bindings.
2. **Planner prompt** — update `tutorial_guide.py` so scroll steps must emit
   `until`. Update example outputs in the prompt.
3. **Tool layer** — update `ScrollAction` in `tutorial_tools.py` and the
   conversion in `_infer_scroll_direction` / surrounding code to carry `until`.
4. **Runtime primitives** — confirm renderer has IPC access to `scroll_tick`
   and `capture_frame`; add any missing wrapper.
5. **State machine** — implement the BURST/SETTLE/SAMPLE loop in the renderer,
   wired to the active step. Include `AbortController` plumbing from day one.
6. **Escalation hook** — route ESCALATE into the existing low-confidence
   confirmation UI; do not invent a new modal.
7. **Tests** — pure-logic unit tests for the state machine (mock timers,
   mock grounding responses): match-on-first-sample, match-after-N-bursts,
   end-of-region-flip, end-of-region-escalate, abort-mid-flight.

## Out of Scope (Explicitly)

- Horizontal/2D scroll search (start with `up`/`down`; `left`/`right` work
  via the same loop but aren't a first-class goal yet).
- Diff-cropped frames sent to grounding (send the full viewport — model
  needs anchor context above/below the revealed strip). Diff is used only
  for *progress detection*, not for the grounding payload.
- SIFT or feature-matching fallbacks. Pixel-diff + visual grounding is the
  whole loop; SIFT is reserved for if real workflows break the naive diff.
- AX-based scroll container introspection.
