import AppKit

final class IconContextMenu {
    private let onTestBbox: () -> Void

    init(onTestBbox: @escaping () -> Void) {
        self.onTestBbox = onTestBbox
    }

    func makeMenu() -> NSMenu {
        let menu = NSMenu()
        let debugItem = NSMenuItem(title: "Debug", action: nil, keyEquivalent: "")
        debugItem.submenu = makeDebugMenu()
        menu.addItem(debugItem)
        return menu
    }

    private func makeDebugMenu() -> NSMenu {
        let menu = NSMenu(title: "Debug")
        let testItem = CallbackMenuItem(title: "Test green bbox", actionHandler: onTestBbox)
        menu.addItem(testItem)
        return menu
    }
}

private final class CallbackMenuItem: NSMenuItem {
    private let actionHandler: () -> Void

    init(title: String, actionHandler: @escaping () -> Void) {
        self.actionHandler = actionHandler
        super.init(title: title, action: #selector(runAction), keyEquivalent: "")
        target = self
    }

    required init(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    @objc private func runAction() {
        actionHandler()
    }
}

