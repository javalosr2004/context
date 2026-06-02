# Project Audit — Context / Tutorial Overlay

*Date: 2026-05-21*
*Scope: backend/, context-app/, docs/, docker/. Electron/ excluded.*
*Method: read code, not just docs. File:line receipts throughout.*

---

## TL;DR

You have a **state-machine problem dressed up as a feature problem**. The agent's state lives in ~40 fields on one dataclass, with 4 tool branches in one 266-line function, and the same shape is replicated in Swift. The CLAUDE.md vows (Uncle Bob, small functions, explicit state, deterministic behavior, no magic) are all being violated by the single file that is the heart of the product.

The product-strategy issues — no defined ICP, three subsystems built in parallel, an in-tree search engine — are real, but the **engineering rot in `tutorial_session.py` is the immediate threat to shipping anything**.

---

## 1. What this project actually is

### The story the README tells

A macOS app that records a workflow once and replays it as a live on-screen overlay tutorial with confirmation prompts. "Teaching while doing." MVP-shaped.

### What the code says it is

A research-grade multimodal agent platform with:

- A **2,605-line `tutorial_session.py`** orchestrating a planner LLM + async monitor LLM + instruction verifier — with a *strict-gate* refactor that left half its predecessor in place (see `remove-spaghetti.md`).
- A separate **`enrichment-layer`** container doing Brave web search + Playwright rendering + trafilatura + SQLite indexing of tutorial corpora. This is a search engine.
- A **`recording-enrichment`** container that re-describes captured actions with Holo.
- A **`gui-grounding`** container, a **`gui-actor-inference`** container (with a Colab launcher and a DeTR model), and workers for omniparser, ui-segmentation, ffmpeg-crop.
- A Caddy gateway in front of all of it.
- Embeddings client, conversations store, session event log, plan-merge, cached enrichment, OpenAI + Gemini + Holo + holo-chat clients, web-grounding, PDF input, A/B flags (`STEP_TOOLS_ENABLED`, `GROUNDING_STRATEGY`), session run persistence "for training/debugging."
- Meanwhile the **frontend** (`context-app/specs/001-overlay-tutorial/spec.md`) is still spec'ing US1 ("show a transparent overlay with a draggable popup") and US2 ("render a green 500x500 debug bbox"). You are simultaneously fine-tuning a planner/monitor split *and* trying to ship the green debug rectangle.

This is not an MVP. It is a research project pretending to be an MVP, with a shell app that hasn't caught up.

---

## 2. Engineering rot — file:line receipts

### 2.1 `TutorialSession` is a god object

`backend/tutorial_session.py:151-248` declares one dataclass with **~40 mutable fields**:

- 6+ distinct "pending" futures/handles: `pending_screen`, `pending_screen_request_id`, `pending_completion`, `pending_completion_response`, `pending_question_response`, `pending_question_batch_id`, `pending_question_ids`, `pending_step_starts`, `pending_step_confirmations`, `pending_verification_replan`.
- 4 task handles: `current_task`, `draft_plan_task`, `verification_task`, plus the implicit `_start_task` task.
- Cross-cutting flags: `screen_is_stale`, `turn_zero_consumed`, `plan_emitted`, `confirmed_with_fresh_screen_step_ids` (a set of step IDs to suppress a stale-screen flip — a fourth distinct screen-staleness signal).
- Embeddings cache, attempt counter, last-action-kind, draft plan, two A/B flags, two `_planner_*` metrics, status string, two timestamps, an LLM call sink…

The entire state machine sits in one struct, owned by one task, mutated by ~30 methods. **No invariant guard anywhere** — nothing asserts that `pending_screen is None` implies `pending_screen_request_id is None`, etc. Every method that touches these fields must remember the unwritten contract.

CLAUDE.md promised "deterministic behavior, explicit state, clear failure modes." This is the opposite: state is implicit, distributed, and failure modes are emergent.

### 2.2 `_run_agent_loop` is a 266-line procedural state machine

