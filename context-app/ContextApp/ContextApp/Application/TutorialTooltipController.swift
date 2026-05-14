import AppKit
import SwiftUI

@MainActor
final class TutorialTooltipController {
    private let screenProvider: () -> NSScreen?
    private var panel: TutorialTooltipPanel?

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func show(beside rect: CGRect, message: String) {
        guard let screen = screenProvider(), !message.isEmpty else { return }
        hide()

        let size = CGSize(width: 280, height: 96)
        let frame = TutorialTooltipController.frame(
            for: size,
            anchor: rect,
            in: screen.frame
        )

        let newPanel = TutorialTooltipPanel(frame: frame)
        newPanel.hasShadow = true
        newPanel.contentView = NSHostingView(rootView: TutorialTooltipView(message: message))
        newPanel.orderFrontRegardless()
        panel = newPanel
    }

    func hide() {
        panel?.orderOut(nil)
        panel = nil
    }

    static func frame(for size: CGSize, anchor: CGRect, in screen: CGRect) -> CGRect {
        let gap: CGFloat = 12
        let margin: CGFloat = 12

        let rightX = anchor.maxX + gap
        let leftX = anchor.minX - gap - size.width
        let canFitRight = rightX + size.width <= screen.maxX - margin
        let canFitLeft = leftX >= screen.minX + margin

        let x: CGFloat
        let y: CGFloat
        if canFitRight {
            x = rightX
            y = clampY(anchor.midY - size.height / 2, size: size, screen: screen, margin: margin)
        } else if canFitLeft {
            x = leftX
            y = clampY(anchor.midY - size.height / 2, size: size, screen: screen, margin: margin)
        } else {
            x = clampX(anchor.midX - size.width / 2, size: size, screen: screen, margin: margin)
            let above = anchor.maxY + gap
            if above + size.height <= screen.maxY - margin {
                y = above
            } else {
                y = max(anchor.minY - gap - size.height, screen.minY + margin)
            }
        }
        return CGRect(x: x, y: y, width: size.width, height: size.height)
    }

    private static func clampY(_ value: CGFloat, size: CGSize, screen: CGRect, margin: CGFloat) -> CGFloat {
        min(max(value, screen.minY + margin), screen.maxY - size.height - margin)
    }

    private static func clampX(_ value: CGFloat, size: CGSize, screen: CGRect, margin: CGFloat) -> CGFloat {
        min(max(value, screen.minX + margin), screen.maxX - size.width - margin)
    }
}

final class TutorialTooltipPanel: NSPanel {
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
        ignoresMouseEvents = true
        isOpaque = false
        level = .screenSaver
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    override var canBecomeKey: Bool { false }
}

struct TutorialTooltipView: View {
    let message: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "hand.point.up.left.fill")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(.tint)
                .padding(.top, 1)

            Text(message)
                .font(.system(size: 12.5))
                .foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.25), radius: 16, y: 8)
    }
}
