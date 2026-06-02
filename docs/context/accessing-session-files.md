# Accessing session capture files

Every tutorial session writes an append-only record of what flowed through it —
including **what the LLM actually saw** (assembled prompts) and what it
returned. This is the data to inspect for context engineering.

## What gets written

Root directory (`{root}`) defaults to `~/.context/sessions`, overridable with
the `CONTEXT_SESSIONS_DIR` env var.

```
{root}/{session_id}/
  events.jsonl              # chronological log, one event/line, both directions
  frames/<sha256>.<ext>     # screenshots, content-addressed by hash
  llm_calls/<call_id>.json  # one sidecar per LLM round-trip (prompt + response)
```

- **`events.jsonl`** — the authoritative timeline. Each line is
  `{ts, direction, event}`. Server- and client-side events are interleaved, so
  reading top-to-bottom replays the session. LLM calls also appear here as a
  compact `{"type": "llm_call", ...}` line that points at the sidecar.
- **`llm_calls/<call_id>.json`** — the full record per call: `agent`
  (`planner` / `draft_planner` / `verifier`), `model`, `method`, `elapsed_ms`,
  `prompt_system`, `prompt_user`, `response_text`, `tool_calls`, `image_count`,
  `ok`, `error`. This is "what the LLM saw" for that turn.
- **`frames/`** — screenshot bytes, referenced by hash from events so the JSONL
  stays small and greppable.

> Note: LLM-call records currently store only `image_count`, not the frame
> hashes, so a call can't yet be joined back to the exact frames it saw. The
> text context (system + user prompt) is fully captured.

## Where the files live depends on how the backend runs

### Running in Docker (docker-compose)

The `backend` service pins `CONTEXT_SESSIONS_DIR=/data/sessions` and mounts a
**named volume** `backend_sessions` (rendered name: `context_backend_sessions`)
at that path. The files persist across container recreates, but the volume
lives inside the Docker Desktop VM — **not** directly on the Mac filesystem, so
you can't open them in Finder/VS Code by browsing to them.

**Confirm capture is firing:**

```bash
docker compose exec backend ls -R /data/sessions/
docker compose exec backend sh -c 'ls /data/sessions/*/llm_calls/*.json | head'
```

**Read one record inline:**

```bash
docker compose exec backend cat /data/sessions/<session_id>/llm_calls/<call_id>.json
```

**Copy out to open in VS Code:**

```bash
docker compose cp backend:/data/sessions ./.sessions-dump
# then open ./.sessions-dump/<session_id>/llm_calls/<call_id>.json
```

This is a snapshot — re-run the `cp` to pull newer calls. (`.sessions-dump/` is
gitignored.)

Alternatively, the VS Code **Docker / Dev Containers** extension can browse the
volume directly (Volumes explorer) or attach VS Code to the running `backend`
container for a live view at `/data/sessions/...`, no copy needed.

### Running locally (host uvicorn)

Files land directly on the Mac at the default root — open them in VS Code like
any other file:

```
~/.context/sessions/<session_id>/llm_calls/<call_id>.json
```

## Quick inspection recipes

```bash
# Every LLM call in a session, oldest first
ls -t ~/.context/sessions/<session_id>/llm_calls/

# Just the planner prompts across a session (local run)
for f in ~/.context/sessions/<session_id>/llm_calls/*.json; do
  jq -r 'select(.agent=="planner") | .prompt_user' "$f"
done

# Watch how the assembled prompt changes turn to turn
jq -r '.prompt_user' ~/.context/sessions/<session_id>/llm_calls/*.json
```

> Context-engineering note: `LLMRequest` is stateless and single-turn — there's
> no growing message array. Each turn the caller re-assembles the full context
> into `prompt_user` from scratch. "Context over time" is therefore the diff
> between consecutive `prompt_user` values, not an accumulating history.
