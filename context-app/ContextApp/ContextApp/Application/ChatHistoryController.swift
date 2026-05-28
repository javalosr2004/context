import AppKit
import SwiftUI

@MainActor
final class ChatHistoryController {
    let panel: ChatHistoryPanel
    private let screenProvider: () -> NSScreen?

    init(
        sessionController: TutorialSessionController,
        screenProvider: @escaping () -> NSScreen?,
        anchorFrame: CGRect
    ) {
        self.screenProvider = screenProvider
        let frame = ChatHistoryController.initialFrame(anchoredTo: anchorFrame, screen: screenProvider()?.frame)
        let panel = ChatHistoryPanel(frame: frame)
        self.panel = panel

        let hosting = NSHostingView(rootView: ChatHistoryView(
            sessionController: sessionController,
            onClose: { [weak panel] in panel?.orderOut(nil) }
        ))
        panel.contentView = hosting
    }

    func show() {
        panel.orderFrontRegardless()
    }

    func hide() {
        panel.orderOut(nil)
    }

    func toggle() {
        if panel.isVisible {
            hide()
        } else {
            show()
        }
    }

    private static func initialFrame(anchoredTo anchor: CGRect, screen: CGRect?) -> CGRect {
        let width: CGFloat = 380
        let height: CGFloat = 520
        let gap: CGFloat = 12

        guard let screen else {
            return CGRect(x: anchor.maxX + gap, y: anchor.minY, width: width, height: height)
        }

        var originX = anchor.maxX + gap
        if originX + width > screen.maxX - 8 {
            originX = max(screen.minX + 8, anchor.minX - gap - width)
        }
        let originY = min(max(screen.minY + 8, anchor.minY), screen.maxY - height - 8)
        return CGRect(x: originX, y: originY, width: width, height: height)
    }
}
