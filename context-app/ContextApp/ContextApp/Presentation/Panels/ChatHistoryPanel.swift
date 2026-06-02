import AppKit

final class ChatHistoryPanel: NSPanel {
    private var closeDelegate: ChatHistoryCloseDelegate?

    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.titled, .closable, .resizable, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        configurePanel()
        configureTrafficLights()
    }

    private func configurePanel() {
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hasShadow = false
        isMovableByWindowBackground = true
        isOpaque = false
        isReleasedWhenClosed = false
        level = .screenSaver
        minSize = NSSize(width: 320, height: 240)
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    private func configureTrafficLights() {
        standardWindowButton(.miniaturizeButton)?.isHidden = true
        standardWindowButton(.zoomButton)?.isEnabled = false

        let delegate = ChatHistoryCloseDelegate()
        self.closeDelegate = delegate
        self.delegate = delegate
    }

    override var canBecomeKey: Bool { true }
}

private final class ChatHistoryCloseDelegate: NSObject, NSWindowDelegate {
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }
}
