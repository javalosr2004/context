# ContextApp

macOS-first overlay shell for the AI Tutorial Overlay MVP.

## Architecture

- `App/`: SwiftUI app entry point and AppKit lifecycle delegate.
- `Domain/`: pure Swift state and geometry logic. Files here must not import `AppKit` or `SwiftUI`.
- `Application/`: coordinators and controllers that compose domain logic with panels and views.
- `Presentation/`: `NSPanel`, `NSMenu`, and SwiftUI rendering.
- `Resources/`: app metadata and entitlements.

## Domain Import Guard

Run this from `context-app` before committing changes that touch `Domain/`:

```bash
rg '^import (AppKit|SwiftUI)$' ContextApp/ContextApp/Domain
```

Expected result: no matches.

## Build And Test

```bash
cd ContextApp
xcodebuild -scheme ContextApp -destination 'platform=macOS' test
```

Last verification attempt on 2026-05-05:

- `swiftc -target arm64-apple-macosx13.0 -typecheck ...`: PASS for app sources.
- Domain import guard: PASS; no `Domain/` file imports `AppKit` or `SwiftUI`.
- `xcodebuild -scheme ContextApp -destination 'platform=macOS' test`: BLOCKED before project build. Xcode 26.4.1 failed to load `IDESimulatorFoundation` because `DVTDownloads.framework` is missing the expected `developerDocumentation` symbol. Xcode suggests running `xcodebuild -runFirstLaunch` or repairing the Xcode installation.

## Manual Validation

- US1: Launch the app and confirm the popup appears within 2 seconds, stays above app windows, drags smoothly, minifies to an icon, restores at the prior position, and clicks outside panels reach underlying apps.
- US2: Select Bounding Boxes > Configure Bounding Boxes from the macOS app menu and confirm one 500x500 green outline appears fully on screen and is replaced on repeated selections.
- US3: Submit several messages, confirm they appear in insertion order, minify and restore, then confirm the messages remain.

SC-001 through SC-007 still need live validation after the local Xcode installation can build and launch the app.

## Troubleshooting

- If the Dock icon appears, confirm `LSUIElement` is true in `Resources/Info.plist`.
- If panels appear behind other apps, confirm each panel uses `.screenSaver` level.
- If clicks do not pass through, confirm the click is outside the popup and icon panels. The bbox panel is click-through by design.
