# Product Critique — Context / Tutorial Overlay

*Date: 2026-05-21*
*Focus: use case, scope creep, real users, missing must-haves, what to cut.*
*Companion to: `docs/project-audit.md` (engineering audit).*

---

## TL;DR

The pitch is "live overlay tutorial that teaches while you work." The codebase says you are building **a GUI-agent research platform with an overlay glued to the front**. The use case as written is too vague to be a wedge, the user is undefined, and ~60% of what is built does not serve the stated product. The features a real user would need to adopt this — sharing, distribution, auth, redaction, multi-OS, browser integration, deterministic targeting fallbacks — are **none of them implemented**. Meanwhile you have built a search engine, a VLM grounding stack, and two frontends.

Cut hard or pick a different product.

---

## 1. The use case — does it survive contact with a real user?

### The pitch (README)

> "Record a workflow once, replay as a live overlay tutorial. Examples: setting up Git, navigating internal tools, completing multi-step web flows."

### What survives a five-second user test

Imagine three real people:

**Person A: New hire at a 500-person company.** Manager sends them a Scribe link. They click it, see screenshots with arrows, follow along on their own machine in a browser tab. Done in 4 minutes.
**Would they install your Mac app?** No. The friction of "install a native app, grant screen recording + accessibility permissions, sign in" exceeds the value of "live overlay" by 100×. The Scribe link won.

**Person B: Senior engineer setting up Git.**
They run `brew install git`, paste their SSH key, move on. They will not record a tutorial and they will not watch one. Your example use case is wrong for this persona.

**Person C: A 65-year-old learning to use Photoshop.**
This is the only persona who genuinely benefits from a live overlay. They cannot translate a YouTube video into the action in front of them. The overlay solves a real cognitive-load problem.
**But:** they are on Windows. They do not know what a "macOS overlay" is. Their grandchild who would install it for them is not going to pay for it.

The use case the README claims (developer/employee productivity) is **the use case where you lose to Scribe and Loom**. The use case where you would actually win (accessibility / cognitive-assist) is **not what the README or roadmap describes** and the codebase does not optimize for it.

### What the use case actually needs to be

Pick one of these. None of them is "what the README currently says":

| Thesis | Product | Why it could work |
|---|---|---|
| **Cognitive-assist coaching** | Mac overlay that walks non-technical users through complex apps (CAD, Photoshop, tax software, EHR) | Live overlay is genuinely better than video for low-tech-confidence users. Hospitals/clinics pay for this. |
| **GUI-agent training data flywheel** | Recording + Holo-described action dataset; overlay is the collection UX | The dataset is monetizable to LLM labs even if no end user ever loves the overlay. |
| **Enterprise SOP enforcement** | Compliance officer records a procedure; the overlay *gates* employee actions until each step is confirmed | "Did you actually run the safety check?" — regulated industries (pharma, finance) pay for this. |
| **Live coach for support reps** | Customer-success agent watches the rep's screen; overlay nudges them in real time | Real B2B SaaS market, but requires multi-user coordination you have not built. |

The current pitch is none of these clearly. It is a Venn-diagram center that no one actually lives in.

---

## 2. Scope creep — what does not belong

CLAUDE.md, verbatim: *"Don't over-engineer early. Start flat, extract modules only when a boundary becomes necessary."*

Reality:

### Things in the repo that should not be there yet

