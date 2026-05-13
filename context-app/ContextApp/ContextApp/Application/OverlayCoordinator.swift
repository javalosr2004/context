import AppKit
import SwiftUI

@MainActor
final class OverlayCoordinator {
    private let endpointStore = GroundingEndpointStore()
    private let messageStore = ChatMessageStore()
    private let screenProvider: () -> NSScreen?
    private let tutorialEndpointStore = TutorialAPIEndpointStore()

    private var debugBboxController: DebugBboxController?
    private var focusMaskController: FocusMaskController?
    private var iconMenuController: IconMenuController?
    private var popupController: PopupController?
    private var screenGroundingController: ScreenGroundingController?
    private var screenObserver: NSObjectProtocol?
    private var statusBarController: StatusBarController?
    private var tutorialActionConsumer: TutorialActionConsumer?
    private var tutorialPlanController: TutorialPlanController?

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func start() {
        guard let screen = screenProvider() else { return }

        let popupPanel = PopupPanel(frame: initialPopupFrame(on: screen.frame))
        let iconPanel = IconPanel(frame: initialIconFrame(on: screen.frame))
        let bboxPanel = DebugBboxPanel(frame: CGRect(origin: .zero, size: DebugBoundingBox.size))

        let focusMaskController = FocusMaskController(
            screenProvider: screenProvider,
            onExit: { [weak bboxPanel] in
                bboxPanel?.orderOut(nil)
            }
        )
        let debugController = DebugBboxController(
            panel: bboxPanel,
            focusMaskController: focusMaskController,
            screenProvider: screenProvider
        )
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
        let tutorialPlanController = TutorialPlanController(
            endpointStore: tutorialEndpointStore,
            ignoredWindowProvider: {
                [popupPanel, iconPanel, bboxPanel]
            },
            screenProvider: screenProvider
        )
        let tutorialActionConsumer = TutorialActionConsumer { instruction in
            await screenGroundingController.submit(instruction)
        }

        popupPanel.contentView = NSHostingView(rootView: ChatPopupView(
            messageStore: messageStore,
            onCreateTutorialPlan: { text in
                try await tutorialPlanController.submit(text)
            },
            onTutorialStepSelected: { step in
                await tutorialActionConsumer.consume(step: step)
            },
            onInputInstruction: { input in
                await screenGroundingController.submit(GroundingInstruction(
                    text: input.text,
                    referenceImageData: input.referenceImageData,
                    imageEncodingConfig: input.imageEncodingConfig,
                    submittedAtUptimeNanoseconds: input.submittedAtUptimeNanoseconds
                ))
            },
            onMinify: {
                popupController.minify()
            }
        ))
        iconPanel.contentView = NSHostingView(rootView: IconView(
            onRestore: { popupController.restore() },
            onContextMenu: { menuController.handleTestBbox() },
            onDrag: { delta in popupController.moveIcon(by: delta) }
        ))

        self.debugBboxController = debugController
        self.focusMaskController = focusMaskController
        self.iconMenuController = menuController
        self.popupController = popupController
        self.screenGroundingController = screenGroundingController
        self.statusBarController = StatusBarController(
            endpointStore: endpointStore,
            tutorialEndpointStore: tutorialEndpointStore,
            onTestBbox: { debugController.showReplacementBbox() }
        )
        self.tutorialActionConsumer = tutorialActionConsumer
        self.tutorialPlanController = tutorialPlanController

        popupController.showPopup()
        observeScreenChanges()
    }

    func stop() {
        screenObserver.map(NotificationCenter.default.removeObserver)
        screenObserver = nil
        statusBarController?.stop()
        debugBboxController?.hide()
        focusMaskController?.hide()
        popupController = nil
        iconMenuController = nil
        debugBboxController = nil
        focusMaskController = nil
        screenGroundingController = nil
        statusBarController = nil
        tutorialActionConsumer = nil
        tutorialPlanController = nil
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
