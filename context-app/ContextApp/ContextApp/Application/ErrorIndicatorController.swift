import AppKit
import SwiftUI

/// Small floating chip rendered in the top-left of the active screen to surface
/// tutorial errors without polluting the chat transcript. Driven by
/// `TutorialSessionController.status == .failed`.
@MainActor
final class ErrorIndicatorController: ObservableObject {
    @Published private(set) var message: String = ""
    @Published private(set) var isVisible: Bool = false

    private let screenProvider: () -> NSScreen?
    private var panel: ErrorIndicatorPanel?

    var window: NSWindow? { panel }

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func show(message: String) {
        guard let screen = screenProvider() else { return }
        self.message = message
        if panel == nil {
            let size = CGSize(width: 260, height: 32)
            let margin: CGFloat = 18
            let frame = CGRect(
                x: screen.frame.minX + margin,
                y: screen.frame.maxY - size.height - margin,
                width: size.width,
                height: size.height
            )
            let newPanel = ErrorIndicatorPanel(frame: frame)
            newPanel.hasShadow = true
            newPanel.contentView = NSHostingView(rootView: ErrorIndicatorView(
                controller: self,
                onDismiss: { [weak self] in self?.hide() }
            ))
            panel = newPanel
        }
        isVisible = true
        panel?.orderFrontRegardless()
    }

    func hide() {
        isVisible = false
        panel?.orderOut(nil)
    }
}

final class ErrorIndicatorPanel: NSPanel {
    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        backgroundColor = .clear
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        isOpaque = false
        level = .screenSaver
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
    }

    override var canBecomeKey: Bool { false }
}

struct ErrorIndicatorView: View {
    @ObservedObject var controller: ErrorIndicatorController
    let onDismiss: () -> Void

    var body: some View {
        Button(action: onDismiss) {
            HStack(spacing: 8) {
                Circle()
                    .fill(Color(red: 0.92, green: 0.34, blue: 0.34))
                    .frame(width: 8, height: 8)
                Text("Error")
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(OverlayTheme.primaryText)
                Text(controller.message)
                    .font(.system(size: 12, weight: .regular))
                    .foregroundStyle(OverlayTheme.secondaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .buttonStyle(.plain)
        .help(controller.message.isEmpty ? "Dismiss" : "\(controller.message)\n\nClick to dismiss")
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color(red: 0.92, green: 0.34, blue: 0.34).opacity(0.55), lineWidth: 1)
        )
    }
}
