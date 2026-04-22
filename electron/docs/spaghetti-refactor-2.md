# Capture Boundary And Backend Stability Plan v2

## Summary

- [x] Strict filesystem boundary is complete.
  Renderer now uses `recordingId`, `displayName`, and main-owned `videoUrl`; it no longer sends or stores archive/extracted/event file paths for import/save.
- [x] Deterministic stop-and-drain capture RPC is complete.
  Rust now supports `stop_and_get_mouse_events`, and Electron uses it during `finishRecording`.
- [ ] Next pass focuses only on the remaining MVP-hardening work:
  1. backend child-process lifecycle and RPC timeout hardening
  2. annotator state normalization and immutable updates
  3. overflow/degraded-session design output
  4. generated-artifact/build policy docs
- [ ] Separate capture/viewer preload split is explicitly deferred.
  Keep the shared preload until the viewer gains write/file/process privileges or starts carrying real LLM/session state.

## Public Interfaces And Defaults

- Keep the current capture API unchanged in this pass:
  - `startRecording(): Promise<Result<null>>`
  - `finishRecording(defaultName): Promise<Result<LoadedRecordingPayload>>`
  - `pickRecording(): Promise<Result<LoadedRecordingPayload>>`
  - `saveRecordingEvents(recordingId, events): Promise<Result<null>>`
- Keep `LoadedRecordingPayload = { recordingId, displayName, videoUrl, events }`.
- Keep `media://recording/<recordingId>` as the only renderer-visible video source.
- Add one new cleanup API:
  - `closeRecording(recordingId): Promise<Result<null>>`
- Default id behavior remains ephemeral:
  - ids are valid only for the current app run
  - app restart invalidates all ids
  - unknown or expired ids return `Err("Recording not found or expired")`

## Remaining Implementation Changes

### 1. Backend Lifecycle Hardening

- In Electron main, make recording shutdown fully deterministic:
  - on `finishRecording`, call `stop_and_get_mouse_events`
  - after archiving/import registration completes, terminate the Rust child process
  - wait for child exit before clearing session state
- On canceled save, failed archive write, window close, and app quit:
  - stop listener if active
  - terminate the child process
  - clear pending RPC requests
  - clear active recording state
- In `rpc.ts`, add per-request timeout handling:
  - default timeout: 2000ms
  - remove timed-out requests from the pending map
  - reject with a stable timeout error string
  - preserve current “process closed” rejection on child exit
- Child-process shutdown policy:
  - first try normal termination
  - wait up to 2000ms for `close`
  - if still alive, force-kill
- Do not change renderer-visible IPC for this work.

### 2. Annotator State Hardening

- In the annotator path, make `rawEvents` the only persistence source of truth.
- On load, normalize snapshot-shaped payloads once:
  - `parents` defaults to `[]`
  - `children` defaults to `[]`
  - `selected` defaults to `"current"` when `current` exists and no explicit selection is present
  - legacy flat attribute maps remain supported without structural rewriting
- Remove all in-place mutation of:
  - `snap`
  - `rawSnap`
  - `rawEvents`
- Replace the current mutation sites with pure immutable helpers for:
  - selecting a node
  - updating `title` / `description`
  - creating or updating `userOverride.boundingBox`
- Keep user behavior unchanged:
  - record
  - import
  - play video
  - edit labels and bounding boxes
  - save back into the archive
- Extract only two focused helpers/modules if needed:
  - one pure normalization/update helper module for snapshot/event edits
  - one small recording-session helper for load/save/close orchestration
- Do not introduce a new global state system or broad UI rewrite.

### 3. Recording Registry Cleanup

- Add `closeRecording(recordingId)` in main.
- `closeRecording` must:
  - remove the registry entry
  - delete the extracted temp directory for that recording
  - return success if already missing after cleanup attempt
- Renderer behavior:
  - when loading a different recording, close the previous one first
  - on annotator unmount, close the current loaded recording if present
- Do not auto-expire ids on a timer in this pass.

### 4. Overflow / Degraded Session Design Output

- Do not implement disk spill in this pass.
- Produce a short decision-complete design note covering:
  - bounded-queue insertion point: Rust collector event queue before Electron drain
  - future sequence numbering owner: Rust collector at capture time
  - future degraded-session fields: `sessionDegraded`, `overflowCount`, `firstOverflowTimeUtcMs`
  - future renderer visibility: degradation returned as session metadata alongside drained events
  - cleanup rule: spill artifacts owned and deleted by the same recording lifecycle as extracted imports
- No runtime behavior changes are required yet beyond documenting this design.

### 5. Generated Artifact / Build Policy

- Do not move generated files in this pass.
- Document the current authoritative paths and regeneration rule:
  - app runtime types come from `electron/resources/types/rust_types.ts`
  - regeneration command is `npm run build:rust:types`
  - `electron/resources/bin/capture` is a temporary built artifact, not the source of truth
  - source of truth remains Rust source plus the build scripts already in `package.json`

## Test Plan

- Electron main tests:
  - `saveRecordingEvents` rejects unknown ids
  - `media://recording/<id>` rejects unknown ids and serves only registered video
  - `closeRecording` removes registry entries and extracted dirs
  - finished, canceled, and failed recordings do not leave Rust child processes alive
  - timed-out RPC requests reject and are removed from the pending map
- Renderer tests:
  - loading a recording with missing `parents` / `children` does not crash
  - label and bbox edits update state immutably
  - switching recordings closes the previous registry entry
  - unmount closes the current recording
- Rust tests:
  - `stop_and_get_mouse_events` returns only post-stop-drain-safe events
  - stop acknowledgment still occurs before RPC success
- Integration scenarios:
  - record -> stop -> save -> auto-load works
  - import -> edit -> save works with no renderer path knowledge
  - repeated record/import cycles do not leak child processes or extracted dirs
  - app quit during active recording does not orphan Rust

## Assumptions And Defaults

- The recently completed strict boundary and pathless capture flow are accepted as baseline and should not be redesigned in this pass.
- Viewer preload separation is deferred by default.
- Ephemeral in-memory recording ids remain the default.
- No disk-spill implementation is added yet.
- macOS-only MVP remains the target.
