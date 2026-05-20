import AppKit
import SwiftUI

@MainActor
final class RecordingsWindowController {
    private var window: NSWindow?
    private let model: RecordingsListModel

    init(index: RecordingsIndex) {
        self.model = RecordingsListModel(index: index)
    }

    func show() {
        if let window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            model.reload()
            return
        }
        let host = NSHostingController(rootView: RecordingsListView(model: model))
        let w = NSWindow(contentViewController: host)
        w.setContentSize(NSSize(width: 520, height: 420))
        w.title = "Recordings"
        w.styleMask = [.titled, .closable, .resizable, .miniaturizable]
        w.isReleasedWhenClosed = false
        w.center()
        self.window = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func refresh() { model.reload() }
}
