import AppKit
import SwiftUI

@MainActor
final class PopupController {
    private let boundsKeeper: ScreenBoundsKeeper
    private let minimumVisible: CGFloat
    private let popupPanel: PopupPanel
    private(set) var state: PopupState

    init(
        popupPanel: PopupPanel,
        initialFrame: CGRect,
        boundsKeeper: ScreenBoundsKeeper = ScreenBoundsKeeper(),
        minimumVisible: CGFloat = 80
    ) {
        self.popupPanel = popupPanel
        self.boundsKeeper = boundsKeeper
        self.minimumVisible = minimumVisible
        self.state = .expanded(frame: initialFrame)
        popupPanel.popupDelegate = self
    }

    func showPopup() {
        popupPanel.orderFrontRegardless()
        state = .expanded(frame: popupPanel.frame)
    }

    func toggle() {
        switch state {
        case .expanded:
            collapse()
        case .collapsed:
            restore()
        }
    }

    func collapse() {
        let frame = popupPanel.frame
        popupPanel.orderOut(nil)
        state = .collapsed(lastFrame: frame)
    }

    func restore() {
        let frame = state.lastExpandedFrame
        popupPanel.setFrame(frame, display: true)
        popupPanel.orderFrontRegardless()
        state = .expanded(frame: frame)
    }

    func fitPopupHeight(to screenFrame: CGRect, minimumHeight: CGFloat = PopupState.minimumSize.height, verticalMargin: CGFloat = 64) {
        guard popupPanel.isVisible else { return }
        guard let contentView = popupPanel.contentView else { return }

        contentView.layoutSubtreeIfNeeded()
        let fittingHeight = ceil(contentView.fittingSize.height)
        let maximumHeight = max(minimumHeight, screenFrame.height - verticalMargin)
        let nextHeight = min(max(fittingHeight, minimumHeight), maximumHeight)
        guard abs(nextHeight - popupPanel.frame.height) > 1 else { return }

        var nextFrame = popupPanel.frame
        nextFrame.origin.y += nextFrame.height - nextHeight
        nextFrame.size.height = nextHeight
        nextFrame = boundsKeeper.clamp(frame: nextFrame, into: screenFrame, minimumVisible: minimumVisible)
        popupPanel.setFrame(nextFrame, display: true)
        state = .expanded(frame: nextFrame)
    }

    func reclamp(to screenFrame: CGRect) {
        let clamp: (CGRect) -> CGRect = { [boundsKeeper, minimumVisible] frame in
            boundsKeeper.clamp(frame: frame, into: screenFrame, minimumVisible: minimumVisible)
        }
        switch state {
        case .expanded:
            let frame = clamp(popupPanel.frame)
            popupPanel.setFrame(frame, display: true)
            state = .expanded(frame: frame)
        case .collapsed(let lastFrame):
            state = .collapsed(lastFrame: clamp(lastFrame))
        }
    }
}

extension PopupController: PopupPanelDelegate {
    func popupPanelDidRequestCollapse() {
        collapse()
    }
}
