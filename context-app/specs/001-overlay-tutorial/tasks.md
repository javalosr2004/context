# Tasks: AI Tutorial Overlay (MVP Shell)

**Input**: Design documents from `/specs/001-overlay-tutorial/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md
**Tests**: Required for pure `Domain/` logic by Constitution Principle III and the implementation plan. AppKit/SwiftUI presentation work is validated manually.
**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on an incomplete task
- **[Story]**: Maps a task to a user story from `spec.md`
- Every task includes an exact target file path

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the macOS app skeleton, test target, and layer directories described in `plan.md`.

- [ ] T001 Create the Xcode macOS app project at `ContextApp/ContextApp.xcodeproj`
- [ ] T002 Configure the `ContextApp` app target for Swift 5.9 and macOS 13.0 in `ContextApp/ContextApp.xcodeproj/project.pbxproj`
- [ ] T003 Configure the `ContextAppTests` XCTest target in `ContextApp/ContextApp.xcodeproj/project.pbxproj`
- [ ] T004 [P] Create app target layer directories under `ContextApp/ContextApp/App/`, `ContextApp/ContextApp/Domain/`, `ContextApp/ContextApp/Application/`, `ContextApp/ContextApp/Presentation/`, and `ContextApp/ContextApp/Resources/`
- [ ] T005 [P] Create test target directory at `ContextApp/ContextAppTests/`
- [ ] T006 Configure `LSUIElement`, app sandbox, bundle identifier, and macOS deployment settings in `ContextApp/ContextApp/Resources/Info.plist`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish lifecycle wiring, panel defaults, and mechanically visible layer boundaries before story work begins.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T007 Create the SwiftUI app entry point in `ContextApp/ContextApp/App/ContextAppApp.swift`
- [ ] T008 Create the `NSApplicationDelegate` lifecycle shell in `ContextApp/ContextApp/App/AppDelegate.swift`
- [ ] T009 Create the overlay startup coordinator shell in `ContextApp/ContextApp/Application/OverlayCoordinator.swift`
- [ ] T010 [P] Create the base popup panel class with borderless non-activating panel defaults in `ContextApp/ContextApp/Presentation/Panels/PopupPanel.swift`
- [ ] T011 [P] Create the base minified icon panel class with borderless non-activating panel defaults in `ContextApp/ContextApp/Presentation/Panels/IconPanel.swift`
- [ ] T012 [P] Create the base debug bbox panel class with transparent click-through defaults in `ContextApp/ContextApp/Presentation/Panels/DebugBboxPanel.swift`
- [ ] T013 Add the domain import guard command documentation to `ContextApp/README.md`

**Checkpoint**: App lifecycle starts, panels can be constructed, and story implementation can proceed without changing project structure.

---

## Phase 3: User Story 1 - Always-On-Top Transparent Overlay with Chat Popup (Priority: P1) MVP

**Goal**: Launch a macOS overlay shell with a visible draggable popup, click-through empty regions, minify-to-icon, and restore behavior.

**Independent Test**: Launch the app and confirm within 2 seconds that the popup is above other windows, draggable, minifies to an icon, restores at the prior position, and clicks outside panels reach underlying apps.

### Tests for User Story 1

> Write these tests first and verify they fail before implementing the corresponding domain code.

- [ ] T014 [P] [US1] Add popup state transition tests in `ContextApp/ContextAppTests/PopupStateTests.swift`
- [ ] T015 [P] [US1] Add screen bounds clamping tests in `ContextApp/ContextAppTests/ScreenBoundsKeeperTests.swift`

### Implementation for User Story 1

- [ ] T016 [P] [US1] Implement `PopupState` expanded/minified transitions in `ContextApp/ContextApp/Domain/PopupState.swift`
- [ ] T017 [P] [US1] Implement `ScreenBoundsKeeper` frame clamping in `ContextApp/ContextApp/Domain/ScreenBoundsKeeper.swift`
- [ ] T018 [US1] Implement popup visibility, minify, restore, and clamping orchestration in `ContextApp/ContextApp/Application/PopupController.swift`
- [ ] T019 [P] [US1] Implement the popup SwiftUI shell with header, minify control, message list placeholder, and input placeholder in `ContextApp/ContextApp/Presentation/Views/ChatPopupView.swift`
- [ ] T020 [P] [US1] Implement the minified icon SwiftUI view in `ContextApp/ContextApp/Presentation/Views/IconView.swift`
- [ ] T021 [US1] Wire `PopupPanel`, `IconPanel`, `PopupController`, and views together in `ContextApp/ContextApp/Application/OverlayCoordinator.swift`
- [ ] T022 [US1] Handle primary display bounds changes and reclamp visible panels in `ContextApp/ContextApp/Application/OverlayCoordinator.swift`
- [ ] T023 [US1] Document US1 manual validation steps in `ContextApp/README.md`

**Checkpoint**: User Story 1 is fully functional and testable as the MVP shell.

---

## Phase 4: User Story 2 - Debug Menu: Test Green Bounding Box (Priority: P2)

**Goal**: From the minified icon menu, render one 500x500 green outline at a random fully-on-screen position and replace it on repeated invocation.

**Independent Test**: Minify the popup, right-click or Control-click the icon, select Debug -> Test green bbox, and confirm the bbox appears within 200 ms and moves to distinct positions across repeated triggers.

### Tests for User Story 2

> Write these tests first and verify they fail before implementing the corresponding domain code.

- [ ] T024 [P] [US2] Add bbox position generator tests in `ContextApp/ContextAppTests/BboxPositionGeneratorTests.swift`
- [ ] T025 [P] [US2] Add single-bbox replacement state tests in `ContextApp/ContextAppTests/DebugBboxStateTests.swift`

### Implementation for User Story 2

- [ ] T026 [P] [US2] Implement `DebugBoundingBox` and `BboxPositionGenerator` in `ContextApp/ContextApp/Domain/BboxPositionGenerator.swift`
- [ ] T027 [P] [US2] Implement `DebugBboxState` replacement semantics in `ContextApp/ContextApp/Domain/DebugBboxState.swift`
- [ ] T028 [P] [US2] Implement the green outline bbox SwiftUI view in `ContextApp/ContextApp/Presentation/Views/DebugBboxView.swift`
- [ ] T029 [P] [US2] Implement icon context menu construction with Debug -> Test green bbox in `ContextApp/ContextApp/Presentation/Menu/IconContextMenu.swift`
- [ ] T030 [US2] Implement menu action handling in `ContextApp/ContextApp/Application/IconMenuController.swift`
- [ ] T031 [US2] Implement bbox generation, replacement, and panel frame updates in `ContextApp/ContextApp/Application/DebugBboxController.swift`
- [ ] T032 [US2] Wire `IconMenuController` and `DebugBboxController` into `ContextApp/ContextApp/Application/OverlayCoordinator.swift`
- [ ] T033 [US2] Document US2 manual validation steps in `ContextApp/README.md`

**Checkpoint**: User Stories 1 and 2 work independently; the explicit debug validation hook is complete.

---

## Phase 5: User Story 3 - Basic Chat Display and Input (Priority: P3)

**Goal**: Make the popup a real in-memory chat shell where submitted text is appended, ordered, scrollable, and preserved across minify/restore.

**Independent Test**: Expand the popup, submit several messages, confirm they appear in insertion order, scroll when needed, minify, restore, and verify the messages remain.

### Tests for User Story 3

> Write these tests first and verify they fail before implementing the corresponding domain code.

- [ ] T034 [P] [US3] Add chat append, trimming, rejection, and ordering tests in `ContextApp/ContextAppTests/ChatMessageStoreTests.swift`

### Implementation for User Story 3

- [ ] T035 [US3] Implement `ChatMessage` and `ChatMessageStore` in `ContextApp/ContextApp/Domain/ChatMessageStore.swift`
- [ ] T036 [US3] Connect `ChatMessageStore` to popup state in `ContextApp/ContextApp/Application/PopupController.swift`
- [ ] T037 [US3] Replace placeholder message/input UI with bound scrollable chat behavior in `ContextApp/ContextApp/Presentation/Views/ChatPopupView.swift`
- [ ] T038 [US3] Preserve chat store instance across minify and restore in `ContextApp/ContextApp/Application/OverlayCoordinator.swift`
- [ ] T039 [US3] Document US3 manual validation steps in `ContextApp/README.md`

**Checkpoint**: All user stories are independently functional for the MVP shell.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validate the shell, tighten failure modes, and update project documentation without expanding product scope.

- [ ] T040 [P] Run the XCTest suite with `xcodebuild -scheme ContextApp -destination 'platform=macOS' test` and record the result in `ContextApp/README.md`
- [ ] T041 Add quickstart launch and troubleshooting notes for `LSUIElement`, panel level, and click-through behavior in `ContextApp/README.md`
- [ ] T042 Verify no `ContextApp/ContextApp/Domain/` file imports `AppKit` or `SwiftUI` and record the check in `ContextApp/README.md`
- [ ] T043 Manually validate SC-001 through SC-007 from `specs/001-overlay-tutorial/quickstart.md` and record results in `ContextApp/README.md`
- [ ] T044 Review all source files for small functions, clear naming, and layer separation in `ContextApp/ContextApp/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; this is the suggested MVP scope.
- **User Story 2 (Phase 4)**: Depends on Foundational and integrates with the minified icon from US1 for the complete manual flow.
- **User Story 3 (Phase 5)**: Depends on Foundational and integrates with the popup from US1.
- **Polish (Phase 6)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: First shippable slice; no dependency on other stories after Foundational.
- **US2 (P2)**: Can implement domain and menu files after Foundational, but end-to-end validation needs US1 icon behavior.
- **US3 (P3)**: Can implement domain chat store after Foundational, but end-to-end validation needs US1 popup behavior.

