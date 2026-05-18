import AppKit
import SwiftUI

@MainActor
final class EdgeTabController {
    private let panel: EdgeTabPanel
    private let screenProvider: () -> NSScreen?
    private let onToggle: () -> Void

    init(screenProvider: @escaping () -> NSScreen?, onToggle: @escaping () -> Void) {
        self.screenProvider = screenProvider
        self.onToggle = onToggle
        self.panel = EdgeTabPanel(frame: .zero)
    }

    func start() {
        installContent()
        reanchor()
        panel.orderFrontRegardless()
    }

    func stop() {
        panel.orderOut(nil)
    }

    func reanchor() {
        guard let screen = screenProvider() else { return }
        let frame = EdgeTabAnchor.frame(
            in: screen.visibleFrame,
            size: EdgeTabMetrics.size,
            inset: EdgeTabMetrics.inset
        )
        panel.setFrame(frame, display: true)
    }

    var window: NSWindow { panel }

    private func installContent() {
        panel.contentView = NSHostingView(rootView: EdgeTabView(
            onClick: { [weak self] in self?.onToggle() },
            onContextMenu: { [weak self] in self?.onToggle() }
        ))
    }
}
