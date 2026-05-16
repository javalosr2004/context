# Feature Specification: AI Tutorial Overlay (MVP Shell)

**Feature Branch**: `001-overlay-tutorial`
**Created**: 2026-05-05
**Status**: Draft
**Input**: User description: "Build an application that has a transparent overlay over the entire user screen and has priority over anything. This will be a AI tutorial layer. It will have a popup that is dragabble and minifiable to a small icon. This will serve as the instruction base. The user can press it and have the instructions / text from the chat pop up. This is a simple chat interface. The screen (not the chat-window) extends to the entire user screen and is transparent. For this MVP we will simply test out functionality by having a debug option in the menu icon which has an item entry - test green bbox, it will display a bbox of 500x500 in a random location."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Always-On-Top Transparent Overlay with Chat Popup (Priority: P1)

The user launches the application. A fully transparent overlay appears covering their entire primary screen, sitting above every other window. A draggable popup containing a chat-style message area and a text input field is visible somewhere on the overlay. The user can drag the popup anywhere on screen, click a control to minify it into a small icon, and click the icon to expand it back into the popup. While the overlay is active, the user can still see and interact with the apps beneath it normally — only the popup and icon themselves intercept mouse input.

**Why this priority**: Without this, there is no surface to host any tutorial content. Every other story depends on this shell existing. This alone is a demonstrable MVP increment that proves the platform-level overlay/click-through behavior works.

**Independent Test**: Launch the app on a Mac. Confirm: (a) the entire primary display is covered by an invisible-but-present overlay that stays above other apps; (b) the popup is visible, draggable, and minifies/restores cleanly; (c) clicks outside the popup/icon reach the apps below (e.g., a Finder window can be focused by clicking it through the overlay).

**Acceptance Scenarios**:

1. **Given** the app is not running, **When** the user launches it, **Then** within 2 seconds a transparent overlay covers the primary display and a chat popup is visible above all other windows.
2. **Given** the popup is visible, **When** the user drags its title bar, **Then** the popup follows the cursor and stays at the released position.
3. **Given** the popup is visible, **When** the user activates the minify control, **Then** the popup collapses into a small icon at or near its previous position.
4. **Given** the popup is minified, **When** the user clicks the icon, **Then** the popup expands back to its prior size with prior chat content intact.
5. **Given** the overlay is active and the popup is not under the cursor, **When** the user clicks an underlying app's window, **Then** that app receives the click as if the overlay were not there.

---

### User Story 2 - Debug Menu: Test Green Bounding Box (Priority: P2)

From the minified icon, the user opens a menu and selects a Debug entry called "Test green bbox". A 500-pixel × 500-pixel green outlined rectangle appears at a random position on the overlay, demonstrating that the application can draw arbitrary visual content over the user's screen. Selecting the entry again replaces the previous bbox with a new one at a new random location.

**Why this priority**: This is the explicit MVP validation hook. It proves end-to-end that the overlay can render targeted visual annotations — the foundation of any future tutorial highlighting feature — without requiring AI integration yet.

**Independent Test**: With the app running, right-click (or otherwise open the menu on) the minified icon, choose Debug → "Test green bbox", and verify a 500×500 green outlined rectangle appears on screen at a position that varies across repeated invocations.

**Acceptance Scenarios**:

1. **Given** the icon is visible, **When** the user opens its menu, **Then** a "Debug" section containing a "Test green bbox" entry is shown.
2. **Given** the menu is open, **When** the user selects "Test green bbox", **Then** a 500×500 green outlined rectangle is rendered on the overlay within 200 ms.
3. **Given** a previous bbox is on screen, **When** the user selects "Test green bbox" again, **Then** the previous rectangle is removed and a new one appears at a different random position.
4. **Given** "Test green bbox" has been triggered ten times in succession, **Then** the rectangle has appeared in at least four distinct on-screen positions across those trials.

---

### User Story 3 - Basic Chat Display and Input (Priority: P3)

The expanded popup behaves as a simple chat surface: it shows a scrollable list of previously displayed messages and an input field at the bottom. The user can type text and submit it; the submitted text is appended to the message list. There is no AI backend yet — the popup is the visual shell that future tutorial/instruction content will populate.

**Why this priority**: The popup must look and feel like the eventual chat surface so later phases (real AI instructions, streamed steps) drop in without UI rework. Without it, the popup is a placeholder rectangle.

**Independent Test**: Open the popup, type a message in the input field, press the submit key, and confirm the message appears in the list above the input field. Scroll the list when more messages exist than fit in the viewport.

**Acceptance Scenarios**:

1. **Given** the popup is expanded, **When** the user types text and submits it, **Then** the text appears as a new entry at the bottom of the message list.
2. **Given** more messages exist than fit on screen, **When** the user scrolls the message area, **Then** older messages become visible.
3. **Given** the popup is minified after messages have been sent, **When** the user expands it again, **Then** all prior messages remain visible in their original order.

---

### Edge Cases