| Built | Should have been | Why it is creep |
|---|---|---|
| `enrichment-layer/` — Brave Search + Playwright + trafilatura + SQLite tutorial corpus | Nothing, or a hardcoded JSON of 3 example tutorials | This is a search engine. You are one person. |
| `gui-actor-inference/` with DeTR + Colab launcher | One grounding call to one model | Two grounding stacks (`gui-actor-inference` + `gui-grounding`) where one would do |
| `recording-enrichment/` separate container | Inline Holo call from the Swift app | Microservices premature; you have one user (you) |
| `web_ground.py`, web search as a planner tool, `GROUNDING_STRATEGY` A/B | Nothing. The model knows enough. | Web grounding for *tutorial generation* is solving a problem no user has reported |
| PDF upload as planner input | Nothing | "We accept PDFs" is a feature looking for a user |
| `STEP_TOOLS_ENABLED` capped-head vs full-plan A/B | Pick one and ship | A/B tests require traffic. You have no users. |
| `instruction_verifier` + strict gate + parallel verifier (half-removed) | Skip verification, ask the user "did this work?" | The MVP explicitly said manual confirmation was fine "for now" |
| Async monitor LLM (planner/monitor split per roadmap) | One model, one call per turn | This is an optimization for a system that does not yet have correctness |
| Embeddings client + logical-id resolver for plan-merge | Replace the plan when it changes | Cosine-similarity step matching is solving a problem caused by emitting full plans every turn — a problem you created |
| Electron frontend *and* Swift `ContextApp` | One frontend | Forking yourself in half |
| SpecKit ceremony (`.specify/memory/constitution.md` v3.1.0) on a non-building app | Just write code | Process theater on top of a broken `xcodebuild` |
| Conversations store with session persistence "for training/debugging" | A JSON file | You are storing data you do not yet read |

### The pattern

Every one of these was a *reasonable* idea taken out of order. The discipline CLAUDE.md asked for — "extract modules only when a boundary becomes necessary" — has been inverted. You extracted modules in anticipation of boundaries that may never matter.

**Honest count of scope creep:** roughly 60% of the codebase serves a use case that does not yet have a user. The other 40% (recording + overlay + plan + walk loop) is the actual MVP.

---

## 3. Who would actually use this — and would they?

### Stated audience (README)

> "users completing tasks like setting up Git, navigating internal tools, completing multi-step web flows."

### Honest segmentation

| Segment | Will they install? | Will they pay? | Are you serving them? |
|---|---|---|---|
| Developers doing dev-onboarding | No — they read docs | No | The Git example is delusional |
| Non-technical employees in big cos | Maybe, if IT pushes it | Their employer would, but you need WalkMe-level distribution | No — no admin console, no SSO, no analytics |
| Elderly / low-confidence users | Yes, if their kid installs it | No — they don't buy software | Possibly, but you are Mac-only and they are mostly on Windows |
| Compliance-bound workers (pharma, finance, EHR) | Yes, if mandated | Their employer pays a *lot* | No — no audit trail, no signoff, no role-based access |
| LLM labs buying GUI-agent training data | N/A — they buy the dataset, not the app | Yes, six-to-seven figures | No — no schema versioning, no export, no labels |
| Customer-success / sales-enablement teams | Yes, if it integrates with their LMS | Their employer pays | No — no LMS integration, no completion tracking, no team rollout |
| Hobbyists making YouTube how-tos | Maybe — but they prefer Loom | No | No — no export to shareable artifact |

There is **no segment** where the current build is "the best option available." Every segment either has a better alternative today or needs features you have not built.

### The really uncomfortable question

If you launched today and got 100 signups, what would you ship them?

- They install the Mac app. (Lose Windows/Linux users.)
- They grant screen-recording permission. (Lose the security-conscious.)
- They record a tutorial. The Holo enrichment runs. The dataset gets a new row.
- They share it with… **how?** There is no share link. No export. No web viewer. The tutorial lives on disk.
- They replay it themselves. The verifier loops on `"unsure"` (see `instruction_verifier.ANALYSIS.md`). They give up.

You cannot launch. Not because the tech is too hard but because the **distribution loop does not exist**. Scribe's whole business is that paste-this-link-in-Slack moment. You have no link.

---

## 4. What real users would need — and isn't built

This is the gap list. These are features that any of the viable use cases above would *require*, and that are absent.

### Distribution and sharing — completely missing

- **Shareable artifact.** A URL, a PDF, a Notion embed — *something* you can paste into Slack. Without this, the tutorial never escapes the recorder's laptop.
- **Web viewer.** The replay surface must work without installing an app. Otherwise you are gating your own growth.
- **Browser extension.** For web-app tutorials (which are 80% of internal-tools and onboarding flows), a Chrome extension beats a native overlay every time.

