import AppKit

final class EdgeTabPanel: NSPanel {
    var onShowOverlay: (() -> Void)?
    var onShowDevSettings: (() -> Void)?

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
        guard let view = contentView else { return }
        let menu = buildContextMenu()
        NSMenu.popUpContextMenu(menu, with: event, for: view)
    }

    private func buildContextMenu() -> NSMenu {
        let menu = NSMenu()

        let show = NSMenuItem(title: "Show Overlay", action: #selector(handleShowOverlay), keyEquivalent: "")
        show.target = self
        menu.addItem(show)

        menu.addItem(.separator())

        // Alternate-item pair: hidden placeholder shown without modifiers; the alternate
        // "Developer Settings…" item replaces it when Shift is held while the menu is open.
        let placeholder = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        placeholder.isHidden = true
        menu.addItem(placeholder)

        let dev = NSMenuItem(title: "Developer Settings…", action: #selector(handleShowDevSettings), keyEquivalent: "")
        dev.target = self
        dev.keyEquivalentModifierMask = .shift
        dev.isAlternate = true
        menu.addItem(dev)

        menu.addItem(.separator())

        let quit = NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quit)

        return menu
    }

    @objc private func handleShowOverlay() {
        onShowOverlay?()
    }

    @objc private func handleShowDevSettings() {
        onShowDevSettings?()
    }
}