`backend/tutorial_session.py:691-956`. Inside one function:

- Awaits the draft plan (first turn only, guarded by `if not self.plan_steps and self.draft_plan is None`).
- Maintains turn budget (`MAX_AGENT_TURNS = 8`) and a separate consecutive-screen-request budget (`MAX_CONSECUTIVE_SCREEN_REQUESTS = 3`).
- Streams the LLM, times it, records it.
- Partitions tool calls into 4 buckets (`update_plan_calls`, `request_screen_call`, `request_completion_call`, `ask_user_call`) plus `unknown_calls`.
- Validates the turn-0 `ask_user` gate with two distinct rejection paths.
- Handles "multiple update_plan calls" by keeping the last and rejecting the rest.
- Forces a synthetic `request_screen` when a text-only turn comes back on a stale screen (loop guard, lines 762-797).
- Closes the turn-0 gate from two different sites.
- Emits stall events, status events, agent turn events, text-response events.
- Bumps planner metrics in a `finally`.

The docstring at the top of the file says the model has **two tools**. The code has **four** (`update_plan`, `request_screen`, `request_completion`, `ask_user`). The docstring is stale by at least one tool surface refactor.

Adding a 5th tool requires open-heart surgery on a routing block with no abstraction. There is no `ToolHandler` protocol. There is no tool registry. The pattern is `is_X_call(c)` + `parse_X_arguments(c)` + `_execute_X_call(c)` as free functions in `tutorial_tools.py`, and the router that calls them is hand-rolled at lines 819-826.

### 2.3 The strict-gate refactor confessed in `remove-spaghetti.md` is real

`tutorial_session.py:213-215`:
```python
verifying_step_id: str | None = None
verification_task: asyncio.Task[None] | None = None
pending_verification_replan: str | None = None
```

These are the *legacy* parallel-verifier fields. The new gate is `_plan_or_gate` (line 1252) + `_verify_step_blocking` (line 1326). The legacy `_start_verification` / `_run_verification` / `_cancel_verification` (lines 1468, 1489, 1572) are still wired into `handle_step_started` (line 386), `handle_user_confirmation`, `shutdown`, and `_cancel_current_task`.

`remove-spaghetti.md` names every single one and says they're "Kept for one commit." The commit that flipped the gate is `7717c446`. Check the git log on this file and ask whether "one commit" was honest.

### 2.4 The verifier prompt is failing on the easiest possible tutorial

`backend/instruction_verifier.ANALYSIS.md` documents a real run: a ~1m45s "create a GitHub account" walkthrough looped on the gate because the verifier returned `unsure` on three legitimate screens. The doc admits:

- The code at `instruction_verifier.py:92-95` already maps `unsure → ok=True`, but the session log shows `unsure` triggering replans. Either the dev server is stale or the model is actually returning `"no"` and the doc author isn't sure which.
- A **stale unit test** (`test_unsure_verdict_rejects`) still asserts the *old* semantics. It wasn't updated when commit `62ed59ed` flipped them. The author flags this and says **"not in scope for this PR."**

Two damning things in one doc:

1. You cannot tell from your own logs whether the model is hitting the `"no"` branch or the `"unsure"` branch. The instrumentation is insufficient to disambiguate the two failure modes you most need to distinguish.
2. You found a broken test, knew it was broken, and chose not to fix it. That is how the trust-the-tests muscle atrophies.

The real problem in the project is not "too many subsystems." It is "the core decision logic isn't observable enough to debug, and the team has normalized that."

### 2.5 The Swift app is the same pathology, in another language

