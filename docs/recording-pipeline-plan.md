# Recording Pipeline Plan

Captures a user-stated goal and a sequence of UI actions on macOS, ships them to a backend enrichment service that describes each action with Holo, and surfaces the enriched recording back to the app.

## Product intent

A teaching system, not an automation agent:

- The user states a goal ("Reply to Sarah about the Q3 hiring numbers").
- The user performs the workflow once.
- We capture clicks, scrolls, keystrokes, frames, and crops.
- A backend worker describes each action with a vision model, using the goal as disambiguation context.
- The enriched recording becomes a replayable tutorial later (out of scope for this plan).

## Non-goals

- No accessibility tree (AX) usage anywhere in capture or enrichment. The pipeline must port to non-macOS targets later, so it is vision-only.
- No PII redaction yet. The schema isolates user-supplied text into one field so a redactor can land later without restructuring.
- No replay flow. This plan ends when an enriched recording is visible in the app.
- No live editing of recordings.

## Architecture

```
┌──────────────────────────────────┐         ┌──────────────────────────────┐
│  Swift macOS app                 │         │  recording-enrichment        │
│                                  │         │  (new docker container)      │
│  Recording/                      │ POST    │                              │
│    GoalSheetController           │ ──────▶ │  FastAPI                     │
│    InputEventTap                 │         │   /recordings (upload)       │
│    ContinuousFrameStream         │         │   /recordings/{id}/status    │
│    ScrollSessionizer             │         │   /recordings/{id}/events    │
│    Cropper                       │         │   /recordings/{id}/events/   │
│    RecordingSession              │ ◀────── │       stream  (SSE)          │
│    EnrichmentUploader            │  SSE    │                              │
│    EnrichmentStatusStream        │         │  Worker (asyncio)            │
│  Presentation/                   │         │   describe via Holo chat     │
│    RecordingsListView            │         │   verify via gui-grounding ──┼──▶ gui-grounding
│    RecordingDetailView           │         │     (env-gated)              │     (existing)
│                                  │         │                              │
│  Bundles on disk                 │         │  SQLite + /data volume       │
└──────────────────────────────────┘         └──────────────────────────────┘
```

Three failure domains: capture (local), upload (network), enrichment (backend). Each survives the others being down.

## Core design decisions

| Decision | Rationale |
| --- | --- |
| Cursor coordinates come from `CGEvent`, never from a model. | OS-truth is free, deterministic, and exact. |
| No AX probe for "what was clicked." | AX won't exist on future targets; vision must be the only "what" signal. |
| Persistent `SCStream` at ~12 fps, ring buffer of recent frames. | One-shot captures churn SCStream cold-starts (~200ms each) and can't keep up with click bursts. |
| Two crops per event: 256x256 target, 768x768 context. | Removes the "is 200 too small?" gamble without AX bbox sizing. |
| Goal stated before recording begins. | Holo describes each action with workflow context; "Send" button gets disambiguated. |
| Holo for both description and (optional) self-verification. | Same dialect on both sides closes the quality loop. |
| Enrichment in a separate container modeled on `gui-grounding`. | Different lifecycle, scaling axis, and storage than the backend. |
| Goal is recording-wide, never woven into per-event `target_phrase`. | Keeps the phrase re-localizable; isolates PII to one field. |

## Schemas

### Manifest (`manifest.json`)

```jsonc
{
  "recording_id": "uuid",
  "schema_version": 1,
  "started_at_ms": 1715000000000,
  "ended_at_ms": 1715000045000,
  "display": { "x": 0, "y": 0, "width": 3024, "height": 1964, "scale_factor": 2 },
  "goal": {
    "text": "Reply to Sarah about the Q3 hiring numbers",
    "entered_at_ms": 1714999999000
  },
  "app_version": "0.3.1",
  "aborted": false
}
```

### Recorded event (`events.jsonl`, one per line)

