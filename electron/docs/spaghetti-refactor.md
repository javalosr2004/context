# Capture Boundary And Backend Stability Plan

## Summary

This iteration keeps the existing product direction:

- `capture app` remains the current Electron app surface for recording, importing, annotating, and saving sessions
- `viewer app` remains a future second fully privileged app surface for LLM interaction, but it is **not** made real in this iteration

The work in this pass is to make the current capture path safe and deterministic enough for MVP by moving path authority into main, formalizing app-owned ids, fixing Rust backend lifecycle/RPC semantics, and reducing the riskiest annotator coupling.

## Key Changes

### 1. Replace renderer path authority with app-owned ephemeral ids

- Main generates opaque ids with `crypto.randomUUID()`:
  - `recordingId` for active capture sessions
  - `importId` for extracted/imported archives
- Main keeps an in-memory registry for the current app run:
  - `recordingId -> { tempVideoPath, startTime, rustSessionState, status }`
  - `importId -> { extractedDir, videoPath, eventsPath, archivePath, status }`
- Renderer no longer sends `eventsPath` or `archivePath` back into main.
- IPC contract changes:
  - `recording:start -> { recordingId }`
  - `recording:finish({ recordingId, defaultName }) -> { archivePath }`
  - `recording:import({ archivePath }) -> { importId, videoUrl, events }`
  - `recording:save-events({ importId, events }) -> { ok }`
- `videoUrl` is produced by main and returned to the renderer so playback behavior stays effectively the same.
- Id scope is ephemeral only for this iteration; no persistence across app restarts.

### 2. Separate capture and viewer contracts without building out the viewer

- Keep the viewer path in the repo.
- Introduce separate preload/interface definitions for capture and viewer now, even if the viewer remains mostly stubbed.
- Capture preload exposes only capture-related APIs.
- Viewer preload exposes only viewer-related APIs needed for the existing stub path.
- Do not add viewer state architecture, LLM session logic, or real viewer workflows in this iteration.
- Goal: remove accidental shared API surface now so future viewer work starts from a clean boundary.

### 3. Make Rust backend lifecycle deterministic

- Define a single capture session lifecycle:
  - spawn backend
  - wait for ready/health acknowledgment
  - start listener explicitly
  - stop listener explicitly
  - wait for stop acknowledgment
  - drain events
  - terminate child process
  - clear pending RPC requests/session state
- `stop_mouse_listener` must not return success until the worker has actually stopped admitting events.
- Electron main must not leave backend child processes alive after a finished or canceled recording session.
- Add RPC timeouts and closed-process handling for every request from Electron main to Rust.
- Use one consistent success/failure envelope for Rust RPC responses; no “error hidden inside result” behavior.

### 4. Add explicit overflow/degraded-session semantics, but only investigate disk spill

- This iteration does **not** implement spill-to-disk overflow buffering.
- This iteration does define the design and invariants needed for a later spill-to-disk implementation.
- For now, the plan should include:
  - identifying where the queue is currently unbounded
  - deciding the intended bounded-queue insertion point
  - defining overflow telemetry fields such as `overflowCount`, `sessionDegraded`, and first-overflow sequence/time
  - defining how Electron learns that a session was degraded
- Investigation output must be decision-complete for a future implementation of disk spill:
  - monotonic sequence numbering
  - writer ownership
  - drain barrier semantics
  - merge ordering between memory and disk
  - cleanup rules
- No event-dropping implementation is required in this iteration unless needed as a minimal temporary safeguard to remove the current unbounded-memory risk.

### 5. Reduce annotator risk without a full rewrite

- Keep the current annotator flow, but split the worst responsibilities into smaller modules/hooks:
  - import/load orchestration
  - recording session orchestration
  - event normalization
  - annotation editing/persistence
- Normalize snapshot payloads on load so optional `parents` and `children` become safe defaults before rendering.
- Remove in-place mutation of React state and raw snapshot payloads.
- Preserve current user behavior:
  - record
  - import
  - view video
  - edit labels/bboxes
  - save back into archive
- Avoid broad UI redesign or state-system replacement in this pass.

### 6. Formalize generated/runtime artifact policy for Electron + Rust integration

- Keep generated Rust TypeScript bindings in repo, but move them under an explicit generated path such as `src/shared/generated/`.
- Treat generated bindings as intentional generated source with one documented regeneration command.
- Do not change product behavior around using the Rust backend inside Electron.
- For the compiled Rust binary:
  - this iteration documents the policy and build/package flow
  - preferred long-term source of truth is Rust source plus build/package step
  - if checked-in binary remains temporarily for MVP convenience, mark it as temporary and non-authoritative in docs/build notes
- No broad packaging refactor is required in this iteration beyond making the ownership model explicit.

## Public Interfaces And Types

- Capture preload API becomes capture-specific and pathless:
  - `startRecording(): Promise<Result<{ recordingId: string }>>`
  - `finishRecording(recordingId, defaultName): Promise<Result<{ archivePath: string }>>`
  - `importRecording(archivePath): Promise<Result<{ importId: string; videoUrl: string; events: RecordedMouseEvent[] }>>`
  - `saveEvents(importId, events): Promise<Result<null>>`
- Viewer preload API becomes separate, but minimal for now.
- Main-process registries are the only place that know real archive/extraction/temp file paths.
- Rust RPC contract uses one response shape for success and one for failure.
- Event/session status should have an explicit degraded-state shape available to Electron for future overflow handling.

## Test Plan

- Electron main tests:
  - renderer cannot save by arbitrary path
  - `importId` resolves to the correct cached extraction and save target
  - invalid or expired ids are rejected cleanly
  - backend child process is terminated after recording stop/finish
- Rust tests:
  - `start`/`stop` acknowledgment semantics are deterministic
  - drain after stop contains no post-stop events
  - unknown RPC methods return proper RPC failures
- Renderer tests:
  - imported recordings still load and play using `videoUrl`
  - missing `parents`/`children` no longer crash annotator
  - label/bbox edits do not rely on in-place mutation
- Integration scenarios:
  - record -> stop -> save archive still works end to end
  - import -> edit -> save archive still works end to end
  - repeated start/stop does not orphan Rust processes
  - viewer path still boots, but without capture preload leakage

## Assumptions And Defaults

- `viewer` remains a future fully privileged second app surface, but is intentionally not expanded in this iteration.
- Ephemeral in-memory ids are the chosen default; restart persistence is out of scope.
- Main returns `videoUrl` so renderer playback remains simple and behaviorally unchanged.
- Disk-spill overflow handling is investigation-only in this pass.
- macOS-only MVP remains the target.
