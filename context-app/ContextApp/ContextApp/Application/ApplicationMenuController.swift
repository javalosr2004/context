import AppKit

@MainActor
final class ApplicationMenuController {
    private let onConfigureBoundingBoxes: () -> Void
    private var boundingBoxesMenuItem: NSMenuItem?

    init(onConfigureBoundingBoxes: @escaping () -> Void) {
        self.onConfigureBoundingBoxes = onConfigureBoundingBoxes
        installMenu()
    }

    func stop() {
        guard let boundingBoxesMenuItem else { return }
        NSApp.mainMenu?.removeItem(boundingBoxesMenuItem)
        self.boundingBoxesMenuItem = nil
    }

    private func installMenu() {
        guard let mainMenu = NSApp.mainMenu else { return }

        let menuItem = NSMenuItem(title: "Bounding Boxes", action: nil, keyEquivalent: "")
        menuItem.submenu = makeBoundingBoxesMenu()
        mainMenu.insertItem(menuItem, at: insertionIndex(in: mainMenu))
        boundingBoxesMenuItem = menuItem
    }

    private func makeBoundingBoxesMenu() -> NSMenu {
        let menu = NSMenu(title: "Bounding Boxes")
        menu.addItem(CallbackMenuItem(
            title: "Configure Bounding Boxes",
            actionHandler: onConfigureBoundingBoxes
        ))
        return menu
    }

    private func insertionIndex(in mainMenu: NSMenu) -> Int {
        guard let windowIndex = mainMenu.items.firstIndex(where: { $0.title == "Window" }) else {
            return mainMenu.numberOfItems
        }

        return windowIndex
    }
}