- `ChatPopupView.swift`: **2,477 lines**. One SwiftUI view. The frontend mirror of the backend god-function.
- `TutorialSessionController.swift`: 691 lines, **15+ `@Published` properties** including `awaitingConfirmationStepID`, `currentStepID`, `pendingContinuePromptStepID`, `pendingCompletionPrompt`, `pendingQuestionBatch`, `agentTurn`, `stepProgress`, `lastPlanDiff`, `lastFrameHash`, `webSources`, `draftPlan`, `messages`, `status`. Every backend pending-future has a Swift twin.
- The state machine is duplicated and the two halves drift independently. `TutorialSessionUIStatus` has 9 cases (line 8-17); backend `status: str` has at least `"created"`, `"planning"`, `"ready"`, and others scattered through `StatusChangedEvent` emits. **No shared schema.** Renaming a backend state does not break the Swift compiler.
- `TutorialSessionAPIClient.swift`: 623 lines.
- Recording subsystem under `Application/Recording/`: **14 files / 2,006 lines**. Includes `KeyTypingSessionizer`, `ScrollSessionizer`, `ContinuousFrameStream`, `EnrichmentUploader`, `EnrichmentStatusStream`, `Cropper`, `GoalSheetController`. This is a real product. It is just not the product the README claims you are shipping.

### 2.6 Two A/B flags with test/prod skew baked in

`backend/tutorial_session.py:228`:
```python
step_tools_mode: Literal["full_plan", "capped_head"] = "full_plan"
```

Comment at lines 220-227, verbatim:
> "the dataclass default is `full_plan` so direct construction (mostly tests) gets the simpler legacy behavior. Production runs default to `capped_head` via TutorialSessionStore / the STEP_TOOLS_ENABLED env var."

You wrote down, in a source comment, that **your tests exercise a different mode than production**. The A/B test you are running (per memory: `project_step_tools_ab.md`) tests the production branch *while your unit tests cover the other branch*. This is how regressions land: the test passes, the prod-mode bug is invisible.

Same pattern with `grounding_strategy: "parallel" | "planner"` at line 235.

### 2.7 The Xcode build has been broken for 16 days

`context-app/ContextApp/README.md`:
> "Last verification attempt on 2026-05-05: `xcodebuild test`: BLOCKED before project build. Xcode 26.4.1 failed to load `IDESimulatorFoundation` because `DVTDownloads.framework` is missing the expected `developerDocumentation` symbol."

Today is 2026-05-21. You have been shipping Swift code for sixteen days without running the Swift test suite locally. You are also concurrently using **SpecKit** (`context-app/CLAUDE.md` lists `speckit-*` skills and a `.specify/memory/constitution.md` v3.1.0) on top of code you cannot test. That is process theater funded by an engineering budget that is already overdrawn.

### 2.8 The docstring lies are the tell

`tutorial_session.py:7-14`:
> "The model has two tools: `tutorial_update_plan` ... `tutorial_request_screen` ..."

The actual tools are four. The docstring is wrong, in the file's own opening comment. When the docstring at the top of a 2,605-line file is wrong about basic surface area, no part of that file's documentation is trustworthy.

---

## 3. Scope creep — the receipts

CLAUDE.md says:
> *"Don't over-engineer early. Start flat, extract modules only when a boundary becomes necessary."*
> *"Avoid 'magic.' Prefer deterministic behavior."*

What is actually there:

| Original MVP slice | What exists now |
|---|---|
| "Record clicks/keys/screens to `events.jsonl`" | Recording pipeline plan + dedicated enrichment container + SSE status stream + Holo descriptions + gui-grounding verification step + scroll sessionizer + cropper |
| "Replay with overlay + highlight target + confirm screen" | Planner/monitor agent split, strict-gate verifier, plan-merge, full-plan-vs-capped-head A/B test, run persistence for future fine-tuning |
| "macOS-first, Electron + capture service" | Electron *and* a Swift `ContextApp` *and* a Python backend *and* 5+ docker services *and* a Caddy gateway. AGENTS.md still says Electron; the code says Swift. |
| "No PII removal yet — design so it lands later" | Fine, but you also added Brave-search-based web grounding and persistent session traces before PII scrubbing exists. The first user who records a Gmail flow is going to surface this. |
| "Universal recording + overlay player" | Roadmap (`tutorial_agent_roadmap.md`) now lists: PDF upload, web grounding, polished mini-app aesthetic, run persistence for training data, drop the "weird box," planner-vs-monitor model selection. None of these are MVP. All are in flight. |

