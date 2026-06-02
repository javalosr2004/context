# God-Class Refactor Plan

*Date: 2026-06-01*
*Scope: the two largest files in the repo. Behavior-preserving, incremental, test-green at every step.*

## Why this plan exists

Two files have grown into god-objects that mix many responsibilities. They are the most
intimidating thing a new reader (or reviewer) opens, and the riskiest thing to change:

| File | Lines | What's wrong |
|---|---|---|
| `backend/tutorial_session.py` (`TutorialSession`) | 2630 | One class owns the WS protocol, the agent loop, grounding, the verifier, plan mutation, logical-id resolution, completion, and task lifecycle. |
| `context-app/.../Presentation/Views/ChatPopupView.swift` (`ChatPopupView`) | 2600 | One SwiftUI struct holds ~30 `@State` properties and ~40 inline subviews/formatters — view, view-model, and a dozen distinct UI surfaces in one body. |

This is a **pure refactor**. No behavior changes, no new features. The contract is: the
backend test suite (307 tests) and the Swift test target stay green after every step, and each
step is an independently shippable commit. We extract along seams that already exist — we are
not redesigning, just giving each responsibility its own home.

## Guardrails (apply to every step)

1. **Green before and after.** Run `uv run --project backend python -m pytest backend/tests -q`
   (and the Swift test target in Xcode) before committing each step. A step that changes a test
   assertion is not a pure refactor — stop and reconsider.
2. **One responsibility per commit.** Extract one collaborator, run tests, commit. Never batch
   two extractions.
3. **Composition over inheritance.** Extracted pieces are plain collaborators the god-object
   *owns*, not subclasses.
4. **No public-contract drift.** The WS event schema (`tutorial_session_events.py`) and the
   HTTP routes (`main.py`) must not change. The overlay must not notice.
5. **Characterization test first when a seam is untested.** If a region has no test, add one
   that pins current behavior *before* moving the code.

---

## Target 1 — `TutorialSession` → coordinator + collaborators

The class already documents its own seams with `# --------` banners. Each banner is a
candidate collaborator. `TutorialSession` becomes a thin coordinator that owns these and
delegates to them.

### Proposed collaborators (by existing region)

| New unit | Extracted from (region) | Responsibility |
|---|---|---|
| `AgentLoop` | `_run_agent_loop`, `_stream_llm_once`, `_build_llm_request`, `_llm_images` | Drive one planner turn: build request → stream tool calls → hand results back. |
| `PlanMutator` | `_execute_plan_update_call`, `_assign_logical_ids`, `_resolve_logical_id`, `_logical_id_for`, `_log_dropped_update_plan` | Apply `update_plan` tool calls and keep logical IDs stable across replans. |
| `StepVerifier` | `_start_verification`, `_run_verification`, `_cancel_verification`, `_consume_verification_replan` | The background per-step verifier (already advisory/non-blocking). |
| `GroundingCoordinator` | `_ground_with_events`, `_ground_single_query_with_events`, `_ground_multimodal_with_events` | Turn a step target into screen coordinates, emitting progress events. |
| `DraftPlanRunner` | `_kick_off_draft_plan`, `_run_draft_plan`, `_await_draft_plan`, `_cancel_draft_task` | The up-front coarse hypothesis plan. *(Candidate for deletion — see note.)* |
| `StepWalker` | `_walk_steps`, `_await_step`, `_await_action`, `_wait_for_step_event` | Advance through steps/actions against incoming user events. |
| `SessionTasks` | `_start_task`, `_cancel_current_task` | The single-in-flight-task lifecycle primitive. |

`TutorialSession` keeps: the public WS entry points (`handle_user_*`), the session state it
coordinates, and the wiring between collaborators.

### Order (each is one PR, tests green)

1. **`SessionTasks`** — smallest, purely mechanical (start/cancel one coroutine). Proves the
   extraction pattern with near-zero risk.
2. **`PlanMutator`** — mostly pure functions over plan state; logical-id logic is already
   unit-tested-adjacent. High value, testable in isolation.