### Authoring — half-built

- **Edit after recording.** You record once; reality is that you mess up step 4 and need to re-record just that step. Not supported. The current model is "record perfectly or start over."
- **Step narration / annotation.** A user needs to add "click here because X." Currently the action description comes from Holo, which is fine for actions but not for *teaching*.
- **Branching.** "If you see this dialog, click Cancel; otherwise continue." Real tutorials need conditional logic.
- **Variables / parameterization.** "Enter your email." You cannot record one user's literal email and replay it for a different user.

### Trust and safety — completely missing

- **PII redaction at record time.** Explicitly deferred in README. But the first time someone records a flow that touches a password field, you have a liability problem. This must land *before* any real user.
- **Secure field detection.** Forms with `type=password`, 2FA codes, credit cards. Must be blocked from frame capture by default.
- **Audit trail.** For compliance use cases — who recorded, who replayed, when, did they confirm each step.
- **Data residency.** Where do the screenshots live? Who can see them? No answer in the codebase.

### Cross-platform — abandoned by decision

- Mac-only forever, per current architecture. But:
  - Internal-tools market is 60% Windows.
  - Browser-app tutorials are OS-agnostic; you are leaving 90% of the market on the table for an overlay that does not benefit you over a browser extension.
- The "no AX" decision (`feedback_no_ax_in_recorder.md`) is a portability hedge for portability you will never ship. You pay the accuracy cost today for an option you will not exercise.

### Deterministic fallbacks — missing

- VLM grounding alone will fail on:
  - Small targets in dense UIs
  - Targets occluded by tooltips, dropdowns
  - Apps with custom rendering (Electron, Figma, games)
- Real systems use a *layered* approach: AX tree → DOM (for web) → OCR → VLM, in that order. You are using only the most expensive and least reliable layer.
- A real implementation would need:
  - macOS AX integration (you explicitly forbade this)
  - DOM selector capture via browser extension
  - OCR fallback for text targets
  - VLM only as last resort

### Replay quality — under-invested

- **"Did the app respond?"** Currently you ask the user to confirm. Real product needs automatic state detection (the verifier exists but is too unreliable per the analysis doc).
- **"What if the app updated?"** UI redesigns break recorded tutorials. No re-grounding workflow exists. Tutorial decays to garbage in 6 months.
- **Speed control.** Pause, rewind, skip — none of this is in `ChatPopupView.swift` based on file size and the recording detail view alone.

### Measurement — does not exist

- No completion rate tracking. (Did the user finish the tutorial?)
- No drop-off analytics. (Which step did they get stuck on?)
- No A/B testing of overlay variants. (The two A/B flags you have are *internal model selection*, not user-facing.)
- No eval suite running on a benchmark. (Per `docs/eval-harness-changes.html` — changes to what baseline?)

Without measurement, you cannot tell if the overlay is better than a Loom. You cannot tell if a planner change helped. You cannot tell if users like it. You are flying blind.

### Auth, billing, admin — not started

- No accounts.
- No teams.
- No SSO.
- No billing.
- No admin console.

These are not premature. They are *required to ship to anyone but yourself*. WalkMe is a $7B company because of these, not because of their overlay.

---

## 5. Where you are lacking, ranked by damage

1. **No shareable artifact.** You cannot grow without a link to paste. This is existential.
2. **No PII redaction.** First-customer blocker; legal will kill the deal.
3. **No measurement.** You cannot improve what you cannot see. The verifier loop incident is the canary.
4. **No deterministic targeting layer.** VLM-only grounding will hit a quality ceiling you cannot pass.
5. **No defined ICP.** Every other lack is downstream of this. You cannot prioritize features for a user you have not chosen.
6. **No cross-platform path.** Mac-only kills 90% of viable markets.
7. **No editing post-recording.** Recording rituals that are "perfect or start over" do not survive contact with humans.
8. **No competitive teardown in writing.** You have not articulated why you beat Scribe. If you cannot write the sentence, the product cannot win.

