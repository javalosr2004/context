# Research: AI Tutorial Overlay (MVP Shell)

**Feature**: 001-overlay-tutorial
**Date**: 2026-05-05

This document records the technical decisions made during planning. Each
entry follows the form: **Decision** / **Rationale** / **Alternatives
considered**.

---

## R-1. Window strategy: multiple `NSPanel` vs one screen-spanning `NSWindow`

**Decision**: Use multiple borderless `NSPanel` instances — one for the
popup, one for the minified icon, one for the debug bbox — rather than one
single full-screen transparent `NSWindow`.

**Rationale**: The spec requires that transparent regions of the overlay
pass mouse events through to underlying applications, while the popup,
icon, menu, and bbox capture input. With multiple `NSPanel`s, this
click-through behavior is intrinsic: where there is no panel, there is
nothing to receive a click, so the underlying application receives it. This
matches what apps like Loom, CleanShot X, AltTab, and Rectangle do for
HUD-style overlays. It also reduces the surface for hit-test bugs.

`NSPanel` is preferred over `NSWindow` because:

- `.nonactivatingPanel` style mask keeps the panel from stealing the active
  application status from the user's actual app, which would break the
  tutorial UX (the user is supposed to be working in the app being
  taught).
- `NSPanel` has sensible defaults for floating/utility windows.

Each panel uses:

- `styleMask = [.borderless, .nonactivatingPanel]`
- `backgroundColor = .clear`, `isOpaque = false`, `hasShadow = false`
- `level = .screenSaver` (above status bar, app windows, and full-screen
  apps where macOS permits)
- `collectionBehavior` includes `.canJoinAllSpaces` and
  `.fullScreenAuxiliary` so the panels remain visible across spaces and
  alongside fullscreen apps.

For the debug bbox panel only: `ignoresMouseEvents = true` so the green
rectangle is purely visual and does not block interaction beneath it.

**Alternatives considered**:

- **Single full-screen transparent `NSWindow` with custom hit-testing.**
  Approach: cover the whole screen, override `NSView.hitTest(_:)` to
  return `nil` for empty regions. Problem: `NSWindow.ignoresMouseEvents`
  is binary (whole-window). Toggling it dynamically based on cursor
  tracking adds a state machine and a `NSTrackingArea` wrangling
  layer that is unnecessary when multiple panels solve the problem
  intrinsically. Rejected for MVP.
- **Single full-screen `NSWindow` with `ignoresMouseEvents = true`, plus
  separate panels for interactive elements.** Same as the chosen approach
  except adds a permanently click-through "canvas" window that contributes
  nothing visually (it is fully transparent). Rejected as
  dead weight; the conceptual "overlay layer" is the *coordinator*, not a
  literal window.

**Implication for the spec**: FR-001 says "the application MUST display a
fully transparent overlay covering the entire primary display." This is
satisfied in the user-observable sense — the floating elements together
behave as a tutorial overlay and can appear anywhere on the display — even
though no single window of display size exists. Spec language is preserved.

---

## R-2. Click-through specifically for the debug bbox panel

**Decision**: The debug bbox panel sets
`acceptsMouseMovedEvents = false`, `ignoresMouseEvents = true`. The other
panels (popup, icon) accept mouse events normally.

**Rationale**: The bbox is a visual annotation. Per the spec it is just a
500×500 green outline; users do not interact with it. Forwarding clicks
through it to the underlying app preserves the tutorial-overlay UX (the
user can click the thing the bbox is highlighting).

**Alternatives considered**: Make the bbox interactive (click to dismiss).
Deferred — SC-007 says the user must be able to "dismiss or replace" the
bbox; replacement via re-invoking the menu satisfies that for MVP. Click-to-
dismiss is a polish item.

---

## R-3. Popup drag mechanics

**Decision**: Use `NSPanel.isMovableByWindowBackground = true`. The whole
popup is draggable by clicking and dragging anywhere on its background; the
header strip serves as the visual affordance but is not a special drag
handle. The minify control is a button placed inside the popup that
captures clicks (so dragging from the button does not move the panel).

**Rationale**: Native, idiomatic, zero custom drag code. NSPanel handles
the drag gesture, hit-test priority for buttons inside the panel works
correctly because `NSButton` participates in normal hit testing.

**Alternatives considered**: Custom drag handler with `mouseDragged(with:)`
override. Rejected — adds code with no advantage over the AppKit default.

---

## R-4. Popup minify / restore

**Decision**: Minify is implemented as a state transition in the
`PopupState` value type owned by `PopupController`:
`expanded(rect: CGRect)` → `minified(point: CGPoint)`. The controller
toggles the visibility of the popup panel and the icon panel based on this
state. Both panels remain allocated for the app's lifetime; only one is
ever ordered on-screen at a time. The popup's last position is preserved
on the `expanded` case so re-expanding restores to the same place.

**Rationale**: Two pre-allocated panels are cheaper than allocating /
deallocating windows on every transition. Preserving position in the state
enum keeps state in one place (Principle I — no scattered "lastFrame"
dictionaries).

