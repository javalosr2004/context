import AppKit
import SwiftUI

@MainActor
final class FocusMaskController {
    private let layout: FocusMaskLayout
    private let onExit: () -> Void
    private let screenProvider: () -> NSScreen?

    private var dimPanels: [FocusMaskPanel] = []
    private var exitPanel: FocusMaskPanel?

    init(
        layout: FocusMaskLayout = FocusMaskLayout(),
        screenProvider: @escaping () -> NSScreen?,
        onExit: @escaping () -> Void
    ) {
        self.layout = layout
        self.screenProvider = screenProvider
        self.onExit = onExit
    }

    func show(cutoutFrame: CGRect) {
        guard let screen = screenProvider() else { return }

        hide()
        dimPanels = layout
            .dimmingRects(screenFrame: screen.frame, targetFrame: cutoutFrame)
            .map(makeDimPanel)

        showExitPanel(on: screen.frame)
    }

    func hide() {
        dimPanels.forEach { $0.orderOut(nil) }
        dimPanels = []
        exitPanel?.orderOut(nil)
        exitPanel = nil
    }

    private func makeDimPanel(frame: CGRect) -> FocusMaskPanel {
        let panel = FocusMaskPanel(frame: frame, ignoresMouseEvents: false, canBecomeKey: true)
        panel.contentView = NSHostingView(rootView: FocusMaskView())
        panel.orderFrontRegardless()
        return panel
    }

    private func showExitPanel(on screenFrame: CGRect) {
        let frame = exitFrame(on: screenFrame)
        let panel = FocusMaskPanel(frame: frame, ignoresMouseEvents: false)
        panel.hasShadow = true
        panel.contentView = NSHostingView(rootView: FocusExitView { [weak self] in
            self?.hide()
            self?.onExit()
        })
        panel.orderFrontRegardless()
        exitPanel = panel
    }

    private func exitFrame(on screenFrame: CGRect) -> CGRect {
        let size = CGSize(width: 104, height: 36)
        let margin: CGFloat = 18
        return CGRect(
            x: screenFrame.maxX - size.width - margin,
            y: screenFrame.maxY - size.height - margin,
            width: size.width,
            height: size.height
        )
    }
}
