# Context

**An AI that plans a task and walks you through it live, on your own screen.**

Context is a primarily **LLM-driven planning → action** app. Point it at a task and the
planner reads your live screen, commits to a multi-step hypothesis, and streams it back as an
always-on-top overlay that points at the next step *inside the actual app you're using* —
firing each action on its own and quietly re-planning when the screen doesn't match. It's the
difference between reading a doc and having someone sit next to you and guide your hands.

> **Status — early MVP.** The planner and the live overlay loop are the working core. The
> longer-term wedge — **recording a workflow once** so Context can teach procedures no model
> knows — is still to be developed. Treat everything here as MVP-stage and in flux.

## Why this exists

Most "AI assistants" can only help with things the model already knows — Photoshop, popular
SaaS, common dev setup. They fall apart the moment you point them at your company's internal
admin tool, a bespoke enterprise app, or "the specific way our team does onboarding."

Context is built to close that gap. Today it plans from your live screen and guides your
hands through it. The next phase is the real wedge: a person who knows a procedure **records
it once**, and everyone after them gets a live, hands-on tutorial for *that exact procedure* —
including the ones no model was ever trained on. That recorded source of truth is the part
general models can't commoditize away.

## Quickstart — just talk to your agent

The fastest way to get this running is with [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
(or Cursor, or any coding agent). Open this repo and paste:

```
Hi Claude.

Read CLAUDE.md in this repo. I want to run Context locally on my Mac.

Walk me through it: set up the Python backend with my Gemini API key, get the
macOS app building in Xcode, point the app at the local backend, and show me how
to point it at a task and watch it plan and guide me through it live. Go step by step.
```

It already knows the architecture, the ports, the env vars, and the gotchas (they're all in
`CLAUDE.md`). Once you're running, just keep talking to it — build features, fix bugs,
whatever.

## Quickstart — manual

Three steps. The first two are all you need for a full demo; the third is optional.

**1. Backend** (Python 3.12 + [`uv`](https://docs.astral.sh/uv/))

```bash
cd backend
cp .env.example .env          # set GEMINI_API_KEY
uv sync
cd ..
uv run --project backend uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Check it: `curl http://127.0.0.1:8000/health`.

**2. macOS app** (Xcode 15+)

```bash
open context-app/ContextApp/ContextApp.xcodeproj
```

Pick the `ContextApp` scheme, set your signing team, **Cmd+R**. Grant Screen Recording +
Accessibility when asked, then set the app's **Tutorial API** endpoint to
`http://localhost:8000`. Point it at a task and watch the planner stream a live overlay tutorial.

**3. Precise pointing & enrichment** *(optional — needs an H Company / Holo key)*

```bash
cp docker/gui-grounding/.env.example docker/gui-grounding/.env   # set HAI_API_KEY
docker compose up gui-grounding recording-enrichment
```

> Full setup details, env vars, and endpoints live in [`CLAUDE.md`](./CLAUDE.md).

## How it works

```
 Plan  ──▶  Walk            ·  Record  (to be developed)
 (backend)  (overlay)          (Swift app)
```

1. **Plan** — the FastAPI backend's planner commits to a multi-step hypothesis from the
   current screen and **streams** the tutorial back as it's generated, so the overlay fills in
   live instead of waiting.
2. **Walk** — the overlay shows the next step, points at its target on screen, and fires the
   next action on its own. A lightweight monitor watches each screen and only re-plans on real
   divergence — it never blocks you between steps.
3. **Record** *(to be developed)* — the macOS app will capture a workflow once as events +
   screenshots, with Holo describing each action, so Context can teach procedures no model
   knows. Still half-built; today the planner works straight from the live screen.

## Project structure

```
context-app/ContextApp/   # macOS app (Swift/SwiftUI) — live overlay (+ recorder, WIP). The real frontend.
backend/                  # FastAPI planner + session engine (Python, uv)
  main.py                   # app entry: /tutorials/plan, /tutorial-sessions, WebSocket loop
  tutorial_*.py             # plan schema, session step loop, planner tools
docker/                   # optional grounding stack: gui-grounding, recording-enrichment,
                          #   enrichment-layer, caddy gateway
CLAUDE.md                 # full setup + architecture (written for your coding agent)
```

## Status

Early macOS-first **MVP**, and built to be treated as one — explicit state, deterministic
failure modes, no magic. The working core is the **LLM-driven planning → action loop**: the
backend planner streams a multi-step hypothesis and the overlay walks it on your live screen,
firing the next action on its own. **Workflow recording is still to be developed** — it's the
intended front of the funnel but half-built today. The Docker grounding stack is an optional
accuracy layer. Cross-platform, sharing, and authoring come later. See
[`CLAUDE.md`](./CLAUDE.md) for the developer-facing details.
