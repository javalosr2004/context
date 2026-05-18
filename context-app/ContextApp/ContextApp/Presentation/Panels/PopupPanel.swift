import AppKit

@MainActor
protocol PopupPanelDelegate: AnyObject {
    func popupPanelDidRequestCollapse()
}

final class PopupPanel: NSPanel {
    weak var popupDelegate: PopupPanelDelegate?
    private var closeDelegate: PopupCloseDelegate?

    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView, .nonactivatingPanel],
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
        minSize = PopupState.minimumSize
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    private func configureTrafficLights() {
        // TODO: future chat-window expansion mode — re-enable the green zoom button.
        standardWindowButton(.zoomButton)?.isEnabled = false

        let closeDelegate = PopupCloseDelegate()
        self.closeDelegate = closeDelegate
        self.delegate = closeDelegate
    }

    override func miniaturize(_ sender: Any?) {
        popupDelegate?.popupPanelDidRequestCollapse()
    }

    override var canBecomeKey: Bool {
        true
    }
}

private final class PopupCloseDelegate: NSObject, NSWindowDelegate {
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        NSApplication.shared.terminate(nil)
        return false
    }
}
