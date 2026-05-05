import AppKit
import SwiftUI

final class PopupController {
    private let boundsKeeper: ScreenBoundsKeeper
    private let iconPanel: IconPanel
    private let minimumVisible: CGFloat
    private let popupPanel: PopupPanel
    private(set) var state: PopupState

    init(
        popupPanel: PopupPanel,
        iconPanel: IconPanel,
        initialFrame: CGRect,
        boundsKeeper: ScreenBoundsKeeper = ScreenBoundsKeeper(),
        minimumVisible: CGFloat = 80
    ) {
        self.popupPanel = popupPanel
        self.iconPanel = iconPanel
        self.boundsKeeper = boundsKeeper
        self.minimumVisible = minimumVisible
        self.state = .expanded(frame: initialFrame)
    }

    func showPopup() {
        popupPanel.orderFrontRegardless()
        iconPanel.orderOut(nil)
        state = .expanded(frame: popupPanel.frame)
    }

    func minify() {
        let iconFrame = iconFrameBesidePopup()
        iconPanel.setFrame(iconFrame, display: true)
        popupPanel.orderOut(nil)
        iconPanel.orderFrontRegardless()
        state = state.minified(at: iconFrame.origin)
    }

    func restore() {
        let popupFrame = restoredPopupFrame()
        popupPanel.setFrame(popupFrame, display: true)
        iconPanel.orderOut(nil)
        popupPanel.orderFrontRegardless()
        state = state.expanded(at: popupFrame)
    }

    func reclamp(to screenFrame: CGRect) {
        if popupPanel.isVisible {
            let frame = boundsKeeper.clamp(frame: popupPanel.frame, into: screenFrame, minimumVisible: minimumVisible)
            popupPanel.setFrame(frame, display: true)
            state = state.expanded(at: frame)
        }

        if iconPanel.isVisible {
            let frame = boundsKeeper.clamp(frame: iconPanel.frame, into: screenFrame, minimumVisible: minimumVisible / 2)
            iconPanel.setFrame(frame, display: true)
            state = state.minified(at: frame.origin)
        }
    }

    private func iconFrameBesidePopup() -> CGRect {
        CGRect(x: popupPanel.frame.minX, y: popupPanel.frame.minY, width: 56, height: 56)
    }

    private func restoredPopupFrame() -> CGRect {
        switch state {
        case .expanded(let frame):
            return frame
        case .minified:
            return popupPanel.frame
        }
    }
}

