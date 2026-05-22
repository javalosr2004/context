import AppKit
import SwiftUI
import os

@MainActor
final class FocusMaskController {
    private static let log = Logger(subsystem: "ContextApp", category: "FocusMask")

    private let clickClassifier: FocusMaskClickClassifier
    private let interactiveWindowsProvider: () -> [NSWindow]
    private let layout: FocusMaskLayout
    private let onExit: () -> Void
    private let onInsideClick: () -> Bool
    private let onOutsideClick: () -> Void
    private let screenProvider: () -> NSScreen?

    private var dimPanels: [FocusMaskPanel] = []
    private var exitPanel: ExitChipPanel?
    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var paddedCutout: CGRect = CGRect.null

    init(
        layout: FocusMaskLayout = FocusMaskLayout(),
        clickClassifier: FocusMaskClickClassifier = FocusMaskClickClassifier(),
        screenProvider: @escaping () -> NSScreen?,
        interactiveWindowsProvider: @escaping () -> [NSWindow] = { [] },
        onExit: @escaping () -> Void,
        onInsideClick: @escaping () -> Bool = { true },
        onOutsideClick: @escaping () -> Void = {}
    ) {
        self.clickClassifier = clickClassifier
        self.interactiveWindowsProvider = interactiveWindowsProvider
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
        Self.log.info("show cutout=\(self.rectString(self.paddedCutout), privacy: .public) appActive=\(NSApp.isActive, privacy: .public) frontmost=\(self.frontmostBundleID(), privacy: .public)")
    }

    func hide() {
        let wasActive = !dimPanels.isEmpty
        removeClickMonitors()
        dimPanels.forEach { $0.orderOut(nil) }
        dimPanels = []
        exitPanel?.orderOut(nil)
        exitPanel = nil
        paddedCutout = CGRect.null
        if wasActive {
            Self.log.info("hide")
        }
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
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] _ in
            let location = NSEvent.mouseLocation
            Task { @MainActor [weak self] in
                guard let self else { return }
                Self.log.info("click source=global at=\(self.pointString(location), privacy: .public) appActive=\(NSApp.isActive, privacy: .public) frontmost=\(self.frontmostBundleID(), privacy: .public)")
                self.handleClick(at: location, eventWindow: nil)
            }
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] event in
            guard let self else { return event }
            let location = NSEvent.mouseLocation
            Self.log.info("click source=local at=\(self.pointString(location), privacy: .public) window=\(String(describing: event.window), privacy: .public) appActive=\(NSApp.isActive, privacy: .public) frontmost=\(self.frontmostBundleID(), privacy: .public)")
            self.handleClick(at: location, eventWindow: event.window)
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

    private func isIgnoredInteractiveWindow(_ window: NSWindow?) -> Bool {
        guard let window else { return false }
        if window === exitPanel {
            return true
        }

        return interactiveWindowsProvider().contains { $0 === window }
    }

    private func handleClick(at screenPoint: CGPoint, eventWindow: NSWindow?) {
        let target = clickClassifier.target(
            for: screenPoint,
            cutout: paddedCutout,
            isIgnoredControl: isIgnoredInteractiveWindow(eventWindow)
        )
        Self.log.info("classify result=\(String(describing: target), privacy: .public) cutout=\(self.rectString(self.paddedCutout), privacy: .public)")

        switch target {
        case .ignoredControl, nil:
            return
        case .insideCutout:
            let shouldDismiss = onInsideClick()
            Self.log.info("inside-click shouldDismiss=\(shouldDismiss, privacy: .public)")
            if shouldDismiss { hide() }
        case .outsideCutout:
            Self.log.info("outside-click")
            hide()
            onOutsideClick()
        }
    }

    private func pointString(_ p: CGPoint) -> String {
        String(format: "(%.0f,%.0f)", p.x, p.y)
    }

    private func rectString(_ r: CGRect) -> String {
        if r.isNull { return "null" }
        return String(format: "(%.0f,%.0f %.0fx%.0f)", r.minX, r.minY, r.width, r.height)
    }

    private func frontmostBundleID() -> String {
        NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "?"
    }
}

@MainActor
final class InstructionCardController {
    private let screenProvider: () -> NSScreen?
    private let onDone: (String) -> Void
    private let onCopy: (String) -> Void

    private var panel: InstructionCardPanel?

    var interactiveWindow: NSWindow? {
        panel
    }

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

        let width: CGFloat = 360
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
        let hostingView = NSHostingView(rootView: view)
        hostingView.frame = CGRect(x: 0, y: 0, width: width, height: 0)
        let fittedHeight = max(hostingView.fittingSize.height, 1)
        let size = CGSize(width: width, height: fittedHeight)
        let frame = CGRect(
            x: screen.frame.midX - size.width / 2,
            y: screen.frame.midY - size.height / 2,
            width: size.width,
            height: size.height
        )
        let newPanel = InstructionCardPanel(frame: frame)
        newPanel.hasShadow = true
        newPanel.contentView = hostingView
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
        .frame(maxWidth: .infinity, alignment: .topLeading)
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
