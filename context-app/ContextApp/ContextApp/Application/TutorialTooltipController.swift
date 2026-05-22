import AppKit
import SwiftUI

@MainActor
final class TutorialTooltipController {
    private let screenProvider: () -> NSScreen?
    private let onNextProvider: () -> (() -> Void)?
    private var panel: TutorialTooltipPanel?

    /// The interactive panel currently on screen, or nil if hidden. Exposed
    /// so the focus-mask click classifier can treat clicks on the tooltip
    /// (e.g. on its Next button) as ignored rather than outside-cutout.
    var interactiveWindow: NSWindow? { panel }

    init(
        screenProvider: @escaping () -> NSScreen?,
        onNextProvider: @escaping () -> (() -> Void)? = { nil }
    ) {
        self.screenProvider = screenProvider
        self.onNextProvider = onNextProvider
    }

    func show(beside rect: CGRect, message: String) {
        guard let screen = screenProvider(), !message.isEmpty else { return }
        hide()

        let onNext = onNextProvider()
        let size = CGSize(width: 280, height: onNext == nil ? 96 : 132)
        let frame = TutorialTooltipController.frame(
            for: size,
            anchor: rect,
            in: screen.frame
        )

        let newPanel = TutorialTooltipPanel(frame: frame, allowsMouseEvents: onNext != nil)
        newPanel.hasShadow = true
        newPanel.contentView = NSHostingView(
            rootView: TutorialTooltipView(message: message, onNext: onNext)
        )
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
    init(frame: NSRect, allowsMouseEvents: Bool = false) {
        super.init(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        acceptsMouseMovedEvents = false
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        // When the tooltip carries a Next button it must accept clicks;
        // otherwise it stays click-through so the user can interact with
        // the underlying app freely.
        ignoresMouseEvents = !allowsMouseEvents
        isOpaque = false
        level = .screenSaver
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    override var canBecomeKey: Bool { false }
}

struct TutorialTooltipView: View {
    let message: String
    let onNext: (() -> Void)?

    init(message: String, onNext: (() -> Void)? = nil) {
        self.message = message
        self.onNext = onNext
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
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

            if let onNext {
                HStack {
                    Spacer()
                    Button(action: onNext) {
                        Text("Next")
                            .font(.system(size: 12.5, weight: .semibold))
                            .foregroundStyle(Color.white)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 6)
                            .background(Color.accentColor)
                            .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
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