```jsonc
{
  "id": "uuid",
  "timestamp_ms": 1715000003120,
  "kind": "click",                 // click | scroll | key_down | flags
  "cursor": { "x": 812, "y": 433 },
  "button": "left",                // when kind=click
  "scroll": null,                  // when kind=scroll, see below
  "key": null,                     // when kind=key_down|flags
  "frame_id": "a1b2c3d4e5f6",
  "target_crop_path": "crops/{event_id}_target.jpg",
  "context_crop_path": "crops/{event_id}_context.jpg"
}
```

`scroll` payload, set on sessionized scroll events:

```jsonc
{
  "start_frame_id": "...",
  "end_frame_id": "...",
  "dx": 0,
  "dy": -480,
  "duration_ms": 720,
  "direction": "down"
}
```

### Enriched event (`events.enriched.jsonl`)

Same shape as `RecordedEvent`, with two added fields:

```jsonc
{
  "...": "...",
  "description": {
    "target_phrase": "the 'Reply' button in the message header",
    "kind": "button",
    "visible_text": "Reply"
  },
  "description_meta": {
    "model": "holo3-35b",
    "prompt_version": "describe-v2",
    "generated_at_ms": 1715000050000,
    "verified": true,                  // null when ENRICH_VERIFY_ENABLED=0
    "distance_px": 12                  // null when not measured
  }
}
```

### Bundle layout on disk

```
recording-{uuid}/
  manifest.json
  events.jsonl
  frames/{frame_id}.jpg
  crops/{event_id}_target.jpg
  crops/{event_id}_context.jpg
```

After enrichment, the container additionally produces `events.enriched.jsonl` adjacent to `events.jsonl`.

## Phases

Each phase is independently shippable. Acceptance criteria are objective.

### Phase 0 - Foundations (~0.5 day)

**Goal:** Project skeleton, schemas, permission scaffolding. No behavior.

**Deliverables**

- `context-app/ContextApp/ContextApp/Application/Recording/` created.
- `Recording/Schema.swift` defining `RecordedEvent`, `Kind`, `Point`, `MouseButton`, `ScrollDelta`, `KeyStroke`, `Manifest`, `Goal`, `BundleLayout`. Constant `kSchemaVersion = 1`.
- `Recording/Permissions.swift` wrapping `CGPreflightScreenCaptureAccess`, `CGRequestScreenCaptureAccess`, and `AXIsProcessTrustedWithOptions` (for the event tap permission, not the AX tree). Returns `RecordingPermissions { allGranted, needsScreen, needsAccessibility, needsBoth }`.
- `docker/recording-enrichment/` skeleton: `Dockerfile`, `pyproject.toml`, `src/app.py` with `/health`.
- Added to `docker-compose.yml` on port `7100` with a `/data` volume.

**Acceptance**

- App builds. No UI change.
- `docker compose up recording-enrichment` returns 200 on `/health`.

**Out of scope:** any capture, upload, or enrichment behavior.

### Phase 1 - Local capture, raw (~2 days)

**Goal:** Record real macOS events with frames into a valid bundle. Goal sheet gates recording. No crops yet.

**Modules**

`Recording/ContinuousFrameStream.swift`

```swift
final class ContinuousFrameStream {
    func start(on screen: NSScreen, fps: Int = 12) async throws
    func stop() async throws
    func latestFrame(near hostTimeMs: Int64) -> CapturedFrame?  // O(1)
}
```

- Long-running `SCStream`, `queueDepth = 4`, `showsCursor = true`.
- Ring buffer of last ~60 frames keyed by `mach_absolute_time` converted to ms.
- `frame_id = sha1(jpeg)[:12]`; identical frames dedupe by content.

`Recording/InputEventTap.swift`

```swift
final class InputEventTap {
    var onEvent: ((RawInputEvent) -> Void)?
    func start() throws
    func stop()
}
```

