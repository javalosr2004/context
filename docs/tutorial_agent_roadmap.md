# Tutorial Agent — Design & Roadmap

Captures the in-flight redesign of the tutorial session agent plus near-term product wants. Not a spec; intent + decisions so we can resume without re-deriving.

## Problem with the current agent

It behaves like a VLM CUA: every screen-changing action force-injects a fresh screenshot request (`tutorial_session.py:_request_fresh_screen_after_user_action`), so the model never commits to a multi-step hypothesis. It also requests screenshots stalely or hesitantly because `tutorial_request_screen` is framed as the default way to continue.

## Target architecture: plan-then-verify with an async monitor

Split the model into two roles:

### Planner (big model — current Opus/Sonnet/Gemini Pro)
- From the **initial** screen, commits to a multi-step hypothesized plan in one turn.
- No forced screenshot between action tools.
- Called again only on `diverged` or user rejection.
- Initial screen capture must be high-quality (full window, focused app) since everything downstream is hypothesis.

### Monitor (small model — GPT-4.1-mini / nano, or Haiku 4.5)
- Runs async on each post-action screenshot.
- Forced-choice verdict — strict enum, no free-form reasoning fields:
  - `on_track`
  - `still_loading(retry_in_ms)` — frontend re-sends after delay; capped retry count to prevent spin.
  - `advanced(to_step_id)` — user jumped ahead; fast-forward plan pointer.
  - `diverged(reason)` — escalate to planner with screen + reason. Monitor never writes a new plan.
- Context payload, minimal: `{prev_human_instructions[-3:], current_step (human + agent_description), next_human_instructions[:5], screen}`. No full history.

### Tool surface changes
- Add `wait_for_ms` to every action tool, model-supplied, with per-type defaults (click ~200, type ~100, scroll ~500, press_key-for-nav ~1500). Frontend treats it as earliest-send debounce, not hard sleep.
- Rewrite `tutorial_request_screen` description: "use when your hypothesis branches, not to verify each step."
- Add planning-phase system prompt nudge: *"Commit to a multi-step hypothesis from the current screen. Only request a screen when you genuinely cannot predict the next state."*
- Rip out `_request_fresh_screen_after_user_action`.

### Code layout
Two configured clients in `llm_provider.py`:
- `planner_llm` — existing big model.
- `monitor_llm` — small model, separate call path.

## Frontend / product roadmap

Not blocking the agent redesign, but next-up:

- **Minimalist UI.** Current overlay reads as a dev environment. Move toward a polished mini-app aesthetic.
- **Drop the "weird box."** Reframe the popup chrome — no boxy container.
- **Menu bar ≠ status bar.** The menu bar item shouldn't double as live status display; status belongs in the overlay.
- **Better-rendered hypothesis plans.** Plan list should feel like a tutorial card, not a JSON dump. Tied to the planner emitting structured steps.
- **PDF upload.** Accept PDFs as input alongside screen + text. Likely a new content channel into the planner.
- **Web grounding.** Planner can pull live web context when the task references an external service / docs.
- **Run persistence for training & debugging.** Save full session traces (events, screens, tool calls, verdicts) to a durable store. Two consumers:
  - Debug replays.
  - Future fine-tuning / eval datasets for both planner and monitor.
