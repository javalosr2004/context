import AppKit
import SwiftUI

@MainActor
final class OverlayCoordinator {
    private let endpointStore = GroundingEndpointStore()
    private let messageStore = ChatMessageStore()
    private let screenProvider: () -> NSScreen?

    private var debugBboxController: DebugBboxController?
    private var iconMenuController: IconMenuController?
    private var popupController: PopupController?
    private var screenGroundingController: ScreenGroundingController?
    private var screenObserver: NSObjectProtocol?
    private var statusBarController: StatusBarController?

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func start() {
        guard let screen = screenProvider() else { return }

        let popupPanel = PopupPanel(frame: initialPopupFrame(on: screen.frame))
        let iconPanel = IconPanel(frame: initialIconFrame(on: screen.frame))
        let bboxPanel = DebugBboxPanel(frame: CGRect(origin: .zero, size: DebugBoundingBox.size))

        let debugController = DebugBboxController(panel: bboxPanel, screenProvider: screenProvider)
        let screenGroundingController = ScreenGroundingController(
            bboxController: debugController,
            endpointStore: endpointStore,
            ignoredWindowProvider: {
                [popupPanel, iconPanel, bboxPanel]
            },
            screenProvider: screenProvider
        )
        let menuController = IconMenuController(debugBboxController: debugController)
        let popupController = PopupController(
            popupPanel: popupPanel,
            iconPanel: iconPanel,
            initialFrame: popupPanel.frame
        )

        popupPanel.contentView = NSHostingView(rootView: ChatPopupView(messageStore: messageStore) {
            input in
            await screenGroundingController.submit(GroundingInstruction(
                text: input.text,
                referenceImageData: input.referenceImageData,
                submittedAtUptimeNanoseconds: input.submittedAtUptimeNanoseconds
            ))
        } onMinify: {
            popupController.minify()
        })
        iconPanel.contentView = NSHostingView(rootView: IconView(
            onRestore: { popupController.restore() },
            onContextMenu: { menuController.handleTestBbox() }
        ))

        self.debugBboxController = debugController
        self.iconMenuController = menuController
        self.popupController = popupController
        self.screenGroundingController = screenGroundingController
        self.statusBarController = StatusBarController(
            endpointStore: endpointStore,
            onTestBbox: { debugController.showReplacementBbox() }
        )

        popupController.showPopup()
        observeScreenChanges()
    }

    func stop() {
        screenObserver.map(NotificationCenter.default.removeObserver)
        screenObserver = nil
        statusBarController?.stop()
        debugBboxController?.hide()
        popupController = nil
        iconMenuController = nil
        debugBboxController = nil
        screenGroundingController = nil
        statusBarController = nil
    }

    private func initialPopupFrame(on screen: CGRect) -> CGRect {
        CGRect(x: screen.midX - 180, y: screen.midY - 220, width: 360, height: 440)
    }

    private func initialIconFrame(on screen: CGRect) -> CGRect {
        CGRect(x: screen.midX - 28, y: screen.midY - 28, width: 56, height: 56)
    }

    private func observeScreenChanges() {
        screenObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.reclampPanels()
            }
        }
    }

    private func reclampPanels() {
        guard let screen = screenProvider() else { return }
        popupController?.reclamp(to: screen.frame)
    }
}
