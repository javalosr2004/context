# Agent UX Observations — Redundant Steps, Input Pacing, and Low-Confidence Recovery

Field notes from observing the tutorial agent in use. Two clusters of issues:
one about step granularity / clipboard ergonomics, one about the agent's
behavior when it can't find its target.

## 1. Redundant grounding steps and clipboard friction

### Observed
- The agent emits separate steps like "click the address bar" and "type <url>"
  even when both resolve to the same grounded bounding box. From the user's
  point of view these are one action, so showing them as two adds noise without
  adding information.
- Copy/paste into a grounded target is awkward. There's no affordance attached
  to the highlighted region for "paste this value here" — the user has to
  juggle the clipboard manually while the overlay points at the box.
- Typing steps don't wait long enough for the user. As soon as the type action
  is dispatched (or assumed complete), the agent advances to grounding the
  next step, even if the user hasn't actually finished entering the value.
  The next highlight appears mid-typing.

### Why it matters
- Redundant steps make the tutorial feel mechanical and break the "one
  instruction, one action" mental model.
- The pacing bug actively confuses users — the overlay moves on before they're
  done, so they lose their place.
- Clipboard friction is the most common interaction for any "fill this field"
  step, and right now it's the least supported.

### Directions to explore
- **Collapse co-located steps.** When consecutive steps share a grounded
  target (click + type into the same box), render them as one step with the
  value inline, not two sequential highlights.
- **Tooltip with copy-to-clipboard next to grounded region.** When a step has
  an associated value (URL, text to paste), show a small tooltip anchored to
  the bounding box with a one-click "copy" affordance. Keeps the user's hands
  on the target instead of bouncing to a side panel.
- **Wait for input completion before advancing.** Don't auto-advance off a
  type step on a fixed timer. Gate the next ground on either (a) an explicit
  user confirmation, or (b) a detector that the field actually contains the
  expected value. Pacing should be user-driven, not agent-driven.

## 2. Agent doesn't scroll or re-evaluate under low confidence

### Observed
- When the grounding confidence is low, the agent tends to commit to its
  current guess rather than scrolling to look for the target or asking the
  verifier to re-check the screen.
- Scrolling, in particular, is under-used. If the target isn't on-screen, the
  agent often doesn't try to bring it into view before grounding.

### Why it matters
- Low confidence is exactly the moment the agent should slow down — instead
  it speeds past, which is how it ends up pointing at the wrong element.
- A tutorial that confidently highlights the wrong region is worse than one
  that pauses and asks. Wrong-with-confidence erodes trust faster than
  visible uncertainty.

### Directions to explore
- **Confidence-gated scrolling.** Below a threshold, the agent's first move
  should be to scroll (up/down, or page-level) and re-ground, not to commit.
- **Re-evaluation loop.** Wire the verifier's verdict back into a "look
  again" path — scroll, re-screenshot, re-ground — before falling back to
  asking the user. Today the planner gating exists (see recent commit
  `feat(tutorial): gate planner on verifier verdict`), but the recovery path
  on a mismatch is still thin.
- **Explicit "I'm not sure" state in the overlay.** When confidence stays
  low after a scroll pass, surface that to the user instead of silently
  guessing. The product intent is a teaching system that asks for
  confirmation when uncertain — honor that here.

## Summary

Both clusters point at the same underlying issue: the agent currently treats
its plan as a script to execute rather than a hypothesis to verify with the
user in the loop. Fixing step collapsing + clipboard tooltip + input pacing
addresses the "too fast, too granular" side. Fixing scroll-on-low-confidence
+ verifier-driven re-evaluation addresses the "too confident when wrong"
side.
