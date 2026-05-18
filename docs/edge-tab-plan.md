# Edge-tab plan

A persistent floating handle pinned to a screen edge that gives the user a
guaranteed way to reach the overlay. Replaces the today's "minified icon"
mode and removes the panel close/miniaturize buttons that currently lead to
an unrecoverable state.

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
2. The handle lives at a screen edge — predictable, out of the way, and
   not occluding work content.
3. No panel chrome close/miniaturize that produces an orphaned state.

## Non-goals

- Multi-monitor handle replication (MVP: primary screen only).
- Hiding the handle entirely (out of scope; users who want it gone can
  quit from the status bar).
- Animating the popup as a sheet attached to the tab.

## Behaviour

**Visibility:** the edge tab is shown from app launch and stays visible
across all popup states. It lives on `.screenSaver` level with
`[.canJoinAllSpaces, .fullScreenAuxiliary]` so it survives Space switches
and fullscreen apps, matching the existing panels.

**States** (replaces the current `PopupState` two-state model):

- `expanded` — popup panel front, edge tab visible.
- `collapsed` — popup panel hidden, edge tab visible.

The "icon hidden when popup shown" rule from `PopupController` goes away.
The tab is always there.

**Interaction:**

- *Click* the tab → toggle. If collapsed, restore popup at last expanded
  frame. If expanded, collapse the popup.
- *Drag* the tab → move along the current edge (one axis only). If
  dragged past a threshold toward another edge, snap to that edge. Free
  2D dragging is rejected to keep placement predictable.
- *Right-click* → small context menu: "Show Overlay", "Pin to left/right
  edge", "Quit".

**Persistence:** edge (`left | right | top | bottom`) and along-edge
offset persist in `UserDefaults` under a single key, e.g.
`overlay.edgeTab.position`. Re-clamped on launch and on
`didChangeScreenParameters`.

**Visual:** narrow vertical pill on the right edge by default — roughly
8pt wide × 56pt tall, semi-transparent, with the app's scope glyph
centered. Hover bumps width slightly to telegraph it's interactive.
Exact metrics live in `EdgeTabMetrics` so they are easy to tune.

## Module boundaries

New files, each with a single responsibility:

- `Presentation/Panels/EdgeTabPanel.swift` — `NSPanel` subclass.
  Borderless, transparent, `.screenSaver`, all-spaces, non-activating.
  No close/miniaturize chrome.
- `Presentation/Views/EdgeTabView.swift` — SwiftUI view for the pill.
  Hover + press states only; no logic.
- `Application/EdgeTabController.swift` — owns the panel, applies
  position from `EdgeTabPositionStore`, handles drag → edge snap →
  persist, exposes `toggle()` / `show()` callbacks to the coordinator.
- `Domain/EdgeTabPosition.swift` — pure value type (`edge`, `offset`)
  plus snapping math. Unit-testable.
- `Domain/EdgeTabPositionStore.swift` — `UserDefaults`-backed
  load/save, mirroring `GroundingEndpointStore` shape.

Changes to existing files:

- `Presentation/Panels/PopupPanel.swift` — drop `.closable` and
  `.miniaturizable` from `styleMask`. No more orphaning. (Keep `.titled`
  for drag-by-titlebar, or switch to `.borderless` + `isMovableByWindowBackground` if cleaner.)
- `Application/PopupController.swift` — collapse the icon-panel branch.
  `minify()`/`restore()` keep their names but stop toggling the icon
  panel; they only toggle the popup itself. State becomes
  `expanded | collapsed`.
- `Application/OverlayCoordinator.swift` — instantiate
  `EdgeTabController`, wire its `onToggle` to `popupController.toggle()`,
  remove `iconPanel` construction and the `IconView` content. The
  in-popup "minify" button still works — it just calls `collapse()` on
  the controller instead of swapping panels.
- `Application/StatusBarController.swift` — keep the "Show Overlay"
  item as a belt-and-suspenders fallback (e.g. user dragged the tab
  somewhere weird off-screen — the reclamp on next screen-change event
  will recover, but the menu item is still nice to have).

Deleted (or kept dormant — confirm before deleting):

- `Presentation/Panels/IconPanel.swift`
- `Presentation/Views/IconView.swift` (path assumed; verify)
- `Application/IconMenuController.swift` — only if its responsibilities
  fully fold into `EdgeTabController`'s right-click menu. If it still
  serves the debug-bbox test action, keep it and just stop wiring it to
  the icon panel.