### Within Each User Story

- Write domain tests before domain implementation.
- Implement domain types before application controllers that compose them.
- Implement presentation views before final coordinator wiring.
- Complete the checkpoint before moving to the next priority story for sequential delivery.

### Parallel Opportunities

- T004 and T005 can run in parallel after project creation.
- T010, T011, and T012 can run in parallel because they create separate panel files.
- T014 and T015 can run in parallel before T016 and T017.
- T024 and T025 can run in parallel before T026 and T027.
- T026, T027, T028, and T029 can run in parallel before controller wiring.
- T040 and T041 can run in parallel during polish once the app exists.

---

## Parallel Example: User Story 1

```bash
Task: "T014 [P] [US1] Add popup state transition tests in ContextApp/ContextAppTests/PopupStateTests.swift"
Task: "T015 [P] [US1] Add screen bounds clamping tests in ContextApp/ContextAppTests/ScreenBoundsKeeperTests.swift"
Task: "T019 [P] [US1] Implement the popup SwiftUI shell with header, minify control, message list placeholder, and input placeholder in ContextApp/ContextApp/Presentation/Views/ChatPopupView.swift"
Task: "T020 [P] [US1] Implement the minified icon SwiftUI view in ContextApp/ContextApp/Presentation/Views/IconView.swift"
```