**Alternatives considered**: One `NSPanel` that resizes and re-renders its
content for each state. Rejected because the icon and popup are
sufficiently different (size, content, behavior) that two panels are
clearer.

---

## R-5. Icon menu mechanics

**Decision**: Right-click on the icon (or `Control`-click) opens an
`NSMenu` built by `IconContextMenu`. The menu has a "Debug" submenu with
a single item: "Test green bbox". Selecting the item posts a notification
(or invokes a closure) handled by `DebugBboxController`.

**Rationale**: Standard macOS context-menu UX. `NSMenu` is the idiomatic
construct, no custom popover needed for MVP.

**Alternatives considered**: Custom popover view. Rejected — overkill for a
single debug toggle.

---

## R-6. Random bbox positioning

**Decision**: `BboxPositionGenerator` is a pure Swift type that takes a
screen size, a bbox size, and a `RandomNumberGenerator` (defaulting to
`SystemRandomNumberGenerator()`), and returns a `CGPoint` uniformly
distributed within `[0, screenWidth − bboxWidth] × [0, screenHeight −
bboxHeight]`. Tests inject a deterministic RNG (e.g.
`SeededRandomNumberGenerator`) to assert behavior.

**Rationale**: Pure functions with injectable dependencies are trivially
testable. The Spec's SC-004 ("at least 4 distinct positions across 10
trials") becomes a property test against the generator with a fixed seed.

**Alternatives considered**: Use `Int.random(in:)` directly inside the
controller. Rejected — couples logic to the global RNG and prevents
deterministic tests.

---

## R-7. Bbox lifecycle (replacement, not stacking)

**Decision**: `DebugBboxState` is a single `Optional<DebugBoundingBox>`
held by `DebugBboxController`. Selecting "Test green bbox" generates a new
position and assigns it; the prior bbox is discarded; the
`DebugBboxPanel` is updated to render the new state. There is no list of
bboxes.

**Rationale**: Spec FR-013 — at most one bbox on screen at any time.
Modeling as `Optional` rather than a collection makes the invariant
mechanical (the type system enforces it).

**Alternatives considered**: Collection with a clear-then-add pattern.
Rejected — invariant lives in code instead of in the type.

---

## R-8. Chat store for MVP

**Decision**: `ChatMessageStore` is an in-memory ordered list of
`ChatMessage` values. It exposes `append(_ text: String)` and a read-only
`messages: [ChatMessage]`. No persistence; lifetime equals app lifetime.

**Rationale**: Spec assumption: ephemeral chat content. Keeping the store
purely in-memory matches the spec and avoids dragging in any persistence
dependency (Principle II — stay minimal).

**Alternatives considered**: `UserDefaults`-backed persistence. Deferred to
a later feature; the spec explicitly defers cross-launch persistence.

---

## R-9. On-screen clamping for popup and icon

**Decision**: `ScreenBoundsKeeper` is a pure function:
`clamp(frame: CGRect, into screen: CGRect, minimumVisible: CGFloat) ->
CGRect`. It guarantees that at least `minimumVisible` points of the panel
remain on-screen on each axis. The application invokes it after a drag
ends and on display-configuration changes (`NSApplication`'s
`didChangeScreenParametersNotification`).

**Rationale**: Spec FR-009 / edge case — the popup must never become
fully off-screen. A pure function is testable and reusable for both the
popup and the icon.

**Alternatives considered**: Override `NSWindow.constrainFrameRect(_:to:)`.
Rejected — works, but mixes UI and logic; the pure function keeps the
invariant in `Domain/` per Principle V.

---

## R-10. Layered project structure

**Decision**: Source organized by architectural layer (`Domain/`,
`Application/`, `Presentation/`, `App/`) rather than by feature.

**Rationale**: Principle V (Separation of Concerns by Layer) is itself
layer-based. With a layer-based directory layout, an import statement that
reaches the wrong way (e.g., a file in `Domain/` that imports `AppKit`) is
a mechanically detectable violation, surfaced by `grep` or a CI check.
For an MVP with one feature, by-layer is also smaller in practice.

**Alternatives considered**: By-feature organization (`Overlay/`, `Chat/`,
`Debug/`, each containing its own domain + view code). Rejected for this
size — it would require feature-internal sublayers anyway.

---

## R-11. macOS permissions and entitlements

**Decision**: For this MVP no special macOS permissions are required. The
overlay is purely visual; the app does not record the screen, capture
input system-wide, or use accessibility APIs. Entitlements file enables the
App Sandbox with no extra capabilities. `LSUIElement` is set to `true` in
`Info.plist` so the app runs without a Dock icon (it is purely a floating
overlay).

**Rationale**: The spec's permission note ("the app may need standard
overlay-related permissions") was a forward-looking caveat — for the MVP
shell with multi-panel architecture and no input capture, no permission
prompt is needed. Adding accessibility/screen-recording entitlements
later (if a future feature needs them) is a separate scope item.

**Alternatives considered**: Pre-request screen recording / accessibility
permissions on first launch. Rejected — premature and would degrade the
first-run experience without any feature requiring them yet.