- **Popup dragged partially off-screen**: The popup MUST remain at least partially on-screen and re-grabbable; it must never become unreachable.
- **Rapid Debug bbox triggering**: Repeated invocation MUST replace (not stack) the bbox; only one debug bbox is on screen at a time.
- **Display configuration change while running**: If the user changes resolution or the display is reconnected, the overlay MUST resize to fit the new primary-display bounds; the popup, icon, and bbox MUST remain on-screen.
- **Another app enters fullscreen exclusive mode**: The overlay's behavior in this case is undefined for MVP and MAY be hidden by the OS; this is acceptable and not a regression.
- **App relaunch**: On relaunch, chat content from the previous session is not preserved (ephemeral by default in MVP).

## Requirements *(mandatory)*

### Functional Requirements

**Overlay surface**

- **FR-001**: The application MUST display a fully transparent overlay covering the entire primary display.
- **FR-002**: The overlay MUST remain visually above all other application windows.
- **FR-003**: Mouse and keyboard input over transparent regions of the overlay MUST pass through to the application beneath; only the popup, the minified icon, the menu, and the debug bbox MUST intercept input.
- **FR-004**: The overlay MUST resize to match the primary display bounds when display configuration changes.

**Popup and minified icon**

- **FR-005**: The application MUST render a chat-style popup containing a header/drag region, a scrollable message list, and a single-line text input field.
- **FR-006**: Users MUST be able to drag the popup to any position; on release, the popup MUST stay at that position.
- **FR-007**: The popup MUST expose a control to minify it; activating this control MUST collapse the popup into a small icon while preserving message-list contents.
- **FR-008**: Activating (clicking) the minified icon MUST expand it back into the popup at its previous size and position, with message-list contents intact.
- **FR-009**: The popup MUST NOT be draggable to a position where it becomes entirely off-screen; if forced off-screen by a display change, the application MUST reposition it to a fully-visible location.

**Menu and debug bbox**

- **FR-010**: The minified icon MUST expose a menu accessible by a standard user interaction (right-click or equivalent).
- **FR-011**: The menu MUST contain a "Debug" section with at least one entry labelled "Test green bbox".
- **FR-012**: Selecting "Test green bbox" MUST render a 500×500 green-outlined rectangle on the overlay at a pseudo-random position fully contained within the visible primary-display bounds.
- **FR-013**: A second invocation of "Test green bbox" MUST remove any prior debug bbox and render a new one at a new random position; at most one debug bbox is on screen at any time.

**Chat behaviour (MVP placeholder)**

- **FR-014**: Submitting text from the input field MUST append that text as a new entry at the bottom of the message list.
- **FR-015**: The message list MUST remain scrollable when its contents exceed the viewport.
- **FR-016**: No AI/LLM backend is required for this MVP; the chat is a UI shell only.

### Key Entities

- **Overlay**: The full-display, always-on-top, transparent surface that hosts every other UI element. Owns the bounds-tracking and click-through behaviour.
- **Popup**: The chat-style window containing the header (drag handle + minify control), message list, and input field. Has a position, a size, and a minified/expanded state.
- **Icon**: The minified representation of the popup. Has a position and exposes a context menu.
- **Menu**: The context menu attached to the icon. Currently contains one Debug section with a single "Test green bbox" entry.
- **DebugBoundingBox**: A 500×500 green-outlined rectangle rendered on the overlay at a random position. At most one exists at a time.
- **ChatMessage**: A single text entry in the message list (origin: user-submitted in MVP).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From cold start, the overlay and popup are visible to the user within 2 seconds.
- **SC-002**: Dragging the popup feels immediate — it tracks the cursor with no perceptible lag (<100 ms perceived response).
- **SC-003**: After the user selects "Test green bbox", the rectangle is visible within 200 ms.
- **SC-004**: Across 10 successive invocations of "Test green bbox", the rectangle appears in at least 4 distinct on-screen positions.
- **SC-005**: When the user clicks an underlying application's window in a region not covered by the popup, icon, menu, or debug bbox, that application receives the click in 100% of trials.
- **SC-006**: Minifying and re-expanding the popup preserves all previously displayed messages with no visible loss of order or content.
- **SC-007**: The user can dismiss or replace the debug bbox without restarting the app.

## Assumptions

- **macOS-first**: This MVP targets macOS only. Windows/Linux behaviour is out of scope.
- **Single primary display**: Multi-display support is out of scope for this MVP; the overlay covers the primary display only.
- **Click-through default**: Transparent regions of the overlay pass clicks through to the apps below; this is a core requirement of the "tutorial layer" concept and is treated as fundamental rather than configurable.
- **Bbox style**: The debug bbox is an outlined (not filled) green rectangle so the user can still see the screen content beneath it.
- **One bbox at a time**: New bbox replaces old; the debug control is a "show one" trigger, not an "add one" trigger.
- **No AI/LLM in this MVP**: The chat is a UI shell. Wiring an instruction generator is a later phase.
- **Ephemeral chat content**: Chat content does not persist across app launches in this MVP.
- **Permissions**: The app may need standard macOS overlay-related permissions (e.g., screen recording or accessibility, depending on implementation choice). The user grants these on first launch; permission flows themselves are not part of this spec's success criteria.
- **Random position bounds**: "Random position" means uniformly distributed within `[0, screen_width − 500] × [0, screen_height − 500]` so the bbox is fully on-screen.
