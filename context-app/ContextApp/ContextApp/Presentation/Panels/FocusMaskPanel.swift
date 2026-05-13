import AppKit

final class FocusMaskPanel: NSPanel {
    private let canBecomeKeyValue: Bool

    init(frame: NSRect, ignoresMouseEvents: Bool, canBecomeKey: Bool = false) {
        self.canBecomeKeyValue = canBecomeKey
        super.init(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        configurePanel(ignoresMouseEvents: ignoresMouseEvents)
    }

    private func configurePanel(ignoresMouseEvents: Bool) {
        acceptsMouseMovedEvents = false
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hasShadow = false
        self.ignoresMouseEvents = ignoresMouseEvents
        isOpaque = false
        level = .screenSaver
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    override var canBecomeKey: Bool {
        canBecomeKeyValue
    }
}
