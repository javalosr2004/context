# Quickstart: AI Tutorial Overlay (MVP Shell)

**Feature**: 001-overlay-tutorial
**Date**: 2026-05-05

## Prerequisites

- macOS 13 (Ventura) or later
- Xcode 15 or later
- Apple Developer signing identity for local-run codesigning (the default
  development cert is fine; no paid account needed for local debugging)

## Build & run

```bash
# from repo root
cd context-app/ContextApp
open ContextApp.xcodeproj
```

In Xcode:

1. Select the `ContextApp` scheme.
2. Choose **My Mac** as the run destination.
3. Press ⌘R.

On launch:

- The Dock icon does not appear (the app is `LSUIElement = YES`).
- A small chat popup floats above all other windows on your primary
  display.
- You can click and drag the popup; it follows the cursor.
- A minify control in the popup's header collapses it to a small icon.
- Right-click (or Control-click) the icon → **Debug** → **Test green
  bbox** to render a 500×500 green-outlined rectangle at a random
  on-screen position. Repeat to move it.

## Validating against the spec

Each numbered item maps to a Success Criterion in `spec.md`.

| SC | How to validate manually |
|---|---|
| SC-001 | Cold-launch the app; a chat popup is visible within ~2 seconds. |
| SC-002 | Drag the popup quickly across the screen; movement tracks the cursor without visible lag. |
| SC-003 | Open the icon menu and select "Test green bbox"; the rectangle appears effectively immediately. |
| SC-004 | Trigger "Test green bbox" 10 times in succession; observe at least 4 distinct positions. |
| SC-005 | With the popup not under the cursor, click an underlying app's window; that app receives focus. |
| SC-006 | Send a few messages, minify, expand; messages remain in order. |
| SC-007 | Trigger "Test green bbox" again and confirm the previous bbox is replaced (not stacked). |

## Running the test suite

```bash
# from repo root
cd context-app/ContextApp
xcodebuild -scheme ContextApp \
           -destination 'platform=macOS' \
           test
```

Expected: all `Domain/`-level tests pass:

- `BboxPositionGeneratorTests`
- `ScreenBoundsKeeperTests`
- `PopupStateTests`
- `ChatMessageStoreTests`
- `DebugBboxStateTests`

UI is not covered by automated tests in this MVP (Constitution Principle
III exemption); validate it manually using the table above.

## Troubleshooting

- **Popup is not above other windows**: confirm `panel.level` is
  `.screenSaver` (set in `PopupPanel.swift`). If macOS has placed an app
  in fullscreen-exclusive mode, the panel may temporarily disappear; this
  is expected per the spec's edge cases.
- **Bbox does not appear**: confirm the menu fires (set a breakpoint in
  `IconMenuController.handleTestBbox()`). Confirm
  `DebugBboxPanel.orderFront(_:)` is called after state changes.
- **Click does not pass through to underlying app**: confirm the click is
  in a region with no panel. The empty space between panels is the only
  click-through region; the popup, icon, and bbox panels do still
  intercept clicks where they overlap (the bbox panel uses
  `ignoresMouseEvents = true`, so it should not intercept).
- **App takes Dock focus on launch**: confirm `LSUIElement = YES` in
  `Info.plist`.

## What is intentionally NOT in this feature

- No AI / LLM integration (deferred to feature 002).
- No persistence — chat content is ephemeral.
- No multi-display support.
- No dark/light theming polish; the popup uses default macOS styling.
- No menu items beyond "Debug → Test green bbox".