3. **`GroundingCoordinator`** — self-contained I/O; clear input (target) → output (coords).
4. **`StepVerifier`** — already isolated as background work; lift wholesale.
5. **`AgentLoop`** — the core; do it after the easy wins so the seam is well understood.
6. **`StepWalker`** — depends on the event plumbing; extract last.
7. **`DraftPlanRunner`** — see note before extracting.

> **Note — possible deletion, not extraction.** `remove-spaghetti.md` and the product
> critique flag the draft-plan pre-pipeline and parts of the verifier as candidates for
> removal, not preservation. Before extracting `DraftPlanRunner` (and before polishing
> `StepVerifier`), decide: is this code on the keep-list? If not, deleting it is a bigger win
> than extracting it. Refactor only what survives that question.

### Acceptance criteria
- `tutorial_session.py` drops below ~600 lines (coordinator + state only).
- Each collaborator has a focused unit test that does not spin up a full session.
- 307+ backend tests still pass; WS event schema byte-identical.

---

## Target 2 — `ChatPopupView` → small views + a view-model

The struct mixes three things: **state** (~30 `@State` vars), **derived/formatting logic**
(`statusChips`, `actionChipLabel`, `shortTargetLabel`, `planDiffSignature`, `handlePlanDiffChange`),
and **many independent UI surfaces** (launcher, peek stack, ask bar, question card, completion
prompt, verification hint, composer, instruction input, finished view, header, message list).

### Step 2a — Extract pure formatting into a tested helper
Move the pure string/label logic out of the view first — it is the easiest to test and carries
no SwiftUI coupling:
- `actionChipLabel(for:)`, `typeActionText(for:)`, `shortTargetLabel(_:)`, `truncate(_:max:)`,
  `chipKind(index:active:)`, `loadingText`, `planDiffSignature`.
- New `ChatPopupFormatting` (plain Swift, no `View`), with unit tests in `ContextAppTests`.

### Step 2b — Introduce a `ChatPopupViewModel: ObservableObject`
Move the non-UI `@State` and the logic that mutates it (`handlePlanDiffChange`,
`statusChips`, step-tracking vars like `activeStepID`, `expandedStepID`, `lastSeenTotalSteps`,
`stepChipFlash`) into a `@MainActor` view-model. The view observes it via `@StateObject`.
Pure presentation state (`@State private var draft`, focus, hover) stays in the view.

### Step 2c — Split each UI surface into its own `View` file
Each `private var someView: some View` that represents a distinct surface becomes its own
`struct` in `Presentation/Views/ChatPopup/`:
- `LauncherView`, `PeekStackView`, `AskBarView`, `QuestionCardView`,
  `CompletionPromptView`, `VerificationHintView`, `ComposerView`,
  `InstructionInputView`, `FinishedTutorialView`, `StatusChipRow`, `MessageListView`.
- `ChatPopupView` becomes a ~150-line composition root that wires the view-model to these.

### Order & risk
- 2a is zero-risk and immediately testable — do it first, commit.
- 2b is the behavior-sensitive step (state ownership moves); do it as one focused PR and
  lean on the existing `PopupStateTests` / `TutorialPlanDisplayTests` to catch regressions.
- 2c is mechanical once 2b lands — one commit per extracted surface.

### Acceptance criteria
- `ChatPopupView.swift` drops below ~200 lines (composition only).
- Formatting logic covered by unit tests (no view instantiation).
- No visual or interaction change — verify by running the app on a recorded tutorial and
  walking a full session.

---

## What this is *not*

- Not a redesign of the agent or the overlay.
- Not a behavior change — if a test needs editing, the step has overstepped.
- Not a license to extract speculative abstractions. Extract a collaborator only when it has a
  name and a single responsibility that already exists in the code. Anything on the
  delete-list (`remove-spaghetti.md`, product critique) is cut, not refactored.

## Suggested sequencing across both targets

Interleave so no single PR is huge and momentum is visible:
1. `SessionTasks` (backend, trivial) → proves the pattern.
2. `ChatPopupFormatting` + tests (Swift 2a) → proves the pattern on the app side.
3. `PlanMutator` (backend) → first high-value backend extraction.
4. `ChatPopupViewModel` (Swift 2b) → the app's pivotal step.
5. Remaining backend collaborators, then remaining Swift surface splits, one commit each.
