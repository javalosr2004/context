import AppKit

final class PopupPanel: NSPanel {
    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        configurePanel()
    }

    private func configurePanel() {
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hasShadow = true
        isMovableByWindowBackground = true
        isOpaque = false
        isReleasedWhenClosed = false
        level = .screenSaver
        minSize = PopupState.minimumSize
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    override var canBecomeKey: Bool {
        true
    }
}