---

## 4. Product strategy — who is this for?

### Who uses this today

Nobody, yet, and the ICP is not defined. The README hedges with three example use cases — "setting up Git, navigating internal tools, completing multi-step web flows" — which are three totally different markets:

- **"Setting up Git"** → developer onboarding. Audience already lives in terminals and reads docs; a Mac-only overlay is the wrong form factor. Loser.
- **"Internal tools"** → enterprise digital adoption. Real TAM, owned by **WalkMe ($7B IPO), Pendo, Whatfix, UserLane, AppCues**. They have SSO, browser-extension distribution, admin consoles, analytics dashboards, SOC2. You have a green debug rectangle.
- **"Multi-step web flows"** → consumer how-to. Owned by **Scribe, Tango, Guidde** — and YouTube. Scribe in particular nails the "record once, share as steps" loop with screenshots + auto-redaction + a browser extension. They do not need an always-on-top overlay because the artifact is the page, not the screen.

You do not have a user. You have three half-imagined personas that each justify a different subsystem you wanted to build.

### Differentiation

- **vs. Scribe/Tango/Guidde**: They produce a *document*; you produce a *live coach*. Genuine difference, but their advantage is shareability and zero install. Your overlay requires a macOS native app, screen-recording permission, accessibility permission — except you said "no AX in recorder" in `feedback_no_ax_in_recorder.md`. You forced yourself into vision-only grounding to keep cross-platform options open, which makes you *strictly worse* at the macOS-only MVP than tools that just use AX. You are paying a portability tax for a portability story you may never ship.
- **vs. WalkMe/Pendo/Whatfix**: They get deterministic element targeting via DOM/extension. You are betting on a VLM saying "this looks like the right button." On a redesign, they fix one selector; you re-record. Their failure mode is "tooltip on wrong element"; yours is "agent hallucinates a click target." Enterprise will not buy that.
- **vs. real automation agents (Anthropic Computer Use, OpenAI Operator)**: You have explicitly said you are *not* an agent — you are a teaching system. Fine, but then the entire planner/monitor/verifier complex is a *means*, not the *product*, and you are spending 80% of your engineering budget on the means.
- **vs. a Loom recording**: For 90% of tutorials, a 45-second screen recording is good enough. Your value-add must be measurable: do users finish tasks faster / with fewer errors than watching a Loom? You have no eval harness running against that question. There is an `eval-harness-changes.html` in docs but no signal you are measuring task success on real users.

The only genuinely differentiated wedge is **"adaptive guidance when the user's screen drifts from the recording."** But that is the hardest problem in the stack, the one you are still actively refactoring (planner/monitor split), and the part competitors with deterministic selectors do not need to solve.

### Is it needed in the world?

Be honest:

- The "tutorial" problem is solved enough. Scribe is doing $30M+ ARR with a worse-than-yours-in-theory but ship-today product.
- The "live coaching" problem is real but small. Most users either know what they are doing or will watch a video. The audience that *needs* live overlay coaching is: elderly users, severely non-technical employees in regulated industries, accessibility use cases. None of those is your ICP per the README.
- The "agent that watches your screen and helps" problem is enormous — but that is Computer Use's market, not yours, and you have deliberately backed out of it.
- The "training data for GUI agents" angle is interesting. `run persistence for training & debugging` in the roadmap hints you know this. If the real product is **a dataset of human workflows + VLM-described actions for fine-tuning GUI agents**, say that out loud and treat the overlay player as a secondary concern. Right now the user-facing product and the data-collection mechanism are both half-built and competing for budget.

