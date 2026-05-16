# Implementation Plan: AI Tutorial Overlay (MVP Shell)

**Branch**: `001-overlay-tutorial` | **Date**: 2026-05-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-overlay-tutorial/spec.md`

## Summary

Deliver the macOS-native shell for the AI Tutorial Overlay: a transparent
always-on-top surface, a draggable chat popup that minifies to an icon, an
icon-attached menu with a Debug → "Test green bbox" entry, and a basic
chat-style UI shell (no AI integration in this feature). The technical
approach uses multiple borderless `NSPanel` windows rather than one
screen-spanning window, because per-region click-through on a single
full-screen `NSWindow` is markedly more complex than placing each UI element
in its own panel and letting the empty space between them be intrinsically
click-through. Domain logic (random bbox positioning, popup state, on-screen
clamping, chat store) is pure Swift in a `Domain/` layer and is developed
test-first per Constitution Principle III; AppKit code lives in
`Presentation/` and is exempt.

## Technical Context

**Language/Version**: Swift 5.9 (Xcode 15+)
**Primary Dependencies**: AppKit (`NSPanel`, `NSWindow`, `NSMenu`,
`NSStatusItem`-style level), SwiftUI for popup content rendering
(hosted inside an `NSHostingView`), Foundation
**Storage**: N/A (chat is ephemeral, in-memory only for this MVP)
**Testing**: XCTest
**Target Platform**: macOS 13.0+ (Ventura)
**Project Type**: macOS desktop application (single project, no backend tier)
**Performance Goals**: cold start to overlay-visible ≤ 2 s (SC-001); popup
drag latency < 100 ms (SC-002); debug bbox visible within 200 ms of menu
selection (SC-003)
**Constraints**: always-on-top above all user app windows; click-through
where no UI panel exists; primary-display only for MVP (no multi-display);
this feature pulls in zero third-party Swift packages (lightweight per-
feature additions remain available under Constitution Principle II if a
later task needs one)
**Scale/Scope**: single-user desktop app; ~6 domain types, ~5 presentation
windows/views, ~10 tests; one Xcode project, one app target, one test target

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution version evaluated: **3.1.0**.

| Principle | Status | Evidence in this plan |
|---|---|---|
| I. Clear Code, Layer-Agnostic | ✅ Pass | Layer-based directory structure; small types per file; no `Utils/` dump. |
| II. Minimum-Viable Dependencies (NON-NEGOTIABLE) | ✅ Pass | This feature uses Apple frameworks only (AppKit, SwiftUI, Foundation). No third-party Swift packages are required for the MVP shell. Lightweight per-feature additions are permitted by the constitution; if a future task needs one, it MUST be declared in this plan's "Dependencies for this feature" subsection (added then) and meet the Lightweight Library Criteria. |
| III. TDD for Domain Logic (NON-NEGOTIABLE) | ✅ Pass | `Domain/` layer (BboxPositionGenerator, ChatMessageStore, PopupState, ScreenBoundsKeeper, DebugBboxState) is test-first. Tasks plan will order tests before implementations for each. AppKit/SwiftUI code in `Presentation/` is exempt. |
| IV. Contract-First Tier Boundaries (NON-NEGOTIABLE) | ✅ N/A — not applicable | This feature is purely intra-process. There is no cross-tier surface (no client↔server, no external service, no persistence). Per the constitution, the `contracts/` artifact is required only for cross-tier features. Principle IV is therefore vacuously satisfied. The Gemini-backed backend tier is deferred to feature 002, which will require a contract. |
| V. Separation of Concerns by Layer (NON-NEGOTIABLE) | ✅ Pass | Layout: `Domain/` (pure Swift, no AppKit imports), `Application/` (coordinators, no SwiftUI bodies), `Presentation/` (NSPanel/NSView/SwiftUI), `App/` (entry point only). Secrets: none. Persistence: none. |

**Result**: All gates pass. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-overlay-tutorial/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (domain entities)
├── quickstart.md        # Phase 1 output (build & run)
└── checklists/
    └── requirements.md  # Spec quality checklist (already passing)
```

No `contracts/` directory — see Constitution Check, Principle IV: this
feature has no cross-tier surface.

### Source Code (repository root)

The Swift app lives at `context-app/ContextApp/` (Xcode project alongside
the existing `.specify/` and `specs/` directories).

```text
context-app/
└── ContextApp/                         # Xcode project root
    ├── ContextApp.xcodeproj/
    ├── ContextApp/                     # app target source
    │   ├── App/
    │   │   ├── ContextAppApp.swift     # @main App entry point
    │   │   └── AppDelegate.swift       # NSApplicationDelegate (lifecycle)
    │   ├── Domain/                     # Pure Swift, no AppKit imports
    │   │   ├── BboxPositionGenerator.swift
    │   │   ├── ScreenBoundsKeeper.swift
    │   │   ├── PopupState.swift
    │   │   ├── ChatMessage.swift
    │   │   ├── ChatMessageStore.swift
    │   │   └── DebugBboxState.swift
    │   ├── Application/                # Coordinators, controllers
    │   │   ├── OverlayCoordinator.swift
    │   │   ├── PopupController.swift
    │   │   ├── IconMenuController.swift
    │   │   └── DebugBboxController.swift
    │   ├── Presentation/               # AppKit + SwiftUI (exempt from TDD)
    │   │   ├── Panels/
    │   │   │   ├── PopupPanel.swift           # NSPanel subclass for popup
    │   │   │   ├── IconPanel.swift            # NSPanel subclass for minified icon
    │   │   │   └── DebugBboxPanel.swift       # NSPanel subclass for the bbox
    │   │   ├── Views/
    │   │   │   ├── ChatPopupView.swift        # SwiftUI popup body
    │   │   │   ├── IconView.swift             # SwiftUI icon body
    │   │   │   └── DebugBboxView.swift        # SwiftUI green-outline rect
    │   │   └── Menu/
    │   │       └── IconContextMenu.swift      # NSMenu builder
    │   └── Resources/
    │       ├── Info.plist
    │       └── Assets.xcassets/
    └── ContextAppTests/                # XCTest target
        ├── BboxPositionGeneratorTests.swift
        ├── ScreenBoundsKeeperTests.swift
        ├── PopupStateTests.swift
        ├── ChatMessageStoreTests.swift
        └── DebugBboxStateTests.swift
```

**Structure Decision**: macOS desktop application, single Xcode project,
single app target, single test target. Source code is organized by
*architectural layer* (`Domain/`, `Application/`, `Presentation/`, `App/`)
rather than by feature, because Principle V is itself layer-based and a
layer-based directory layout makes layer violations visible at the import
level: a file in `Domain/` that imports `AppKit` or `SwiftUI` is a
mechanically detectable violation.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. This section is intentionally empty.
