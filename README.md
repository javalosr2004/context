# Context

**An AI that teaches you a workflow live, on your own screen.**

Record a task once — the real clicks, keystrokes, and screens. Context replays it as an
always-on-top overlay that points at the next step *inside the actual app you're using*,
follows along as you go, and quietly re-plans when your screen doesn't match. It's the
difference between watching a Loom and having someone sit next to you and guide your hands.

## Why this exists

Most "AI assistants" can only help with things the model already knows — Photoshop, popular
SaaS, common dev setup. They fall apart the moment you point them at your company's internal
admin tool, a bespoke enterprise app, or "the specific way our team does onboarding."

Context flips that. **The recording is the source of truth, not the model.** A person who
knows the procedure records it once; everyone after them gets a live, hands-on tutorial for
*that exact procedure* — including the procedures no model was ever trained on. That's the
part general models can't commoditize away.

## Quickstart — just talk to your agent

The fastest way to get this running is with [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
(or Cursor, or any coding agent). Open this repo and paste:

```
Hi Claude.

Read CLAUDE.md in this repo. I want to run Context locally on my Mac.

Walk me through it: set up the Python backend with my Gemini API key, get the
macOS app building in Xcode, point the app at the local backend, and tell me how
to record a workflow and replay it as an overlay. Go step by step.
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
`http://localhost:8000`. Record a workflow, then replay it as an overlay.

**3. Precise pointing & enrichment** *(optional — needs an H Company / Holo key)*

```bash
cp docker/gui-grounding/.env.example docker/gui-grounding/.env   # set HAI_API_KEY
docker compose up gui-grounding recording-enrichment
```

> Full setup details, env vars, and endpoints live in [`CLAUDE.md`](./CLAUDE.md).

## How it works

```
 Record  ──▶  Plan  ──▶  Walk
 (Swift app)  (backend)  (overlay)
```

1. **Record** — the macOS app captures a workflow as events + screenshots, and can have Holo
   describe each action.
2. **Plan** — the FastAPI backend's planner commits to a multi-step hypothesis from the
   current screen and **streams** the tutorial back as it's generated, so the overlay fills in
   live instead of waiting.
3. **Walk** — the overlay shows the next step, points at its target on screen, and advances as
   you act. A lightweight monitor watches each screen and only re-plans on real divergence —
   it never blocks you between steps.

## Project structure

```
context-app/ContextApp/   # macOS app (Swift/SwiftUI) — recorder + overlay. The real frontend.
backend/                  # FastAPI planner + session engine (Python, uv)
  main.py                   # app entry: /tutorials/plan, /tutorial-sessions, WebSocket loop
  tutorial_*.py             # plan schema, session step loop, planner tools
docker/                   # optional grounding stack: gui-grounding, recording-enrichment,
                          #   enrichment-layer, caddy gateway
CLAUDE.md                 # full setup + architecture (written for your coding agent)
```

## Status

macOS-first MVP. The core loop — record → plan → live overlay — is the product; the Docker
grounding stack is an optional accuracy layer. Cross-platform, sharing, and authoring come
later. See [`CLAUDE.md`](./CLAUDE.md) for the developer-facing details.