**Verdict on need:** As stated, no. As *a data flywheel for GUI agent training with the overlay as a UX justification for collecting recordings*, yes — but you have not admitted that is the play, and the codebase does not optimize for it either (no dataset schema versioning, no labeling UI, no export pipeline for training).

---

## 5. The harshest items, distilled

1. **You are building three products in one repo.** The agent (`backend/`), the data pipeline (`docker/*`), the overlay shell (`context-app/`). Each is staffed by one person — you — and each is being half-built.
2. **`tutorial_session.py` is 2,605 lines with a confessional in `remove-spaghetti.md`.** Your own clean-code mandate is unenforced. The "senior engineer partner" rubric is not being applied to your own work.
3. **AGENTS.md says Electron. The Swift app is in `context-app/`. The `electron/` directory still exists.** That is two frontends. Kill one.
4. **You have an `enrichment-layer` that runs Brave Search + Playwright + trafilatura.** That is a six-month build by itself, justified in the spec as "the dataset is the product" — which contradicts the README ("the overlay is the product"). One of those documents is wrong.
5. **Your wedge depends on the hardest technology (VLM grounding without AX), but you have capped your accuracy ceiling by forbidding AX even on macOS where it is free.** Future-proofing paid for in today's product quality.
6. **No competitive teardown exists in `docs/`.** Twelve design docs, zero "here is why we beat Scribe." That is a tell.
7. **No eval harness output anywhere visible.** You have `eval-harness-changes.html` (changes — to what baseline?). If you cannot say "task-completion rate is X% on benchmark Y," you cannot claim the live overlay is better than a Loom.
8. **The Swift app is still on US1/US2 (overlay + green bbox)** while the backend is doing planner/monitor splits. The frontend will not catch up before the backend is obsolete.

---

## 6. What to do Monday morning

In priority order:

1. **Fix `xcodebuild test`.** Nothing else matters until the Swift suite runs locally. Everything merged since 2026-05-05 is unverified by the suite that is supposed to verify it.
2. **Fix verifier observability.** Every verdict ships with raw model output verbatim in the log. Re-enable / update the stale `test_unsure_verdict_rejects` test. Until you can tell `"no"` from `"unsure"` in a log, you cannot debug the agent.
3. **Pick one thesis in writing,** in the README, this week. Either: (a) *macOS live-coach for non-technical users in regulated workflows*, or (b) *a dataset/eval engine for GUI agents, with the overlay as the collection UI*. Not both.
4. **Delete one frontend.** Electron or Swift. Today.
5. **Refactor `_run_agent_loop` into a `ToolRouter` + `AgentLoop` + `SessionState`.** Cap `tutorial_session.py` at 500 LOC. Finish the spaghetti removal in `remove-spaghetti.md` *before* the next feature.
6. **Defer `enrichment-layer` (Brave search) entirely.** It is a separate company. Spin it out or shelve it.
7. **Defer `gui-actor-inference`, `omniparser`, `ui-segmentation`, `ffmpeg-crop`.** Pick one grounding model. Hardcode it. Move on.
8. **Kill the A/B flags or pick the winner.** Test/prod skew via dataclass-vs-env defaults will produce a regression you cannot reproduce.
9. **Generate the Swift state model from the Python schema.** Stop hand-syncing two state machines.
10. **Write the competitor section in the README.** One paragraph each: Scribe, WalkMe, Computer Use. Force yourself to articulate why you win against each. If you cannot, the project does not ship.
11. **Define a single eval:** "User completes task X in N steps with overlay vs. without overlay." Run it on five real users this month. If overlay does not win, that is the signal — either pivot to the dataset thesis or stop.

---

## 7. Bottom line

The engineering is impressive; the product is not yet a product. You have built the means before deciding the end, and the means are now too expensive to maintain alongside the end you have not picked.

The CLAUDE.md vows about Uncle Bob, small functions, explicit state, deterministic behavior, and no magic are all being violated *by the file that is the heart of the product*. That file **is** the project right now. Fixing that file is fixing the project.

The path forward is subtraction, not addition.
