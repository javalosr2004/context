import AppKit
import SwiftUI

/// Small floating chip shown while ScreenStabilityWatcher polls. Lets us see
/// live diff values so we can verify the screen actually settled before the
/// next backend event fires.
@MainActor
final class StabilityIndicatorController: ObservableObject {
    @Published private(set) var diff: Double?
    @Published private(set) var isVisible: Bool = false

    private let screenProvider: () -> NSScreen?
    private var panel: StabilityIndicatorPanel?

    var window: NSWindow? { panel }

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func show() {
        guard let screen = screenProvider() else { return }
        if panel == nil {
            let size = CGSize(width: 200, height: 36)
            let margin: CGFloat = 18
            let frame = CGRect(
                x: screen.frame.maxX - size.width - margin,
                y: screen.frame.maxY - size.height - margin - 56,
                width: size.width,
                height: size.height
            )
            let newPanel = StabilityIndicatorPanel(frame: frame)
            newPanel.hasShadow = true
            newPanel.contentView = NSHostingView(rootView: StabilityIndicatorView(controller: self))
            panel = newPanel
        }
        diff = nil
        isVisible = true
        panel?.orderFrontRegardless()
    }

    func update(diff: Double) {
        self.diff = diff
    }

    func hide() {
        isVisible = false
        panel?.orderOut(nil)
    }
}

final class StabilityIndicatorPanel: NSPanel {
    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        acceptsMouseMovedEvents = false
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        isOpaque = false
        level = .screenSaver
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        ignoresMouseEvents = true
    }

    override var canBecomeKey: Bool { false }
}

struct StabilityIndicatorView: View {
    @ObservedObject var controller: StabilityIndicatorController

    var body: some View {
        HStack(spacing: 10) {
            ProgressView()
                .scaleEffect(0.6)
                .frame(width: 16, height: 16)
            Text(label)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .foregroundStyle(.primary)
            Spacer()
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 1)
        )
    }

    private var label: String {
        guard let diff = controller.diff else {
            return "Settling…"
        }
        return String(format: "Settling… diff %.4f", diff)
    }
}
