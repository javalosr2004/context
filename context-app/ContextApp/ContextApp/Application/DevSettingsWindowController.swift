import AppKit
import SwiftUI

@MainActor
final class DevSettingsWindowController {
    private let visualStore: GroundingEndpointStore
    private let webStore: WebGroundingEndpointStore
    private let tutorialStore: TutorialAPIEndpointStore
    private var window: NSWindow?

    init(
        visualStore: GroundingEndpointStore,
        webStore: WebGroundingEndpointStore,
        tutorialStore: TutorialAPIEndpointStore
    ) {
        self.visualStore = visualStore
        self.webStore = webStore
        self.tutorialStore = tutorialStore
    }

    func show() {
        if let window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let hosting = NSHostingController(rootView: DevSettingsView(
            visualStore: visualStore,
            webStore: webStore,
            tutorialStore: tutorialStore,
            onClose: { [weak self] in self?.close() }
        ))

        let window = NSWindow(contentViewController: hosting)
        window.title = "Developer Settings"
        window.styleMask = [.titled, .closable]
        window.isReleasedWhenClosed = false
        window.level = .floating
        window.center()
        self.window = window

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func close() {
        window?.close()
        window = nil
    }
}
