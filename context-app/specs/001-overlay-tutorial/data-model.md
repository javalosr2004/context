# Data Model: AI Tutorial Overlay (MVP Shell)

**Feature**: 001-overlay-tutorial
**Date**: 2026-05-05

This feature has no persistence and no cross-process schema. The "data
model" here is the in-process domain types in the `Domain/` layer. Each
type is pure Swift (no AppKit/SwiftUI imports) and is the unit covered by
TDD per Constitution Principle III.

---

## ChatMessage

A single text entry shown in the popup's message list.

```swift
struct ChatMessage: Equatable, Identifiable {
    let id: UUID
    let text: String
    let createdAt: Date
}
```

**Validation**:

- `text` MUST be non-empty after trimming whitespace; `ChatMessageStore`
  rejects empty submissions.
- `id` is generated at construction; the type does not accept an externally
  supplied id (no need in MVP).

**Relationships**: owned exclusively by `ChatMessageStore`.

---

## ChatMessageStore

In-memory ordered list of `ChatMessage` values; lifetime equals app
lifetime.

```swift
final class ChatMessageStore {
    private(set) var messages: [ChatMessage]
    @discardableResult
    func append(_ text: String, now: () -> Date = Date.init) -> ChatMessage?
}
```

**Behavior**:

- `append` returns the new `ChatMessage` on success, `nil` if `text` is
  empty after trimming.
- The store preserves insertion order; oldest first.
- No removal API in MVP — chat is append-only.

**State transitions**: stateless apart from the `messages` array.

---

## PopupState

Closed enum representing whether the popup is expanded or minified, and
where it last sat.

```swift
enum PopupState: Equatable {
    case expanded(frame: CGRect)
    case minified(iconOrigin: CGPoint)

    func minified(at iconOrigin: CGPoint) -> PopupState
    func expanded(at frame: CGRect) -> PopupState
}
```

**Validation**:

- `frame.size` MUST satisfy a minimum of (240 × 320) — enforced by the
  caller at construction time, asserted in tests.
- Transitions are total: any state can move to either case.

**State transitions**:

```text
expanded(frame) ── minify ──► minified(iconOrigin)
minified(origin) ── expand ─► expanded(frame)
```

The previous-position memory lives inside the case payloads (no separate
`lastFrame: CGRect?` field anywhere — single source of truth).

---

## DebugBoundingBox

A 500×500 green-outlined rectangle position. Owned by `DebugBboxState`
(see below).

```swift
struct DebugBoundingBox: Equatable {
    static let size = CGSize(width: 500, height: 500)
    let origin: CGPoint
}
```

**Validation**:

- `origin.x` MUST satisfy `0 ≤ origin.x ≤ screenWidth − 500`.
- `origin.y` MUST satisfy `0 ≤ origin.y ≤ screenHeight − 500`.
- Construction always goes through `BboxPositionGenerator`, which
  guarantees the invariant.

---

## DebugBboxState

A single optional `DebugBoundingBox`. Selecting "Test green bbox" replaces
the value; the controller listens for changes and re-renders the panel.

```swift
final class DebugBboxState {
    private(set) var current: DebugBoundingBox?
    func replace(with bbox: DebugBoundingBox?)
}
```

**Invariant**: at most one bbox exists at a time. `Optional` rather than
`[DebugBoundingBox]` makes the invariant a property of the type itself.

---

## BboxPositionGenerator

Pure function (modeled as a stateless type to inject a custom
`RandomNumberGenerator`).

```swift
struct BboxPositionGenerator {
    func position<R: RandomNumberGenerator>(
        screen: CGSize,
        bbox: CGSize,
        rng: inout R
    ) -> CGPoint
}
```

**Behavior**:

- Returns a uniformly distributed point in
  `[0, screen.width − bbox.width] × [0, screen.height − bbox.height]`.
- If the screen is smaller than the bbox on either axis, the function
  preconditions on this and triggers a runtime error in debug builds; the
  caller is responsible for not invoking with a too-small screen.

**Tests** (Constitution Principle III applies — these are written first):

- Property: result is always within the valid rectangle, for fuzzed
  screen / bbox sizes.
- Determinism: with a seeded RNG, repeated calls yield the same sequence
  of points.
- Spec SC-004: 10 calls with `SystemRandomNumberGenerator()` produce ≥ 4
  distinct points (with effectively-1.0 probability).

---

## ScreenBoundsKeeper

Pure function that ensures a window's frame keeps a minimum on-screen
visibility.

```swift
struct ScreenBoundsKeeper {
    func clamp(
        frame: CGRect,
        into screen: CGRect,
        minimumVisible: CGFloat
    ) -> CGRect
}
```

**Behavior**:

- Returns a frame translated (never resized) so that at least
  `minimumVisible` points of `frame` overlap `screen` on each axis.
- If `frame` is already fully on-screen, returns it unchanged.
- If `frame.size` is larger than `screen.size`, prefers visibility over
  containment (top-left corner clamps to screen origin; the bottom-right
  may be off-screen).

**Tests**: corner cases — fully off-screen, partially off the right
edge, partially off the bottom, larger than screen, exactly fitting.

---

## Layer placement

All of the above live in `ContextApp/Domain/` with `import Foundation`
only. None of them imports `AppKit` or `SwiftUI`; that is enforced by
Constitution Principle V and is mechanically checkable via `grep`.

The controllers in `ContextApp/Application/` (`PopupController`,
`DebugBboxController`, `IconMenuController`, `OverlayCoordinator`)
compose these domain types and mediate between them and the panels in
`ContextApp/Presentation/`.