- `CGEvent.tapCreate(.cgSessionEventTap, .listenOnly, ...)` with masks for `leftMouseDown | rightMouseDown | otherMouseDown | scrollWheel | keyDown | flagsChanged`.
- Dedicated `RunLoop`; callback marshals to a serial actor before invoking `onEvent`.

`Recording/GoalSheetController.swift`

- AppKit sheet on the main window. Text field with validation (trimmed length in [8, 280]). Esc cancels, Return submits.
- Returns `Goal { text, enteredAtMs }` or throws on cancel.

`Recording/RecordingSession.swift`

```swift
final class RecordingSession {
    func start(goal: Goal) async throws -> URL    // returns bundle dir
    func stop() async throws -> URL               // returns finalized bundle dir
    var isRecording: Bool { get }
}
```

- State machine `idle | recording | stopping`. One recording at a time.
- On start: create `recording-{uuid}/` in `Application Support/Recordings/`, write `manifest.json` (including `goal`), start frame stream + event tap.
- On each `RawInputEvent`: pull `latestFrame(near:)`, persist frame if new, build `RecordedEvent`, append JSONL line.
- On stop: stop tap and stream, flush events, finalize manifest with `endedAtMs`.

`StatusBarController.swift` (existing) gains a "Record..." action that opens the goal sheet, then calls `RecordingSession.start(goal:)`.

**Failure modes**

- Event tap rejected (no Accessibility permission): recording refuses to start with a clear error directing the user to System Settings.
- SCStream drops a sample: log `frame_gap_ms`, event gets `frame_id = null`, recording continues.
- Disk write failure: recording stops, manifest gets `aborted: true`, partial bundle preserved.
- Goal sheet cancelled: nothing starts, no bundle dir created.

**Acceptance**

- Click "Record...", type a goal, click Start.
- Perform clicks, scrolls, keystrokes across other apps.
- Click Stop.
- Bundle dir contains `manifest.json` (with goal), `events.jsonl` (one line per event), `frames/*.jpg`.
- Every event's `frame_id` resolves to a real file or is explicitly `null` with a logged reason.

**Out of scope:** scroll sessionization, crops, upload, backend.

### Phase 2 - Scroll sessionization + crops (~1 day)

**Goal:** Scrolls become useful semantic units. Every event has target + context crops.

**Modules**

`Recording/ScrollSessionizer.swift`

- Buffers raw `scrollWheel` events.
- Opens a session on the first scroll after idle.
- Closes after 350ms of no scroll, or on `phase = .ended` with momentum done.
- Emits one `RecordedEvent { kind: .scroll, scroll: { startFrameId, endFrameId, dx, dy, durationMs, direction } }`.
- Pass-through for key and click events.

`Recording/Cropper.swift`

```swift
enum Cropper {
    static func crop(frame: CapturedFrame, around cursor: Point) -> (target: Data, context: Data)
}
```

- `target`: 256x256 centered on cursor, clipped to frame bounds.
- `context`: 768x768 centered on cursor, clipped to frame bounds.
- JPEG quality 0.7. Pure function. Edge clipping does not shift the center; crops near edges are simply smaller.

`RecordingSession` wiring

- After building each `RecordedEvent`, call `Cropper`, persist `crops/{event_id}_target.jpg` and `_context.jpg`, write paths into the event.
- For scroll events, crop using the start frame (the moment scroll began is the interesting state).

**Tests**

- `Cropper`: center, near-edge, corner, zero-size frame.
- `ScrollSessionizer`: single delta, burst, momentum phase, two distinct sessions back-to-back.

**Acceptance**

- Bundles now have populated `crops/`.
- A scrolling burst collapses to one `RecordedEvent` with plausible `dx/dy/duration/direction`.

**Out of scope:** any backend work.

### Phase 3 - Backend service skeleton (~1 day)

**Goal:** `recording-enrichment` accepts uploads, stores them, exposes status. No actual enrichment.

