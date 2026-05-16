import AppKit
import SwiftUI

@MainActor
final class OverlayCoordinator {
    private let endpointStore = GroundingEndpointStore()
    private let messageStore = ChatMessageStore()
    private let screenProvider: () -> NSScreen?
    private let tutorialEndpointStore = TutorialAPIEndpointStore()

    private var applicationMenuController: ApplicationMenuController?
    private var debugBboxController: DebugBboxController?
    private var focusMaskController: FocusMaskController?
    private var iconMenuController: IconMenuController?
    private var popupController: PopupController?
    private var screenGroundingController: ScreenGroundingController?
    private var screenObserver: NSObjectProtocol?
    private var statusBarController: StatusBarController?
    private var tutorialActionConsumer: TutorialActionConsumer?
    private var tutorialPlanController: TutorialPlanController?
    private var tutorialSessionController: TutorialSessionController?
    private let stabilityWatcher = ScreenStabilityWatcher()
    private var stabilityIndicator: StabilityIndicatorController?

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func start() {
        guard let screen = screenProvider() else { return }

        let popupPanel = PopupPanel(frame: initialPopupFrame(on: screen.frame))
        let iconPanel = IconPanel(frame: initialIconFrame(on: screen.frame))
        let bboxPanel = DebugBboxPanel(frame: CGRect(origin: .zero, size: DebugBoundingBox.size))
        let stabilityIndicator = StabilityIndicatorController(screenProvider: screenProvider)
        self.stabilityIndicator = stabilityIndicator

        var sessionControllerRef: TutorialSessionController?
        let focusMaskController = FocusMaskController(
            screenProvider: screenProvider,
            interactiveWindowsProvider: {
                [popupPanel, iconPanel]
            },
            onExit: { [weak bboxPanel, weak self] in
                bboxPanel?.orderOut(nil)
                self?.stabilityWatcher.cancel()
            },
            onInsideClick: { [weak bboxPanel, weak self, weak popupPanel, weak iconPanel, screenProvider] in
                bboxPanel?.orderOut(nil)
                guard let sessionController = sessionControllerRef,
                      let stepID = sessionController.currentStepID else { return }
                Task { @MainActor in
                    if let screen = screenProvider(), let self {
                        self.stabilityIndicator?.show()
                        let excluded: [NSWindow] = [popupPanel, iconPanel, self.stabilityIndicator?.window]
                            .compactMap { $0 }
                        await self.stabilityWatcher.waitUntilStable(
                            on: screen,
                            excludingWindows: excluded,
                            onProgress: { [weak self] progress in
                                Task { @MainActor in self?.stabilityIndicator?.update(progress: progress) }
                            }
                        )
                        self.stabilityIndicator?.hide()
                    }
                    await sessionController.confirmStep(stepID: stepID, confirmed: true, note: nil)
                }
            },
            onOutsideClick: { [weak bboxPanel, weak self] in
                bboxPanel?.orderOut(nil)
                self?.stabilityWatcher.cancel()
                guard let sessionController = sessionControllerRef,
                      let stepID = sessionController.currentStepID else { return }
                sessionController.presentContinuePrompt(stepID: stepID)
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
        let tutorialSessionController = TutorialSessionController(
            messageStore: messageStore,
            endpointStore: tutorialEndpointStore,
            fallbackPlanController: tutorialPlanController,
            ignoredWindowProvider: {
                [popupPanel, iconPanel, bboxPanel]
            },
            screenProvider: screenProvider
        )
        sessionControllerRef = tutorialSessionController
        let tutorialActionConsumer = TutorialActionConsumer(
            groundInstruction: { [weak self, weak popupPanel, weak iconPanel, screenProvider] instruction in
                if let self, let screen = screenProvider() {
                    let excluded: [NSWindow] = [popupPanel, iconPanel, self.stabilityIndicator?.window]
                        .compactMap { $0 }
                    self.stabilityWatcher.prewarm(on: screen, excludingWindows: excluded)
                }
                return await screenGroundingController.submit(instruction)
            },
            presentNonSpatial: { step in
                "Showing instruction inline for \(step.action.type)."
            }
        )
        let handleTutorialStep: (TutorialStep) async -> String = { step in
            await tutorialActionConsumer.consume(step: step)
        }
        tutorialSessionController.setTutorialActionHandler(handleTutorialStep)

        popupPanel.contentView = NSHostingView(rootView: ChatPopupView(
            sessionController: tutorialSessionController,
            onTutorialStepSelected: { step in
                await handleTutorialStep(step)
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
        self.applicationMenuController = ApplicationMenuController(
            onConfigureBoundingBoxes: { debugController.showReplacementBbox() }
        )
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
        self.tutorialSessionController = tutorialSessionController

        popupController.showPopup()
        observeScreenChanges()
    }

    func stop() {
        screenObserver.map(NotificationCenter.default.removeObserver)
        screenObserver = nil
        applicationMenuController?.stop()
        statusBarController?.stop()
        debugBboxController?.hide()
        focusMaskController?.hide()
        tutorialSessionController?.stop()
        popupController = nil
        applicationMenuController = nil
        iconMenuController = nil
        debugBboxController = nil
        focusMaskController = nil
        screenGroundingController = nil
        statusBarController = nil
        tutorialActionConsumer = nil
        tutorialPlanController = nil
        tutorialSessionController = nil
    }

    private func initialPopupFrame(on screen: CGRect) -> CGRect {
        CGRect(x: screen.midX - 170, y: screen.midY - 180, width: 340, height: 360)
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
