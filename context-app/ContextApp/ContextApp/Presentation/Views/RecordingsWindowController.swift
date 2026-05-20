import AppKit
import SwiftUI

@MainActor
final class RecordingsWindowController {
    private var window: NSWindow?
    private let controller: RecordingController

    init(controller: RecordingController) {
        self.controller = controller
    }

    func show() {
        if let window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let host = NSHostingController(rootView: RecordingsRootView(controller: controller))
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
}

/// Root view that owns navigation between the list and the detail screen.
/// The detail model is created when an entry is opened and kept fresh from
/// the index so SSE-driven status updates land on the open detail view too.
struct RecordingsRootView: View {
    @ObservedObject var controller: RecordingController
    @State private var selectedId: String?

    var body: some View {
        Group {
            if let id = selectedId, let entry = controller.index.entry(id: id) {
                DetailScreen(controller: controller, entry: entry, onClose: { selectedId = nil })
            } else {
                RecordingsListView(
                    index: controller.index,
                    onOpen: { entry in selectedId = entry.id },
                    onStartRecording: { controller.toggleRecording() },
                    isRecording: controller.isRecording
                )
            }
        }
    }
}

private struct DetailScreen: View {
    @ObservedObject var controller: RecordingController
    let entry: LocalRecordingEntry
    let onClose: () -> Void
    @StateObject private var model: RecordingDetailModel

    init(controller: RecordingController, entry: LocalRecordingEntry, onClose: @escaping () -> Void) {
        self.controller = controller
        self.entry = entry
        self.onClose = onClose
        _model = StateObject(wrappedValue: RecordingDetailModel(entry: entry))
    }

    var body: some View {
        RecordingDetailView(model: model, onClose: onClose)
            .onChange(of: entry) { newEntry in
                model.update(entry: newEntry)
                if newEntry.lastStatus == "ready" {
                    model.reload()
                }
            }
    }
}