**Layout**

```
docker/recording-enrichment/
  Dockerfile
  pyproject.toml
  src/
    app.py                 # FastAPI
    storage.py             # SQLite + filesystem
    schemas.py             # Pydantic models
  tests/
  README.md
```

**Storage** (`src/storage.py`)

SQLite at `/data/recordings.db`:

```sql
CREATE TABLE recordings (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,          -- pending | enriching | ready | failed
  goal TEXT NOT NULL,
  total_events INTEGER NOT NULL,
  completed INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE enrichment_jobs (
  id TEXT PRIMARY KEY,
  recording_id TEXT NOT NULL REFERENCES recordings(id),
  event_id TEXT NOT NULL,
  status TEXT NOT NULL,          -- pending | running | done | failed
  error TEXT,
  distance_px REAL,
  verified INTEGER,              -- 0/1/NULL
  sequence INTEGER NOT NULL,     -- monotonic per recording, for SSE Last-Event-ID
  started_at INTEGER,
  finished_at INTEGER
);
```

Bundles unpacked to `/data/bundles/{recording_id}/`.

**Endpoints**

```
POST   /recordings                   multipart bundle.zip -> 202 {recording_id, status, total_events}
GET    /recordings/{id}              -> {id, status, goal, total, completed, failed, created_at, ...}
GET    /recordings/{id}/status       -> {status, total, completed, failed}
GET    /recordings/{id}/events       -> enriched JSONL when status=ready; 409 otherwise
```

Upload validates `manifest.json` and `events.jsonl` parse, `schema_version` is supported, and inserts one row per event into `enrichment_jobs`.

**Swift uploader** (`Recording/EnrichmentUploader.swift`)

```swift
final class EnrichmentUploader {
    func upload(bundleDir: URL) async throws -> RemoteRecording   // {id, status}
}
```

- Zips the bundle on a background queue. Multipart POST.
- Persists `(localBundleURL -> remoteRecordingId)` in a small Codable index file under `Application Support/Recordings/index.json`.

**Acceptance**

- Record locally, upload, `/status` returns `pending`.
- Bundle visible in the container at `/data/bundles/{id}/`.
- Re-upload creates a new `recording_id` (no dedup; out of scope).

**Out of scope:** worker, SSE, verification.

### Phase 4 - Holo describer worker (~2 days)

**Goal:** Events flow through the describer. `events.enriched.jsonl` is produced. Status flips to `ready`.

**Modules**

`docker/recording-enrichment/src/holo_describe.py`

- Copy `HoloChatClient` from `backend/holo_chat_client.py` into the service. Do not extract to a shared package until a third caller appears.
- One method:

```python
class Description(BaseModel):
    target_phrase: str
    kind: Literal["button","input","link","tab","icon","list_item","cell","menu_item","text","other"]
    visible_text: Optional[str]

def describe(target_jpeg: bytes, context_jpeg: bytes, goal: str) -> Description: ...
```

- `temperature=0.0`.
- `extra_body.structured_outputs` with the JSON schema for `Description`.
- `prompt_version = "describe-v2"`.

System prompt:

```
You are describing a single UI action that is part of a larger workflow.

USER GOAL FOR THE WORKFLOW:
"{goal}"

Given the target crop (tight) and context crop (wider) of the moment a user
performed an action, return a JSON object with:
  - target_phrase: short noun phrase naming the UI element, in the dialect a
    visual grounder would use to re-locate it. Include visible text in quotes
    and a disambiguating spatial/visual cue when needed.
  - kind: one of [button, input, link, tab, icon, list_item, cell, menu_item, text, other]
  - visible_text: the literal visible text on the element, or null.

The user goal is context for disambiguation only. Do NOT include the goal in
the target_phrase. Describe the element as it appears on screen, not the user's
intent.
```

`docker/recording-enrichment/src/worker.py`

