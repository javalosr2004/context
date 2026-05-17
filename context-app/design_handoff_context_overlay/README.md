# Handoff: Context Tutorial Overlay (Hybrid A)

## Overview

Context is a macOS overlay that turns a recorded workflow into a live, step-by-step tutorial. This handoff covers the redesigned **controller view** — the small floating card that shows the user where they are in a tutorial and lets them ask questions inline.

The design replaces a cluttered scrolling list of all steps with a **focused peek-stack** (just-did / now / up-next) and a persistent **"Ask Context"** input bar at the bottom. When the user asks a question mid-tutorial, the answer slots in as a card above the stack and the tutorial auto-pauses until they hit Resume.

**Goals of the redesign:**
- Cut visual noise; show only what matters right now.
- Make "where am I?" answerable in <1 second.
- Make Q&A a first-class affordance, not a hidden mode.
- Match macOS look & feel (vibrancy, traffic lights, system type).

## About the Design Files

The files bundled here are **design references created in HTML/React** — prototypes that show the intended look and behavior, not production code to ship verbatim. Your task is to **recreate these designs in the existing macOS codebase** (likely SwiftUI for a native overlay, or whatever the host app uses) using established patterns, components, and the system's real vibrancy materials.

If the project doesn't already have a UI environment, use SwiftUI with `NSVisualEffectView` / `Material` for the vibrancy — this overlay is macOS-only and benefits from native materials over a web-based approximation.

## Fidelity

**High-fidelity.** Spacing, type, sizes, colors, and component anatomy are all specified below. The vibrancy values approximate macOS `.hudWindow` / `.popover` materials — substitute the actual system material on macOS rather than copying the CSS rgba/blur values.

## Screens / Views

There is **one overlay window** that renders 5 different states. The window is fixed at **340 pt wide** (height varies by state). All states share the same chrome.

### Shared chrome (top bar) — 36 pt tall

