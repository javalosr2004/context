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