- `asyncio` task started on FastAPI startup. One worker per container replica.
- Picks oldest `pending` recording, transitions to `enriching`.
- For each event (in order):
  1. Load `target.jpg` + `context.jpg`.
  2. Call `describe(target, context, goal)`.
  3. Append enriched event to `events.enriched.jsonl.partial`.
  4. Update `enrichment_jobs` row.
- On success: atomic rename `.partial` -> `events.enriched.jsonl`, status `ready`.
- On per-event failure: log, increment `failed`, mark job `failed`, continue.

**Concurrency**

- `HOLO_MAX_CONCURRENCY=1` env, enforced by an `asyncio.Semaphore`. Tuning is one env-var away.

**Failure modes**

- Holo timeout or 5xx: mark event failed, description null, continue.
- Worker crash mid-recording: on restart, reset any `running` job to `pending`, rebuild `.partial` from scratch, resume.
- Malformed structured output: retry once with the same prompt; if it fails again, mark the event failed.

**Acceptance**

- Upload a recording, wait, `GET /events` returns enriched JSONL with `description` on each event.
- A poisoned event (e.g. corrupt crop) does not block the recording from reaching `ready` (it lands with `description = null` and the job marked `failed`).

**Out of scope:** SSE, verification.

### Phase 5 - Live status via SSE (~1 day)

**Goal:** UI shows live progress per event during enrichment.

**Modules**

`docker/recording-enrichment/src/event_bus.py`

- In-memory `dict[recording_id, asyncio.Queue]`.
- Worker publishes after each successful event and emits periodic progress snapshots.

SSE endpoint

```
GET /recordings/{id}/events/stream
```

Event types:

```
event: enriched
data: {"sequence": 47, "event_id": "...", "target_phrase": "...", "kind": "button",
       "verified": null, "distance_px": null}

event: progress
data: {"completed": 47, "total": 120, "failed": 0}

event: done
data: {"status": "ready"}
```

- Honors `Last-Event-ID` header for reconnects (the SQLite `sequence` column is the ID).
- Heartbeats: emit a `progress` event at least every 2 seconds even when nothing changed.
- On `done`, the server closes the stream.

**Swift consumer** (`Recording/EnrichmentStatusStream.swift`)

```swift
@MainActor final class EnrichmentStatusStream: ObservableObject {
    @Published var status: Status = .pending
    @Published var completed: Int = 0
    @Published var total: Int = 0
    func connect(recordingId: String) async
    func disconnect()
}
```

- URLSession streaming task parsing SSE frames.
- Reconnect on drop with the last seen `sequence` in `Last-Event-ID`.

**Acceptance**

- Upload, open the recording's status panel, watch counters tick up live.
- Kill the network for 5 seconds, restore: stream resumes without duplicate events.
- `done` event closes the stream cleanly.

### Phase 6 - Optional self-verification (~0.5 day)

**Goal:** When enabled, every description is scored against `HoloLocalizer` and the result lands in `description_meta`.

**Env**

```
ENRICH_VERIFY_ENABLED=0                  # default off
ENRICH_VERIFY_MAX_DISTANCE_PX=30
GROUNDING_URL=http://gui-grounding:8080
```

**Module** (`src/holo_verify.py`)

- POSTs to `${GROUNDING_URL}/predict` (the existing `gui-grounding` service - do not re-import `HoloLocalizer` in this container).
- Inputs: the event's `frame_id` JPEG + `target_phrase`.
- Output: `point_pixel` from `GuiActorResponse`.
- Distance: Euclidean to the recorded `cursor` (same pixel space).

**Worker hook**

```python
verified = None
distance_px = None
if settings.verify_enabled:
    point = verify_client.locate(frame_bytes, desc.target_phrase)
    distance_px = euclidean(point, event.cursor)
    verified = distance_px <= settings.verify_max_distance_px
```

