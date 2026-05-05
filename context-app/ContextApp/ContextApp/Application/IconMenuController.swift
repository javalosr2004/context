import AppKit

final class IconMenuController {
    private let debugBboxController: DebugBboxController

    init(debugBboxController: DebugBboxController) {
        self.debugBboxController = debugBboxController
    }

    func makeMenu() -> NSMenu {
        IconContextMenu(onTestBbox: handleTestBbox).makeMenu()
    }

    func handleTestBbox() {
        debugBboxController.showReplacementBbox()
    }
}

