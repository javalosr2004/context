import AppKit
import SwiftUI

final class DebugBboxController {
    private let panel: DebugBboxPanel
    private let positionGenerator: BboxPositionGenerator
    private let screenProvider: () -> NSScreen?
    private let state: DebugBboxState

    init(
        panel: DebugBboxPanel,
        state: DebugBboxState = DebugBboxState(),
        positionGenerator: BboxPositionGenerator = BboxPositionGenerator(),
        screenProvider: @escaping () -> NSScreen?
    ) {
        self.panel = panel
        self.state = state
        self.positionGenerator = positionGenerator
        self.screenProvider = screenProvider
    }

    func showReplacementBbox() {
        guard let screen = screenProvider() else { return }
        guard screen.frame.width >= DebugBoundingBox.size.width,
              screen.frame.height >= DebugBoundingBox.size.height else { return }

        var rng = SystemRandomNumberGenerator()
        let localOrigin = positionGenerator.position(
            screen: screen.frame.size,
            bbox: DebugBoundingBox.size,
            rng: &rng
        )
        let bbox = DebugBoundingBox(origin: CGPoint(
            x: screen.frame.minX + localOrigin.x,
            y: screen.frame.minY + localOrigin.y
        ))

        state.replace(with: bbox)
        render(bbox)
    }

    func hide() {
        state.replace(with: nil)
        panel.orderOut(nil)
    }

    func show(rect: CGRect) {
        state.replace(with: DebugBoundingBox(origin: rect.origin))
        render(rect)
    }

    private func render(_ bbox: DebugBoundingBox) {
        render(CGRect(origin: bbox.origin, size: DebugBoundingBox.size))
    }

    private func render(_ rect: CGRect) {
        panel.contentView = NSHostingView(rootView: DebugBboxView(size: rect.size))
        panel.setFrame(
            rect,
            display: true
        )
        panel.orderFrontRegardless()
    }
}