`description_meta.verified` and `description_meta.distance_px` are both `Optional`. Downstream code must treat `None` as "not measured," not as `False`.

**Acceptance**

- `ENRICH_VERIFY_ENABLED=0`: `verified=null` on every event.
- `ENRICH_VERIFY_ENABLED=1`: every event has `verified in {true,false}` and `distance_px` is a number.
- SSE `enriched` events carry the verify fields when enabled.

### Phase 7 - Recordings UI (~1-2 days)

**Goal:** User sees recordings, sees enrichment progress, opens only what's ready.

**Views**

`Presentation/Recordings/RecordingsListView.swift`

- Row content: goal (primary), duration + event count (secondary), status pill.
- Status pill values: `uploading | pending | enriching X/Y | ready | failed`.
- Backed by `index.json` + an `EnrichmentStatusStream` per non-terminal row.
- "Open" disabled unless `status == ready`.

`Presentation/Recordings/RecordingDetailView.swift`

- Header band: goal, recorded date, total events.
- Timeline of enriched events with timestamp, kind, cursor coords, `target_phrase`, both crops.
- When `verified` is non-null, show a badge (check/cross) with distance.
- Frame scrubber for navigation.

**Wiring**

- Status-bar action: "Show Recordings..." opens the list window.
- No integration with the existing tutorial replay flow yet.

**Acceptance**

- End-to-end demo:
  1. Hit Record, enter a goal, perform a workflow, hit Stop.
  2. Recording appears in the list with `uploading` -> `pending` -> `enriching X/Y` updating live.
  3. Status flips to `ready`.
  4. Open the recording, scrub through events, see `target_phrase` and crops for each.

## Cross-cutting concerns

These do not get their own phase; each lands inside the phase that introduces it.

- **Logging.** Swift uses `os.Logger` with a per-module category (`ContextApp.Recording.*`). Python uses `structlog`. Every failure mode listed above has a corresponding log line at boundary code.
- **Tests.** Pure logic gets unit tests in its introducing phase. Specifically: `Cropper`, `ScrollSessionizer`, `holo_describe` prompt construction, SSE reconnect handling.
- **Schema versioning.** `manifest.json` pins `schema_version`. Bumps only in dedicated phases. Older bundles remain readable.
- **Permissions UX.** Phase 0 builds detection. Phase 1 surfaces the not-granted states. Later phases assume granted. No scattered prompts.
- **PII surface.** Goal text is the freeform user input. Schema isolates it to `Goal.text`. The describer prompt explicitly bans goal text from `target_phrase`. When the redactor lands later, it has one obvious field.

## Dependency graph

```
P0 ─┬─ P1 ─ P2 ─┐
    │           ├─ P3 ─ P4 ─┬─ P5 ─┐
    │                       │      ├─ P7
    │                       └─ P6 ─┘
    │
    └─ P3 may start in parallel with P1; the bundle format is fixed by P0,
       so the backend can be built against synthetic fixtures.
```

P6 is fully optional and may ship any time after P4.

## Estimate

- Sequential: ~9-10 working days.
- With P1 and P3 in parallel: ~6-7 working days.

MVP demo target (record -> upload -> enriched recording browsable in the app) is the union of P0-P5 + P7. P6 is a quality-measurement add-on, not on the critical path.

## Open questions

These do not block starting Phase 0, but should be answered before the phase that needs them.

- **Keystroke privacy.** Keystrokes capture literal characters today. Before Phase 4 ships, decide whether to redact (or omit) printable characters in `key.characters` or rely on the future redactor.
- **Bundle size cap.** A long recording could produce hundreds of MB of frames + crops. No cap yet. Revisit before Phase 3 ships if uploads become slow.
- **Re-enrichment.** When the describer prompt changes, do we re-run on existing bundles? Plan: yes, via a `POST /recordings/{id}/reenrich` endpoint that resets jobs to pending. Not in this plan's scope but worth keeping in mind for schema choices.
