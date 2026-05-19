import AppKit

final class EdgeTabPanel: NSPanel {
    var onShiftRightClick: (() -> Void)?

    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        configurePanel()
    }

    private func configurePanel() {
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hasShadow = true
        isMovable = false
        isMovableByWindowBackground = false
        isOpaque = false
        isReleasedWhenClosed = false
        level = .screenSaver
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    override func rightMouseDown(with event: NSEvent) {
        if event.modifierFlags.contains(.shift), let onShiftRightClick {
            onShiftRightClick()
            return
        }
        super.rightMouseDown(with: event)
    }
}
