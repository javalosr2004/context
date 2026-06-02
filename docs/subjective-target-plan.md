# Subjective-target plan

Pickup notes for the second half of the grounding-issues conversation.
First half (stability gate on `user_confirmation`) is already landed.

## Problem

The planner sometimes emits actions whose target is the user's choice, not
a concrete on-screen element — e.g. *"click on the item that **you** want"*.
The frontend grounder dutifully treats the description as a literal target
and tries to ground it. There is no pixel that matches.

This is not a grounding bug; it's a planner output contract bug. The
planner is asserting "there's a target to ground" when the honest
statement is "the user makes a free choice here."

## Direction (already agreed)

Detection lives in the planner via the schema, not in a post-hoc classifier
and not in the grounder. The planner emits a new action variant that means
"no target — let the user pick anything reasonable."

## Current state of the code (anchors)

- `backend/tutorial_schema.py:27-42` — `ActionTarget(kind, label, role, description)`. `kind` is `element | screen | window | region`.
- `backend/tutorial_schema.py:45-85` — `TutorialAction`; `target: ActionTarget | None`.
- `backend/tutorial_tools.py:388-401` — `_action_from_payload` converts LLM `ClickAction` / `TypeAction` payloads → `TutorialAction` with `target=ActionTarget(kind="element", description=payload.agent_description)`.
- `backend/tutorial_guide.py:76-200` — system prompt for the planner. No notion of user choice today.
- The frontend overlay consumes `target.description` directly via the grounder; no backend-side grounding service.

## Proposed implementation

### 1. Schema

Add a new action type rather than overloading `target`. Reasoning:
`target=None` already exists for non-spatial actions (e.g. `wait`,
`press_key`), so collapsing user-choice onto `target=None` muddies the
"is this action spatial?" question.

Two reasonable shapes — pick one:

- **(a) New action type**: extend `TutorialAction.type` with `"user_choice"`. Carries `prompt: str` ("Pick any video you want to watch", "Type your username", "Click on the repo of your choosing"). The action is *modality-agnostic* — the user's free input may be a click, a typed string, a selection, etc. No region, no target.
- **(b) New target kind**: keep `type="click"` but add `ActionTarget.kind = "user_choice"`. Less invasive but wrong: locks user-choice to click, when it equally applies to typing ("enter your own username") and other free input.

Prefer **(a)** — it's the lifecycle that's different, not just the target, and `user_choice` spans click *and* type *and* whatever else the user freely provides.

### 2. Planner schema (LLM-facing)

In `backend/tutorial_tools.py`, the LLM tool schema for `tutorial_update_plan`
needs a new action variant alongside `ClickAction`, `TypeAction`, etc.
Something like:

```py
class UserChoiceAction(BaseModel):
    type: Literal["user_choice"]
    prompt: str            # "Pick the video you want to watch" / "Type your username" / "Click any repo"
```

No region, no target, no modality field. The prompt is the whole contract: it tells the user what to do, the overlay shows it, and any plausible input advances the step.

Then `_action_from_payload` maps it to a `TutorialAction(type="user_choice", ...)`.

### 3. Planner prompt

`backend/tutorial_guide.py` system prompt needs a short rule:

> If the next step requires the user to make a free choice — which item
> to watch, which file to open, which message to reply to, *what
> username to type*, what search query to enter — emit a `user_choice`
> action with a short prompt. Do NOT emit `click` with a description
> like "the item you want", and do NOT emit `type` with placeholder
> text like "your username" — there is no deterministic target or
> string to ground.

Include 1–2 few-shot examples in the prompt so the model internalizes the
distinction between *deterministic-target click* and *user-choice click*.

### 4. Walk loop

`tutorial_session.py` walks step-by-step and awaits confirmation. The
walk loop currently assumes every spatial action has a target it can
hand to the frontend grounder via `step_ready`. A `user_choice` action
has no target, so the emission shape is different — this *does* require
backend changes:

- `step_ready` payload needs to carry the action type so the frontend
  knows whether to ground or to render the prompt directly.
- For `user_choice`, emit a step payload with `type="user_choice"` and
  the `prompt` string; no target, no grounding hint.
- Confirmation still comes from the same `user_confirmation` path. The
  user does whatever the prompt asks (click, type, etc.), the overlay
  confirms locally, ships the stable post-action screen (already wired
  from the first half), and the walk advances.

No new event *types* — `step_ready` and `user_confirmation` stay — but
the `step_ready` payload schema needs the action-type discriminator.
Grep `tutorial_session.py` for every `step_ready` emission and audit
how target is assumed before coding.

### 5. Frontend overlay

- `TutorialPlan.swift` — add `user_choice` to the action type enum.
- `TutorialActionConsumer` — when the action type is `user_choice`, do
  **not** call the grounder and do **not** assume the input is a click.
  Show the prompt in the popup; the confirming input may be a click,
  keystrokes, or anything else the user does in response.
- `FocusMaskController` — currently gates `onInsideClick` against a
  specific target region. Needs a "freeform" mode where any qualifying
  user input (click anywhere, or typing activity in the focused app)
  counts as the trigger to start the stability watcher.
- Stability watcher path is already correct: `onInsideClick` →
  `waitUntilStable` → `currentScreenSnapshot` → `confirmStep(screen:)`.
  No changes needed there.

## Tests

- `backend/tests/test_tutorial_tools.py` — parsing `UserChoiceAction` from
  LLM payload, mapping to `TutorialAction(type="user_choice")`.
- `backend/tests/test_tutorial_session.py` — a plan with a `user_choice`
  step walks correctly: emits awaiting, takes a confirmation, advances.
- Frontend: `TutorialActionConsumerTests` — `user_choice` action does not
  invoke the grounding closure.

## Out of scope for this slice

- Region constraints or any spatial gating — `user_choice` is
  intentionally modality- and location-agnostic (click, type, etc.).
  Adding region scoping would re-introduce the "there's a target" lie
  this whole design is trying to remove.
- Backend re-validation that the user did a sensible thing — that's a
  monitor-session concern, not a planner concern.

## First slice to ship

1. Schema: `TutorialAction.type="user_choice"` + `prompt` field.
2. LLM tool schema + prompt update with few-shot examples covering
   *both* click-style ("pick any repo") and type-style ("enter your
   username") user choices.
3. Walk loop: extend `step_ready` payload with action type; emit
   `user_choice` steps without target/grounding fields.
4. Frontend: action consumer branch + freeform FocusMask mode (accepts
   click or typing as the qualifying input).
5. Tests for parsing, walking, and the new `step_ready` payload shape.

Prompt tuning and planner backsliding (e.g. model still emitting `click`
or `type` with user-choice-shaped descriptions) become follow-ups —
likely a server-side lint that converts offenders to `user_choice`.
