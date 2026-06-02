import AppKit
import SwiftUI

@MainActor
final class ClipboardPopoverController {
    private let screenProvider: () -> NSScreen?
    private let onCopy: (String) -> Void
    private var panel: ClipboardPopoverPanel?

    var interactiveWindow: NSWindow? { panel }

    init(
        screenProvider: @escaping () -> NSScreen?,
        onCopy: @escaping (String) -> Void = { text in
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            pasteboard.setString(text, forType: .string)
        }
    ) {
        self.screenProvider = screenProvider
        self.onCopy = onCopy
    }

    func show(beside rect: CGRect, text: String) {
        guard let screen = screenProvider(), !text.isEmpty else { return }
        hide()

        let size = CGSize(width: 280, height: 88)
        let frame = TutorialTooltipController.frame(
            for: size,
            anchor: rect,
            in: screen.frame
        )

        let onCopy = self.onCopy
        let newPanel = ClipboardPopoverPanel(frame: frame)
        newPanel.hasShadow = true
        newPanel.contentView = NSHostingView(rootView: ClipboardPopoverView(
            text: text,
            onCopy: { onCopy($0) }
        ))
        newPanel.orderFrontRegardless()
        panel = newPanel
    }

    func hide() {
        panel?.orderOut(nil)
        panel = nil
    }
}

final class ClipboardPopoverPanel: NSPanel {
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
    }

    override var canBecomeKey: Bool { false }
}

struct ClipboardPopoverView: View {
    let text: String
    let onCopy: (String) -> Void
    @State private var copied = false

    var body: some View {
        HStack(spacing: 8) {
            Text(text)
                .font(.system(size: 12, design: .monospaced))
                .lineLimit(2)
                .truncationMode(.tail)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(OverlayTheme.strongerFill)
                .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))

            Button {
                onCopy(text)
                copied = true
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 1_200_000_000)
                    copied = false
                }
            } label: {
                Image(systemName: copied ? "checkmark" : "doc.on.clipboard")
                    .font(.system(size: 12, weight: .medium))
                    .frame(width: 30, height: 30)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help(copied ? "Copied" : "Copy to clipboard")
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.25), radius: 16, y: 8)
    }
}
