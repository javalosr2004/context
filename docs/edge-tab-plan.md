# Edge-tab plan

A persistent floating handle pinned to the bottom-right corner of the
primary screen that gives the user a guaranteed way to reach the overlay.
Replaces today's "minified icon" mode and removes the panel
close/miniaturize buttons that currently lead to an unrecoverable state.

## Problem

`PopupPanel` is a `.titled, .closable, .miniaturizable` `NSPanel`. If the
user hits the macOS close (X) or miniaturize button on the panel chrome,
the panel disappears and nothing on screen brings it back. The status-bar
menu helps, but is hidden in fullscreen apps and not a primary surface.

The existing `IconPanel` (the floating circle) is only visible when the
user explicitly minifies *from inside the popup* — it does not catch the
close-button case, and its free-floating position is easy to lose.

## Goals

1. There is *always* something on screen the user can click to reach the
   overlay, regardless of how the popup got dismissed.
2. The handle lives in a fixed, predictable spot — out of the way and
   not occluding work content.
3. No panel chrome close/miniaturize that produces an orphaned state.

## Non-goals

- Multi-monitor handle replication (MVP: primary screen only).
- Hiding the handle. It is always visible until the app quits.
- Letting the user move the tab. Position is fixed.
- Animating the popup as a sheet attached to the tab.

## Decisions (locked)

- **Tab position:** fixed in the bottom-right corner of the primary
  screen's `visibleFrame` (so it clears the Dock). Not draggable, not
  persisted, no edge-selection UI.
- **Popup position:** independent from the tab. The popup keeps whatever
  frame the user last placed it at; toggling via the tab does not move
  the popup.
- **Hideability:** none. The tab is always visible. To remove it the
  user quits the app.

## Behaviour

**Visibility:** the edge tab is shown from app launch and stays visible
across all popup states. It lives on `.screenSaver` level with
`[.canJoinAllSpaces, .fullScreenAuxiliary]` so it survives Space switches
and fullscreen apps, matching the existing panels.

**States** (replaces the current `PopupState` two-state model):

- `expanded` — popup panel front at its last user-chosen frame, tab visible.
- `collapsed` — popup panel hidden, tab visible.

The "icon hidden when popup shown" rule from `PopupController` goes away.
The tab is always there.

**Interaction:**

- *Click* the tab → toggle. If collapsed, restore popup at last
  expanded frame. If expanded, collapse the popup.
- *Right-click* → small context menu: "Show Overlay", "Quit".
- No drag handling.

**Visual:** narrow vertical pill anchored to the bottom-right corner of
`visibleFrame`, roughly 8pt wide × 56pt tall, with a small inset from the
edge (e.g. 8pt from right, 12pt from bottom). Semi-transparent with the
app's scope glyph centered. Hover bumps width slightly to telegraph it's
interactive. Exact metrics live in `EdgeTabMetrics` so they are easy to
tune.

**Re-anchoring:** on `NSApplication.didChangeScreenParametersNotification`,
recompute the bottom-right frame from the new `visibleFrame` and apply.
No persistence needed.

## Module boundaries

New files, each with a single responsibility:

- `Presentation/Panels/EdgeTabPanel.swift` — `NSPanel` subclass.
  Borderless, transparent, `.screenSaver`, all-spaces, non-activating.
  No close/miniaturize chrome.
- `Presentation/Views/EdgeTabView.swift` — SwiftUI view for the pill.
  Hover + press states only; no logic.
- `Application/EdgeTabController.swift` — owns the panel, computes the
  bottom-right frame for the current screen, re-anchors on screen-
  parameter changes, exposes `onToggle` to the coordinator.
- `Domain/EdgeTabAnchor.swift` — pure function:
  `func frame(in visibleFrame: CGRect, size: CGSize, inset: CGSize) -> CGRect`.
  Unit-testable.

Changes to existing files:

- `Presentation/Panels/PopupPanel.swift` — drop `.closable` and
  `.miniaturizable` from `styleMask`. No more orphaning. (Keep `.titled`
  for drag-by-titlebar, or switch to `.borderless` +
  `isMovableByWindowBackground` if cleaner.)
- `Application/PopupController.swift` — collapse the icon-panel branch.
  `minify()`/`restore()` keep their names but stop toggling the icon
  panel; they only toggle the popup itself. State becomes
  `expanded | collapsed`. Last expanded frame is still tracked so
  `restore()` returns the popup to where the user left it.