- **Traffic lights** (close / minimize / maximize), 12 pt diameter, 6 pt gap, 12 pt from left edge. Use system traffic lights — don't draw your own.
- **New chat button** ("pencil/compose" icon), 24×24 pt, 12 pt from right edge. Tap = clear current Q&A history, open a fresh ask state. Hover bg `rgba(0,0,0,0.06)`, icon color `rgba(0,0,0,0.55)` → `rgba(0,0,0,0.8)` on hover.
- The entire bar is window-draggable (`-webkit-app-region: drag` in the prototype; on macOS it's free since the whole panel can be dragged from anywhere non-interactive).

### State 1 — Idle (default tutoring)

Layout, top to bottom:
1. **Chrome** (above).
2. **Meta row** (28 pt tall, 16 pt horizontal padding). Left: tutorial name in `uppercase` 11 pt with 0.04em tracking, color `rgba(0,0,0,0.5)`. Right: `3 of 12` in SF Mono 11 pt, same color, not uppercased.
3. **Progress bar** — 2 pt high, full width minus 14 pt L/R inset, `rgba(0,0,0,0.07)` track, `rgba(0,0,0,0.55)` fill, 1 pt radius.
4. **Peek stack** (12 pt top pad, 10 pt L/R pad, 8 pt bottom pad). Three rows:
   - **Done row** — 7 pt vertical, 10 pt horizontal pad, 12 pt gap between marker and text. Marker: 18×18 pt circle, just an SF Symbols checkmark in `rgba(0,0,0,0.4)`. Text: SF Text 13 pt regular, `rgba(0,0,0,0.42)`, **strikethrough** with `rgba(0,0,0,0.25)` strike color.
   - **Now row** — same paddings but with a `rgba(0,0,0,0.05)` background fill and 0.5 pt inset border `rgba(0,0,0,0.08)`, 9 pt corner radius. Marker: 18×18 pt black filled disc `#1A1A1C` with a thin halo (3 pt `rgba(0,0,0,0.06)` outer ring) and a small inner dot in `#F8F6F4`. Text: SF Text 14 pt semibold (600), `#0A0A0C`.
   - **Next row** — same paddings, no fill. Marker: 18×18 pt circle with **dashed** 1 pt border `rgba(0,0,0,0.25)`, contains a right-arrow glyph in the same color. Text: 13 pt regular, `rgba(0,0,0,0.4)`.
5. **Ask bar** — top border 0.5 pt `rgba(0,0,0,0.08)`. 9 pt vertical, 12 pt horizontal pad. Background `rgba(255,255,255,0.32)`. Layout: sparkle icon (13 pt, `rgba(0,0,0,0.45)`) · placeholder "Ask Context anything" (SF Text 13 pt, `rgba(0,0,0,0.42)`) · keyboard hint `⌘K` (SF Mono 10.5 pt, `rgba(0,0,0,0.4)`, 2/6 pt padding, 4 pt radius, `rgba(0,0,0,0.04)` bg, 0.5 pt inset border).

### State 2 — User typing

Same as Idle, but the **ask bar** is in input mode:
- Sparkle still on the left (same color).
- Typed text in SF Text 13 pt, `#0A0A0C`. Live caret: 1.2 pt × 14 pt black bar, blinks at 1s steps(2).
- Replace the `⌘K` hint with an `esc` hint (same styling).
- Add a **send button** at the right edge: 22×22 pt, 6 pt radius, `rgba(0,0,0,0.85)` background, `#F8F6F4` foreground, simple "up arrow" icon (12 pt).

### State 3 — AI streaming (answer in progress)

The tutorial **pauses**. Layout changes:
1. Chrome unchanged.
2. Meta row: right side now says `paused` (lowercase, same SF Mono 11 pt color) instead of `3 of 12`. Progress bar still rendered.
3. **Answer card** (slotted in above the stack):
   - 10 pt top, 12 pt L/R margin from card edge; 4 pt bottom margin to the stack.
   - 12/14 pt vertical/horizontal interior padding, 10 pt radius, `rgba(255,255,255,0.55)` bg, 0.5 pt inset border `rgba(0,0,0,0.08)`.
   - Header row: sparkle (11 pt) + label `Answer · tutorial paused` (10.5 pt uppercase, 0.04em tracking, `rgba(0,0,0,0.45)`).
   - Q echo: italic 12 pt, `rgba(0,0,0,0.55)`, quoted.
   - Streaming body: 13.5 pt / 1.45 line height, `#0A0A0C`. Inline code spans use SF Mono 12 pt with 1/5 pt padding, 4 pt radius, `rgba(0,0,0,0.05)` bg. **Trailing typing dots** appear at the end of the streamed text: 3 dots, 5 pt each, 4 pt gap, color `#0A0A0C` at 30% opacity, bouncing in sequence (150ms stagger, 1.2s loop, vertical -1 pt on the peak).
4. **Steps stack** still renders but at 35% opacity and pointer-events disabled.
5. Ask bar unchanged from Idle (placeholder restored).

### State 4 — Answer shown · Resume

Same skeleton as State 3, but the body is the complete response (no typing dots), and an **actions row** appears below the body:
- 10 pt top margin, 6 pt gap.
- **Primary button** "↩ Resume tutorial": SF Text 12 pt, 5/11 pt padding, 7 pt radius, `#1A1A1C` bg, `#F8F6F4` text. Hover `#000`.
- **Ghost button** "Ask follow-up": transparent bg, `rgba(0,0,0,0.55)` text, same paddings.

The Resume action: removes the answer card, restores meta-row right side to `3 of 12`, returns the stack to full opacity, focuses the ask bar's host on the underlying app again.

### State 5 — Tutorial finished

Stack and meta row are replaced by a centered celebration block:
- Top pad 28 pt, side pad 24 pt, bottom pad 24 pt.
- **Check disc**: 44×44 pt circle, `#1A1A1C` bg, `#F8F6F4` checkmark glyph, 14 pt bottom margin.
- **Title** "All done": SF Display 18 pt semibold (600), -0.01em tracking, `#0A0A0C`.
- **Subtitle** "12 steps · Runpod Setup": 12 pt uppercase 0.04em tracking, `rgba(0,0,0,0.5)`, 4 pt top margin.
- **Actions row** (18 pt top margin): a single primary button "Start new tutorial" (same primary button styling as State 4).
- Ask bar remains at the bottom in its idle form.

## Interactions & Behavior

- **Open the overlay**: window appears with a brief scale-up (98% → 100%, 180 ms ease-out) and a fade (0 → 1, same duration). Position: floating above active app, user-draggable, position persisted between sessions.
- **Tutorial progression**: when a step is auto-detected as complete, the done/now/next rows shift up by one row (220 ms `cubic-bezier(.2,.7,.3,1)`). The new "now" row briefly pulses its background fill (`rgba(0,0,0,0.05)` → `rgba(0,0,0,0.1)` → back, 600 ms).
- **Ask bar focus** (click or `⌘K` from anywhere): bar swaps from idle → typing in 100 ms; placeholder fades, caret appears.
- **Submit** (`↩`): bar collapses back to idle styling immediately; answer card mounts above the stack with a 180 ms slide+fade (translateY 8 pt → 0, opacity 0 → 1); steps fade to 35% over 160 ms.
- **Streaming**: text appends token-by-token; typing dots only show when the stream is still active.
- **Resume**: answer card unmounts with the inverse animation; steps return to 100% opacity.
- **New chat (pencil)**: clears current question/answer state, returns to Idle.
- **Esc while typing**: clear the input, return to Idle ask-bar styling.
- **Tutorial finished**: stack animates out (upward fade), check + title animate in (scale + fade, 240 ms ease-out, 80 ms stagger).
- **Hover targets**: traffic lights, pencil, send, and the action buttons all show a `rgba(0,0,0,0.06)` hover bg (or `rgba(0,0,0,0.10)` for the ghost button).

## State Management

State variables (suggested):
- `tutorial: { id, name, totalSteps, currentStep, status: 'idle'|'paused'|'finished' }` — the tutorial source of truth, driven by the recognizer/agent.
- `askState: 'idle' | 'typing' | 'streaming' | 'answered'` — controls the ask bar and the presence of the answer card.
- `currentQuestion: string` — typed input.
- `currentAnswer: { text: string, isStreaming: boolean }` — populated by the LLM/stream provider.

Transitions:
- `askState` is `idle` by default. Focusing the bar (or `⌘K`) → `typing`. Submit → `streaming` (also sets `tutorial.status = 'paused'`). Stream end → `answered`. Resume action → `idle` (and `tutorial.status = 'idle'`). Pencil → `idle` (clear `currentQuestion` / `currentAnswer`).
- `tutorial.currentStep` is incremented by the workflow-detection layer; the UI reacts via the stack-shift animation above.
- `tutorial.status = 'finished'` when `currentStep > totalSteps`; the UI replaces the stack with State 5.

## Design Tokens

### Colors (light vibrancy)

| Token | Value | Use |
|---|---|---|
| `surface/vibrancy` | `rgba(248, 246, 244, 0.62)` over `backdrop-filter: blur(24px) saturate(180%)` | Card background — substitute system `.hudWindow` material on macOS |
| `surface/answer` | `rgba(255, 255, 255, 0.55)` | Answer card inner panel |
| `surface/ask` | `rgba(255, 255, 255, 0.32)` | Ask bar bg |
| `surface/hover` | `rgba(0, 0, 0, 0.06)` | Icon button hover |
| `surface/now-fill` | `rgba(0, 0, 0, 0.05)` | Current step row bg |
| `text/primary` | `#0A0A0C` | Main text, now row |
| `text/secondary` | `rgba(0, 0, 0, 0.55)` | Subdued (icons, ghost btn) |
| `text/tertiary` | `rgba(0, 0, 0, 0.45)` | Placeholders, labels |
| `text/quaternary` | `rgba(0, 0, 0, 0.40)` | Done step text, next-step text |
| `text/done` | `rgba(0, 0, 0, 0.42)` | Done step text (strike) |
| `stroke/hairline` | `rgba(0, 0, 0, 0.08)` | Inset borders, separators |
| `accent/inverted` | `#1A1A1C` | Primary buttons, now-marker disc, send |
| `accent/inverted-fg` | `#F8F6F4` | Foreground on `accent/inverted` |
| `traffic/close` | `#FB6058` | Use system traffic lights |
| `traffic/min` | `#FDBE40` | — |
| `traffic/max` | `#2DC940` | — |

There is **no chromatic accent**. Hierarchy is built entirely through value (gray steps) and weight.

### Typography

System font stack (`-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display'`). All sizes in pt.

| Role | Size | Weight | Tracking | Notes |
|---|---|---|---|---|
| Step / now | 14 | 600 | normal | `#0A0A0C` |
| Step / done & next | 13 | 400 | normal | Secondary colors per table above |
| Ask bar text | 13 | 400 | normal | — |
| Answer body | 13.5 | 400 | normal | 1.45 line height |
| Answer Q echo | 12 | 400 italic | normal | Secondary color |
| Meta label | 11 | 500 | 0.04em | uppercase, tertiary color |
| Progress / counter | 11 | 500 | normal | SF Mono |
| Inline code | 12 | 500 | normal | SF Mono, `surface/hover` bg, 4 pt radius |
| Finished title | 18 | 600 | -0.01em | normal case |
| Finished sub | 12 | 500 | 0.04em | uppercase |
| Keyboard hint | 10.5 | 400 | normal | SF Mono |
| Button text | 12 | 500 | normal | — |

### Spacing scale

`4 / 6 / 8 / 10 / 12 / 14 / 16 / 18 / 24 / 28` pt. Card-level paddings use 10/12/16; row-internal use 6/8/10.

### Radii

- Card outer: 14 pt
- Answer card inner: 10 pt
- Step row: 9 pt
- Button (small): 7 pt
- Icon button: 6 pt
- Keyboard hint chip: 4 pt
- Markers: 50% (pill)
- Progress bar: 1 pt

### Shadows

Card (substitute system material elevation if available):
```
inset 0  0.5 0  rgba(255,255,255,0.7),     // top highlight
inset 0  0   0  0.5 rgba(0,0,0,0.10),      // hairline border
0 1 2 rgba(0,0,0,0.12),                    // close shadow
0 12 40 rgba(0,0,0,0.22),                  // mid lift
0 24 80 rgba(0,0,0,0.18)                   // ambient
```

Now-marker disc: `0 0 0 3pt rgba(0,0,0,0.06)` (halo).

### Materials (macOS native equivalents)

- Card → `NSVisualEffectView.material = .hudWindow` (or `.popover`); `blendingMode = .behindWindow`.
- Always render the card on **light vibrancy** in this design. If you support dark mode, mirror the same component anatomy with inverted text/surface tokens — open question for product, not specified here.

## Assets

- **Pencil / compose icon**: SF Symbols `square.and.pencil` (or `pencil.line`).
- **Sparkle icon**: SF Symbols `sparkle` (single) — small accent in the ask bar and answer card header.
- **Send arrow**: SF Symbols `arrow.up` (in a filled square button).
- **Checkmark (done step + finished disc)**: SF Symbols `checkmark`.
- **Next-step arrow**: SF Symbols `arrow.right` inside a dashed circle.
- **Traffic lights**: system-provided.

No raster assets. No custom logo in the chrome (the existing "Context" wordmark from the previous design is intentionally removed for minimalism — confirm with product before stripping it system-wide).

## Files in this bundle

- `README.md` — this document.
- `hifi.jsx` — the React/HTML prototype of all 5 states. The CSS in the `HFCSS` template literal at the top of the file is the most precise source of truth for paddings, opacities, radii, and shadows. Read the component bodies (`HFIdle`, `HFTyping`, `HFStreaming`, `HFAnswered`, `HFFinished`) for the exact DOM structure of each state.
- `Overlay Wireframes.html` — the full canvas (wireframes + hybrids + hi-fi). Open in a browser to interact with the design; the Hi-fi section is at the top.

## Open questions for product / design

- **Dark mode**: not specified yet. Same anatomy, inverted tokens.
- **Context window**: where does the overlay sit by default? (Top-right of screen, near the menu bar, is a reasonable starting point.)
- **Persistence**: does Q&A history survive across tutorials? The pencil ("new chat") implies yes, but the answer surface only shows the latest Q+A. A "history" button is not in this design — confirm.
- **Confidence / confirmation prompts**: the previous wireframes explored a "Are you here?" state when AI confidence is low. Not represented in the hi-fi pass — decide if it should reuse the answer-card slot or get its own treatment.