---

## 6. What to cut — concrete kill list

Cut these. Today. Not "deprecate" — delete the directories.

### Tier 1 — gone this week

- `electron/` — pick Swift, kill this fork.
- `docker/enrichment-layer/` — Brave Search + Playwright + corpus indexing. This is a separate company. Spin out or shelve.
- `docker/gui-actor-inference/` — second grounding stack with Colab launcher. Pick `gui-grounding` and consolidate.
- `docker/workers/omniparser/`, `docker/workers/ui-segmentation/`, `docker/workers/ffmpeg-crop/` — three workers in service of a grounding strategy you have not validated against users.
- `backend/web_ground.py` and the entire `GROUNDING_STRATEGY=planner` branch — you do not have evidence the planner needs web search.
- `STEP_TOOLS_ENABLED` A/B — pick one mode. The test/prod skew comment in source admits it.
- PDF upload as planner input — feature in search of a user.
- `backend/embeddings_client.py` + logical-id resolver — only exists because you emit full plans every turn. Cap the plan tail and this entire subsystem disappears.

### Tier 2 — gone within a month

- Parallel verifier scaffolding (`_start_verification`, `_run_verification`, `_cancel_verification`, `pending_verification_replan`, etc.) per `remove-spaghetti.md`. Stop saying "one commit" and actually delete it.
- The "draft plan" pre-pipeline (`_kick_off_draft_plan`, `_await_draft_plan`, `DraftPlanReadyEvent`) — speculative architecture before the basic plan works reliably.
- The two A/B flags in production (`STEP_TOOLS_ENABLED`, `GROUNDING_STRATEGY`) — pick winners.
- `conversations.py` + `session_event_log.py` persistence — you are recording data you do not yet consume.
- SpecKit ceremony in `context-app/.specify/` — process overhead on a project that cannot run its own tests.
- Half of `ChatPopupView.swift` — 2,477 lines of SwiftUI is a refactor target, not a feature.

### Tier 3 — re-evaluate after picking an ICP

- Async monitor LLM (planner/monitor split per `tutorial_agent_roadmap.md`) — defer until the single-model loop is reliable.
- `recording-enrichment/` as a separate container — inline it into the backend until you have a reason to split.
- All the AppKit polish (`StabilityIndicatorController`, `ErrorIndicatorController`, `EdgeTabController`, `FocusMaskController`) — these are UI affordances for a use case you have not validated.

---

## 7. What to build instead

If you keep going, the next 30 days should be exclusively:

1. **Pick an ICP in writing.** One sentence in the README. Refuse to add a feature unless it serves that ICP.
2. **Ship the share link.** A web viewer for recorded tutorials. The viewer can be dumb (steps + screenshots) — the point is the URL.
3. **PII redaction at capture time.** Blur secure fields before they hit disk.
4. **Add a deterministic targeting layer.** For your chosen ICP — AX on macOS for desktop apps, DOM via extension for web apps. VLM as fallback only.
5. **Measure one thing.** Per-tutorial completion rate. Funnel the data into a SQLite table you actually read.
6. **Run 5 users.** Real ones. Not yourself. Watch them try to record and replay. The first three will fail in ways the codebase does not predict.

If you cannot commit to those six, the honest move is to pivot to the dataset thesis: stop building a product, start selling enriched recordings to LLM labs. The codebase is already 70% configured for that — the overlay is the part that does not pull its weight in that universe.

---

## 8. Bottom line

The use case as written is too vague to win against the tools that already exist. The user is undefined. The features a real user would need are not built. The features that *are* built mostly serve a research agenda, not a product.

You are not lacking *engineering*. You are lacking *subtraction* and a *named user*. Until both happen, every new feature is technical debt with no offsetting customer value.

**The path forward is to cut 60% of the code, name one user, and ship one shareable artifact.** Everything else is procrastination dressed up as progress.