## Parallel Example: User Story 2

```bash
Task: "T024 [P] [US2] Add bbox position generator tests in ContextApp/ContextAppTests/BboxPositionGeneratorTests.swift"
Task: "T025 [P] [US2] Add single-bbox replacement state tests in ContextApp/ContextAppTests/DebugBboxStateTests.swift"
Task: "T028 [P] [US2] Implement the green outline bbox SwiftUI view in ContextApp/ContextApp/Presentation/Views/DebugBboxView.swift"
Task: "T029 [P] [US2] Implement icon context menu construction with Debug -> Test green bbox in ContextApp/ContextApp/Presentation/Menu/IconContextMenu.swift"
```

## Parallel Example: User Story 3

```bash
Task: "T034 [P] [US3] Add chat append, trimming, rejection, and ordering tests in ContextApp/ContextAppTests/ChatMessageStoreTests.swift"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. Stop and validate US1 manually against its independent test.
5. Demo the overlay shell before adding debug bbox or chat behavior.

### Incremental Delivery

1. Setup + Foundational establishes the app, layers, lifecycle, and panel defaults.
2. US1 delivers the smallest shippable overlay shell.
3. US2 adds the explicit green bbox validation hook.
4. US3 turns the popup placeholder into the chat shell.
5. Polish validates success criteria and records the manual checks.

### Failure Modes To Watch

- Panel level is too low, causing the popup or bbox to appear behind other apps.
- A panel accidentally intercepts clicks outside its visible UI, breaking click-through expectations.
- Popup or icon can be dragged fully off-screen and becomes unreachable.
- Bbox generation does not account for displays smaller than 500x500.
- Chat store accepts empty messages or loses message order after minify/restore.
