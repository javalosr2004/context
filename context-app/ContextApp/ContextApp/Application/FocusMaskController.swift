import AppKit
import SwiftUI

@MainActor
final class FocusMaskController {
    private let layout: FocusMaskLayout
    private let onExit: () -> Void
    private let onInsideClick: () -> Void
    private let onOutsideClick: () -> Void
    private let screenProvider: () -> NSScreen?

    private var dimPanels: [FocusMaskPanel] = []
    private var exitPanel: ExitChipPanel?
    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var paddedCutout: CGRect = CGRect.null

    init(
        layout: FocusMaskLayout = FocusMaskLayout(),
        screenProvider: @escaping () -> NSScreen?,
        onExit: @escaping () -> Void,
        onInsideClick: @escaping () -> Void = {},
        onOutsideClick: @escaping () -> Void = {}
    ) {
        self.layout = layout
        self.screenProvider = screenProvider
        self.onExit = onExit
        self.onInsideClick = onInsideClick
        self.onOutsideClick = onOutsideClick
    }

    func show(cutoutFrame: CGRect) {
        guard let screen = screenProvider() else { return }

        hide()
        paddedCutout = layout.paddedCutout(screenFrame: screen.frame, targetFrame: cutoutFrame)
        dimPanels = layout
            .dimmingRects(screenFrame: screen.frame, targetFrame: cutoutFrame)
            .map(makeDimPanel)

        showExitPanel(on: screen.frame)
        installClickMonitors()
    }

    func hide() {
        removeClickMonitors()
        dimPanels.forEach { $0.orderOut(nil) }
        dimPanels = []
        exitPanel?.orderOut(nil)
        exitPanel = nil
        paddedCutout = CGRect.null
    }

    private func makeDimPanel(frame: CGRect) -> FocusMaskPanel {
        let panel = FocusMaskPanel(frame: frame)
        panel.contentView = NSHostingView(rootView: FocusMaskView())
        panel.orderFrontRegardless()
        return panel
    }

    private func showExitPanel(on screenFrame: CGRect) {
        let frame = exitFrame(on: screenFrame)
        let panel = ExitChipPanel(frame: frame)
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

    private func installClickMonitors() {
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] event in
            Task { @MainActor [weak self] in
                self?.handleClick(at: NSEvent.mouseLocation)
            }
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] event in
            guard let self else { return event }
            if self.isOwnInteractiveWindow(event.window) {
                return event
            }
            self.handleClick(at: NSEvent.mouseLocation)
            return event
        }
    }

    private func removeClickMonitors() {
        if let globalMonitor {
            NSEvent.removeMonitor(globalMonitor)
        }
        globalMonitor = nil
        if let localMonitor {
            NSEvent.removeMonitor(localMonitor)
        }
        localMonitor = nil
    }

    private func isOwnInteractiveWindow(_ window: NSWindow?) -> Bool {
        guard let window else { return false }
        return window === exitPanel
    }

    private func handleClick(at screenPoint: CGPoint) {
        guard !paddedCutout.isNull, !paddedCutout.isEmpty else { return }
        let inside = paddedCutout.contains(screenPoint)
        hide()
        if inside {
            onInsideClick()
        } else {
            onOutsideClick()
        }
    }
}

@MainActor
final class InstructionCardController {
    private let screenProvider: () -> NSScreen?
    private let onDone: (String) -> Void
    private let onCopy: (String) -> Void

    private var panel: InstructionCardPanel?

    init(
        screenProvider: @escaping () -> NSScreen?,
        onDone: @escaping (String) -> Void,
        onCopy: @escaping (String) -> Void = { _ in }
    ) {
        self.screenProvider = screenProvider
        self.onDone = onDone
        self.onCopy = onCopy
    }

    func show(stepID: String, title: String, message: String, copyableText: String? = nil) {
        guard let screen = screenProvider() else { return }
        hide()

        let size = CGSize(width: 360, height: copyableText == nil ? 132 : 188)
        let frame = CGRect(
            x: screen.frame.midX - size.width / 2,
            y: screen.frame.midY - size.height / 2,
            width: size.width,
            height: size.height
        )
        let view = InstructionCardView(
            title: title,
            message: message,
            copyableText: copyableText,
            onDone: { [weak self] in
                self?.hide()
                self?.onDone(stepID)
            },
            onCopy: { [weak self] text in
                self?.onCopy(text)
            },
            onClose: { [weak self] in
                self?.hide()
            }
        )
        let newPanel = InstructionCardPanel(frame: frame)
        newPanel.hasShadow = true
        newPanel.contentView = NSHostingView(rootView: view)
        newPanel.orderFrontRegardless()
        panel = newPanel
    }

    func hide() {
        panel?.orderOut(nil)
        panel = nil
    }
}

final class InstructionCardPanel: NSPanel {
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

struct InstructionCardView: View {
    let title: String
    let message: String
    let copyableText: String?
    let onDone: () -> Void
    let onCopy: (String) -> Void
    let onClose: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                Button(action: onClose) {
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .semibold))
                        .frame(width: 22, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }

            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if let copyableText, !copyableText.isEmpty {
                HStack(spacing: 8) {
                    Text(copyableText)
                        .font(.system(size: 12, design: .monospaced))
                        .lineLimit(2)
                        .truncationMode(.tail)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(OverlayTheme.strongerFill)
                        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))

                    Button {
                        onCopy(copyableText)
                    } label: {
                        Image(systemName: "doc.on.clipboard")
                            .font(.system(size: 12, weight: .medium))
                            .frame(width: 30, height: 30)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .help("Copy to clipboard")
                }
            }

            HStack {
                Spacer()
                Button(action: onDone) {
                    Label("Done", systemImage: "checkmark")
                        .font(.caption.weight(.medium))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.25), radius: 20, y: 10)
    }
}

final class ExitChipPanel: NSPanel {
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
