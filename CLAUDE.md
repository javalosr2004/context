# Context — Agent Setup & Architecture Guide

> This file is written for an AI coding agent (Claude Code, Cursor, etc.). If you are a
> human, you can hand this whole repo to your agent and say *"read CLAUDE.md and get me
> running"* — see `README.md`. Everything below is the ground truth the agent needs.

## What this project is

Context turns a **recorded workflow** into a **live, on-screen tutorial**. A creator records
a task once — real clicks, keystrokes, scrolls, screenshots, and window context. The system
replays it as an always-on-top overlay that points at the next action *inside the real app*,
tracks the learner's progress, and re-plans when the screen diverges from the recording.

The wedge: it teaches procedures the model does **not** already know — internal tools,
bespoke enterprise software, "the way *we* do it here." The recording is the source of truth,
not the model's general knowledge.

## Architecture at a glance

Two components do the real work. A third (Docker) is optional and only needed for precise
on-screen pointing and recording enrichment.

```
┌──────────────────────────┐        HTTP + WebSocket        ┌───────────────────────────┐
│  Swift macOS app          │  ───────────────────────────▶ │  Python FastAPI backend    │
│  (record + overlay)       │ ◀───────────────────────────  │  (planner + session engine)│
│  context-app/ContextApp   │   streamed plan + step events  │  backend/                  │
└──────────────────────────┘                                └───────────┬───────────────┘
                                                                          │ optional
                                                          ┌───────────────▼───────────────┐
                                                          │  Docker grounding stack         │
                                                          │  gui-grounding · enrichment ·   │
                                                          │  recording-enrichment · caddy   │
                                                          └─────────────────────────────────┘
```

| Component | Path | Runtime | Responsibility |
|---|---|---|---|
| **macOS app** | `context-app/ContextApp/ContextApp.xcodeproj` | Swift / SwiftUI + AppKit | Menu-bar app. Records workflows (events + frames), renders the overlay, points at targets, tracks step progress, talks to the backend. |
| **Backend** | `backend/` | Python 3.12, FastAPI, `uv` | Generates the multi-step tutorial plan from a recording + the live screen, streams it, and runs the per-session step loop over a WebSocket. |
| **Grounding stack** *(optional)* | `docker/` | Docker Compose | `gui-grounding` (where to click, via Holo), `recording-enrichment` (describes recorded actions), `enrichment-layer` (web corpus), `caddy` (gateway). The core record→plan→overlay loop runs **without** this. |

> The `electron/` directory is a legacy prototype of the overlay and is being removed. The
> Swift app is the real frontend — do not build new UI in Electron.

## Backend endpoints

`backend/main.py` (`app = create_app()`), served by uvicorn on port `8000`:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check. |
| `POST` | `/tutorials/plan` | One-shot: recording + screen → a full tutorial plan. |
| `POST` | `/tutorial-sessions` | Create a live teaching session. |
| `GET` | `/tutorial-sessions/{id}` | Fetch session state. |
| `WS` | `/tutorial-sessions/{id}/socket` | The step loop — streams plan/step events, receives user screens & confirmations. |
| `POST` | `/conversations/stream` | Streaming multimodal chat (SSE). |

## Setup

### Prerequisites
- macOS 14+ and **Xcode 15+** (for the app; uses ScreenCaptureKit + AppKit overlays)
- **Python 3.12** and [`uv`](https://docs.astral.sh/uv/)
- A **Gemini API key** (default planner). Optional: an OpenAI key, and an H Company / Holo
  key (`HAI_API_KEY`) if you want precise pointing + recording enrichment.
- *(Optional)* Docker, only for the grounding stack.

### 1. Backend (required)

```bash
cd backend
cp .env.example .env        # then edit .env and set GEMINI_API_KEY
uv sync
```

`.env` keys (see `backend/.env.example`):

| Var | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `openai`, or `holo`. |
| `LLM_MODEL` | `gemini-3-flash-preview` | Planner model. |
| `GEMINI_API_KEY` | — | Required when provider is `gemini`. |
| `HAI_API_KEY` / `HAI_BASE_URL` / `HOLO_MODEL` | — | Only for Holo grounding / enrichment. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address. |

Run it **from the repo root** so the `backend` package resolves (the app uses absolute
`backend.*` imports — uvicorn puts the working directory on `sys.path`):

```bash
# from the repository root, not from backend/
uv run --project backend uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify: `curl http://127.0.0.1:8000/health`.

### 2. macOS app (required)

```bash
open context-app/ContextApp/ContextApp.xcodeproj
```

In Xcode: select the `ContextApp` scheme, set your signing team under **Signing &
Capabilities**, then **Cmd+R**. On first launch grant **Screen Recording** and
**Accessibility** when prompted. Then open the menu-bar item and set the **Tutorial API**
endpoint to `http://localhost:8000` (the placeholder shown in the field).

### 3. Grounding stack (optional — precise pointing & enrichment)

Only needed if you want Holo-grade "click exactly here" targeting and recorded-action
descriptions. Requires `HAI_API_KEY`.

```bash
cp docker/gui-grounding/.env.example docker/gui-grounding/.env   # set HAI_API_KEY
docker compose up gui-grounding recording-enrichment             # add gateway/enrichment-layer if needed
```

The Caddy `gateway` (port `8080`) fronts these: `/grounding/*` → gui-grounding,
`/recordings*` → recording-enrichment, everything else → backend.

## End-to-end data flow

1. **Record** — the Swift app captures events + frames for a workflow and (optionally) sends
   frames to `recording-enrichment` so Holo describes each action.
2. **Plan** — to teach, the app calls `POST /tutorials/plan` or opens a session WebSocket.
   The backend planner commits to a **multi-step hypothesis** from the current screen and
   **streams** it back as it is generated.
3. **Walk** — the overlay renders the plan as a tutorial card, points at the target for the
   current step (grounding via `gui-grounding` or recorded coordinates), and advances as the
   learner acts. A lightweight monitor checks each post-action screen and only escalates to a
   re-plan on genuine divergence — it never blocks the next step.

## Conventions

- **Backend:** small functions, single responsibility, explicit state, deterministic failure
  modes. Tests for pure logic live in `backend/tests/`.
- **Swift:** SwiftUI for UI; AppKit (`NSPanel`) only where required for floating/overlay
  windows. All UI state on `@MainActor`; async/await throughout. Tests in
  `context-app/ContextApp/ContextAppTests/`.
- **TypeScript bindings are generated** from Rust/Python schemas via codegen — never hand-edit
  binding files.
- After finishing a code change, commit it with a one-line conventional-commit message.

## Do NOT

- Do **not** run `xcodebuild` from the terminal for the macOS app — it invalidates TCC
  (Screen Recording / Accessibility) permissions and forces a re-grant. Build from Xcode.
- Do **not** build new overlay UI in `electron/` — it is legacy.
- Do **not** assume the Docker stack is running; the core loop must work backend + app only.
- Do **not** commit real `.env` files or API keys.
