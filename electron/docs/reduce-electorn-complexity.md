# Reduce Electron Complexity Hotspots

## Summary
Refactor the highest-ROI Electron complexity hotspots only: the renderer annotator flow and the main-process recording workflow. Keep behavior, IPC contracts, `.ctx` archive shape, and saved event schema unchanged. The goal is to lower cyclomatic complexity by moving branching into small pure helpers, focused hooks, and narrow subcomponents without changing product behavior.

## Key Changes
- Refactor [`electron/src/renderer/src/views/Annotator.tsx`](/Users/jesusavalos/Documents/Coding/Projects/context/electron/src/renderer/src/views/Annotator.tsx:1) into a thin container plus extracted helpers/hooks/components.
  - Extract pure model helpers into `views/annotator/model.ts`:
    - `buildAnnotatorEvents(rawEvents: RecordedMouseEvent[]): AnnotatorEvent[]`
    - `boundingBoxForSelection(snap: SnapView, selection: string): AxBoundingBox | null`
    - `selectedBoundingBox(snap: SnapView): AxBoundingBox | null`
    - `formatTimestamp(ms: number): string`
  - Extract recording/import orchestration into `views/annotator/useAnnotatorRecording.ts`.
    - Own `isRecording`, `isRecordingLoading`, `captureScreen`, media recorder lifecycle, import flow, and `loadRecordingIntoEditor`.
    - Public hook return:
      - `isRecording`
      - `isRecordingLoading`
      - `startOrStopRecording(): Promise<void>`
      - `importRecording(): Promise<void>`
      - `resetRecordingResources(): void`
  - Extract event selection, tooltip, and playhead behavior into `views/annotator/useAnnotatorTimeline.ts`.
    - Own `currentTimeMs`, `durationMs`, `activeEventIdx`, `expandedEventIdx`, tooltip state, hover scheduling, `seekToTime`, click/double-click selection, and time-windowed active event logic.
  - Extract annotation editing into `views/annotator/useAnnotationEditor.ts`.
    - Own `hasUnsavedChanges`, `isEditingBbox`, `selectNode`, `updateEventLabel`, `updateUserOverrideBbox`, `handleStartCustomAnnotation`, and `save`.
    - All writes to both `events` and `rawEvents` must be centralized here so there is one mutation path for annotation state.
  - Extract render-only subcomponents:
    - `AnnotatorToolbar`
    - `AnnotatorVideoPane`
    - `AnnotatorSidebar`
    - `EventTooltip`
  - `Annotator` should become a composition root that wires hooks and passes props. Target complexity: `<= 10`.

- Refactor [`electron/src/main/recording.ts`](/Users/jesusavalos/Documents/Coding/Projects/context/electron/src/main/recording.ts:1) so `finishRecording` stops being a multi-responsibility workflow.
  - Keep exported functions and return types unchanged.
  - Extract helpers:
    - `buildArchiveDialogOptions(defaultName: string): SaveDialogOptions`
    - `promptForArchivePath(window: BrowserWindow | null, defaultName: string): Promise<string | null>`
    - `collectRecordedEvents(startTime: number, fallbackEvents: RecordedMouseEvent[]): Promise<RecordedMouseEvent[]>`
    - `buildEventsJsonl(startTime: number, events: RecordedMouseEvent[]): string`
    - `createArchiveWriter(outputPath: string): { archive, archivePromise }`
    - `appendRecordingArchiveContents(archive, tempPath: string, jsonl: string): void`
    - `cleanupTempRecording(tempPath: string): Promise<void>`
  - `finishRecording` should read as:
    - validate active recording
    - close handle
    - prompt for path
    - collect events
    - write archive
    - cleanup
    - reload archive into app
    - map errors to existing result shape
  - Keep `startRecording`, `pushRecordingChunk`, `pickRecording`, and import/save helpers behaviorally identical unless needed to support the extraction. Target complexity: `finishRecording <= 6`, `pickRecording <= 4`.

- Do not include Rust or Python refactors in this pass.
  - Rust and worker code remain unchanged.
  - The only allowed cross-file type edits are internal renderer helper types if needed to support the extraction.

## Interfaces and Behavior
- No public IPC changes:
  - `recording:start`
  - `recording:push`
  - `recording:finish`
  - `recording:pick`
  - `recording:save-events`
- No schema changes:
  - `RecordedMouseEvent`
  - `LoadedRecordingPayload`
  - `.ctx` contents remain exactly `recording.webm` + `events.jsonl`
- Internal renderer types:
  - Keep `AnnotatorEvent` as the view model for the editor.
  - Keep `SnapView` semantics unchanged: `current`, `parents`, `children`, `userOverride`, `selected`, `title`, `description`.
- Selection behavior remains string-key based.
  - Preserve `"current"`, `"user_override"`, `"parents:<index>"`, `"children:<index>"`.
  - Do not reintroduce per-node `selected` flags.

## Test Plan
- Add unit tests for extracted pure helpers if a lightweight runner is introduced during implementation; otherwise keep tests to existing checks and focused manual verification.
- Required automated checks after refactor:
  - `npm run typecheck` in `electron`
  - `npm run lint` in `electron`
- Required manual scenarios:
  - Import a `.ctx` file and confirm events load, titles render, and tooltips still appear.
  - Click and double-click events in the sidebar and confirm selection/expansion behavior is unchanged.
  - Start recording, stop recording, save a `.ctx`, and confirm it reloads successfully.
  - Edit event title/description, save, reopen, and confirm persisted labels remain.
  - Create a custom annotation, drag bbox handles, switch selected nodes, save, reopen, and confirm the override persists.
  - Cancel both “open recording” and “save recording” dialogs and confirm existing error/cancel behavior is unchanged.
- Acceptance criteria:
  - `Annotator` no longer contains recording flow, timeline orchestration, and annotation mutation logic directly.
  - `finishRecording` no longer contains archive assembly, dialog handling, event collection, and cleanup inline.
  - No touched function exceeds cyclomatic complexity `10`, and the two current worst offenders are reduced to the targets above.

## Assumptions
- Scope is Electron-only for this pass.
- This is a refactor pass, not a feature pass: no UI redesign, no schema migration, no replay logic changes.
- Prefer a flat extraction under `views/annotator/` over introducing a deeper architecture.
- If no test runner is already present, do not expand scope by building a large test harness; prioritize pure extraction seams, existing checks, and the manual acceptance scenarios above.