- `Application/OverlayCoordinator.swift` — instantiate
  `EdgeTabController`, wire its `onToggle` to `popupController.toggle()`,
  remove `iconPanel` construction and the `IconView` content. The
  in-popup "minify" button still works — it just calls `collapse()` on
  the controller instead of swapping panels.
- `Application/StatusBarController.swift` — keep the "Show Overlay"
  item as a redundant fallback (cheap, no harm).

Deleted (or kept dormant — confirm before deleting):

- `Presentation/Panels/IconPanel.swift`
- `Presentation/Views/IconView.swift` (path assumed; verify)
- `Application/IconMenuController.swift` — only if its responsibilities
  fully fold into `EdgeTabController`'s right-click menu. If it still
  serves the debug-bbox test action, keep it and just stop wiring it to
  the icon panel.

## Data flow

```
App launch
  → OverlayCoordinator builds EdgeTabController
  → EdgeTabAnchor.frame(in: screen.visibleFrame, ...)   [pure]
  → EdgeTabPanel placed bottom-right, orderFrontRegardless

User click on tab
  → EdgeTabPanel mouseDown
  → EdgeTabController.handleClick()
  → PopupController.toggle()
  → PopupPanel orderFront at last expanded frame / orderOut
  → state: expanded | collapsed (published)

Screen parameters change
  → OverlayCoordinator observes NSApplication.didChangeScreenParameters
  → EdgeTabController.reanchor(to: screen.visibleFrame)
  → EdgeTabAnchor.frame(...)                            [pure]
  → apply frame
  (popup frame is left alone; PopupController already clamps on its own
   reclamp path)
```

`EdgeTabAnchor.frame` is the entire unit-test surface for placement.
Everything else is thin glue.

## Failure modes & edge cases

- *Multi-monitor / monitor disconnect.* If the primary screen changes,
  the next `didChangeScreenParameters` re-anchors using the new
  `visibleFrame`. No persisted position to invalidate.
- *Dock visibility changes.* Always use `screen.visibleFrame`, never
  `screen.frame`, so the tab follows the Dock if the user hides/shows
  or moves it.
- *Click-through in fullscreen apps.* Confirm
  `.fullScreenAuxiliary + .canJoinAllSpaces + .nonactivatingPanel` keeps
  the tab clickable in another app's fullscreen — this mirrors what
  `PopupPanel` already does, so it should hold.
- *Popup last-frame off-screen after monitor change.* `PopupController`
  already runs `boundsKeeper.clamp` on `reclamp`; verify that still
  fires when the popup is hidden so the next `restore()` lands on a
  valid frame.

## Milestones

**M1 — Tab exists at bottom-right and toggles the popup.**
- New `EdgeTabPanel` + `EdgeTabView` rendered on app launch at the
  bottom-right of `visibleFrame`.
- Click toggles `PopupPanel` via `PopupController.toggle()`; popup
  restores to its last user-chosen frame.
- `PopupPanel` style mask updated to drop `.closable, .miniaturizable`.
- Re-anchor on `didChangeScreenParameters`.
- Acceptance: launching the app shows the tab in the bottom-right;
  clicking it expands and collapses the popup without moving the
  popup's user-set position; there is no X button on the popup;
  hiding/showing the Dock re-anchors the tab above the Dock.

**M2 — Polish + retire icon panel.**
- Right-click context menu on the tab (Show / Quit).
- Visual hover/press states.
- Delete `IconPanel` and `IconView` after confirming no other code path
  uses them.
- Update or remove `IconMenuController` accordingly.
- Acceptance: no references to `IconPanel`/`IconView` remain; tab
  context menu exposes Show / Quit.

## Tests

Pure-logic tests under `ContextAppTests/`:

- `EdgeTabAnchorTests` — bottom-right placement inside `visibleFrame`,
  inset honored, behaves correctly when `visibleFrame.origin` is
  non-zero (menu bar at top, Dock on left).
- `PopupControllerTests` — collapse/expand transitions no longer
  reference an icon panel; state machine reduces to two states;
  `restore()` returns the popup to its last expanded frame.

UI / integration smoke (manual, documented in acceptance per
milestone): launch, toggle, Dock show/hide, monitor disconnect.

## Open questions

1. Keep or drop the in-popup "minify" button now that the tab does the
   same job? Keep for M1 (familiar surface), revisit in M2.