## Data flow

```
User click on tab
  → EdgeTabPanel mouseDown
  → EdgeTabController.handleClick()
  → PopupController.toggle()
  → PopupPanel orderFront / orderOut
  → state: expanded | collapsed (published)

User drag on tab
  → EdgeTabPanel mouseDragged delta
  → EdgeTabController.handleDrag(delta)
  → EdgeTabPosition.afterDrag(delta, on: screenFrame)  [pure]
  → apply frame, debounce-save to EdgeTabPositionStore

Screen parameters change
  → OverlayCoordinator observes NSApplication.didChangeScreenParameters
  → EdgeTabController.reclamp(to: screen.frame)
  → EdgeTabPosition.clamped(into: screenFrame)         [pure]
```

The pure functions in `EdgeTabPosition` (snap, clamp, afterDrag) are the
unit-test surface. Everything else is thin glue.

## Failure modes & edge cases

- *Multi-monitor / monitor disconnect.* If the persisted position
  references a screen that no longer exists, fall back to the primary
  screen's right edge at 40% from top. Reclamp on every
  `didChangeScreenParameters`.
- *Notch / menu bar overlap on top edge.* When `edge == .top`, offset
  the panel below `NSScreen.main.safeAreaInsets.top` (or the legacy
  menu-bar height) so it isn't obscured.
- *Dock collision on bottom edge.* Use `screen.visibleFrame` (not
  `screen.frame`) as the placement rect so the tab clears the Dock.
- *Click-through in fullscreen apps.* Confirm
  `.fullScreenAuxiliary + .canJoinAllSpaces + .nonactivatingPanel` keeps
  the tab clickable in another app's fullscreen — this mirrors what
  `PopupPanel` already does, so it should hold.
- *Drag jitter near edge boundary.* Snap threshold must exceed the
  hysteresis band (e.g. snap when drag delta perpendicular to current
  edge > 60pt, then re-snap to nearest edge by center distance).
- *Save thrash on drag.* Debounce `EdgeTabPositionStore.save` to ~250ms
  trailing-edge so we don't hammer `UserDefaults`.

## Milestones

**M1 — Tab exists and is always visible.**
- New `EdgeTabPanel` + `EdgeTabView` rendered on app launch at fixed
  right-edge position.
- Click toggles `PopupPanel` via existing `PopupController.minify/restore`
  wrappers.
- `PopupPanel` style mask updated to drop `.closable, .miniaturizable`.
- Acceptance: launching the app shows the tab; clicking it expands and
  collapses the popup; there is no X button on the popup.

**M2 — Draggable + edge snapping + persistence.**
- `EdgeTabPosition` pure type with `afterDrag`, `snapped`, `clamped`.
- `EdgeTabController` applies drag, snaps to nearest edge past
  threshold, debounce-saves to `EdgeTabPositionStore`.
- Reclamp on `didChangeScreenParameters`.
- Acceptance: drag to each of the four edges and verify snap; relaunch
  app and verify position persists; disconnect a monitor and verify
  reclamp.

**M3 — Polish + retire icon panel.**
- Right-click context menu on the tab.
- Visual hover/press states.
- Delete `IconPanel` and `IconView` after confirming no other code path
  uses them.
- Update or remove `IconMenuController` accordingly.
- Acceptance: no references to `IconPanel`/`IconView` remain; tab
  context menu exposes Show / Pin / Quit.

## Tests

Pure-logic tests under `ContextAppTests/`:

- `EdgeTabPositionTests` — snapping past threshold, clamping inside
  `visibleFrame`, top-edge menu-bar inset, drag math along each axis.
- `EdgeTabPositionStoreTests` — round-trip save/load, default value
  when unset, invalid stored payload falls back to default.
- `PopupControllerTests` — collapse/expand transitions no longer
  reference an icon panel; state machine reduces to two states.

UI / integration smoke (manual, documented in acceptance per
milestone): launch, drag, restart, monitor disconnect.

## Open questions

1. Should the tab be hideable (e.g. ⌥-click to fade for 30s)? Not in
   MVP, but worth deciding before we lock the UX.
2. Right-click "Pin to edge" — useful, or is drag-to-snap enough? Lean
   toward drag-only for MVP; add menu only if users get stuck.
3. Keep or drop the in-popup "minify" button now that the tab does the
   same job? Keep for M1 (familiar surface), revisit in M3.
