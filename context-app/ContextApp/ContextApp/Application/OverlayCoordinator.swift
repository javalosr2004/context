import AppKit
import Combine
import SwiftUI

@MainActor
final class OverlayCoordinator {
    private let tutorialEndpointStore = TutorialAPIEndpointStore()
    private lazy var endpointStore = GroundingEndpointStore(baseURLStore: tutorialEndpointStore)
    private let messageStore = ChatMessageStore()
    private let screenProvider: () -> NSScreen?
    private let webGroundingEndpointStore = WebGroundingEndpointStore()
    private var devSettingsWindowController: DevSettingsWindowController?

    private var applicationMenuController: ApplicationMenuController?
    private var debugBboxController: DebugBboxController?
    private var edgeTabController: EdgeTabController?
    private var focusMaskController: FocusMaskController?
    private var popupController: PopupController?
    private var screenGroundingController: ScreenGroundingController?
    private var screenObserver: NSObjectProtocol?
    private var statusBarController: StatusBarController?
    private let recordingController = RecordingController()
    private var popupResizeCancellable: AnyCancellable?
    private var tutorialActionConsumer: TutorialActionConsumer?
    private var tutorialPlanController: TutorialPlanController?
    private var tutorialSessionController: TutorialSessionController?
    private var clipboardPopoverController: ClipboardPopoverController?
    private let stabilityWatcher = ScreenStabilityWatcher()
    private var stabilityIndicator: StabilityIndicatorController?
    private var errorIndicator: ErrorIndicatorController?
    private var errorStatusCancellable: AnyCancellable?

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func start() {
        guard let screen = screenProvider() else { return }

        let popupPanel = PopupPanel(frame: initialPopupFrame(on: screen.frame))
        let bboxPanel = DebugBboxPanel(frame: CGRect(origin: .zero, size: DebugBoundingBox.size))
        let stabilityIndicator = StabilityIndicatorController(screenProvider: screenProvider)
        self.stabilityIndicator = stabilityIndicator
        let errorIndicator = ErrorIndicatorController(screenProvider: screenProvider)
        self.errorIndicator = errorIndicator

        let popupController = PopupController(
            popupPanel: popupPanel,
            initialFrame: popupPanel.frame
        )
        let edgeTabController = EdgeTabController(
            screenProvider: screenProvider,
            onToggle: { popupController.toggle() },
            onShowDevSettings: { [weak self] in self?.showDevSettings() }
        )

        var sessionControllerRef: TutorialSessionController?
        let clipboardPopoverController = ClipboardPopoverController(screenProvider: screenProvider)
        let tutorialTooltipController = TutorialTooltipController(
            screenProvider: screenProvider,
            onNextProvider: {
                guard let sessionController = sessionControllerRef,
                      let stepID = sessionController.currentStepID,
                      let actionIndex = sessionController.currentActionIndex else {
                    return nil
                }
                return {
                    Task { @MainActor in
                        await sessionController.confirmStep(
                            stepID: stepID,
                            actionIndex: actionIndex,
                            confirmed: true,
                            note: nil
                        )
                    }
                }
            }
        )
        let focusMaskController = FocusMaskController(
            screenProvider: screenProvider,
            interactiveWindowsProvider: { [weak clipboardPopoverController, weak tutorialTooltipController] in
                [
                    popupPanel,
                    edgeTabController.window,
                    clipboardPopoverController?.interactiveWindow,
                    tutorialTooltipController?.interactiveWindow,
                ].compactMap { $0 }
            },
            onExit: { [weak bboxPanel, weak self, weak clipboardPopoverController, weak tutorialTooltipController] in
                bboxPanel?.orderOut(nil)
                clipboardPopoverController?.hide()
                tutorialTooltipController?.hide()
                self?.screenGroundingController?.clearCache()
                self?.stabilityWatcher.cancel()
            },
            onInsideClick: { () -> Bool in
                // Advance is driven exclusively by the explicit "Next" button in
                // the tutorial-tooltip callout. An inside-click on the indicator
                // is just the user interacting with the underlying app.
                return false
            },
            onOutsideClick: { [weak bboxPanel, weak self, weak clipboardPopoverController, weak tutorialTooltipController] in
                bboxPanel?.orderOut(nil)
                clipboardPopoverController?.hide()
                tutorialTooltipController?.hide()
                self?.screenGroundingController?.clearCache()
                self?.stabilityWatcher.cancel()
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
            ignoredWindowProvider: { [weak clipboardPopoverController, weak tutorialTooltipController] in
                [
                    popupPanel,
                    edgeTabController.window,
                    bboxPanel,
                    clipboardPopoverController?.interactiveWindow,
                    tutorialTooltipController?.interactiveWindow,
                ].compactMap { $0 }
            },
            screenProvider: screenProvider,
            tooltipController: tutorialTooltipController,
            clipboardPopoverController: clipboardPopoverController
        )
        let tutorialPlanController = TutorialPlanController(
            endpointStore: tutorialEndpointStore,
            ignoredWindowProvider: {
                [popupPanel, edgeTabController.window, bboxPanel]
            },
            screenProvider: screenProvider
        )
        let tutorialSessionController = TutorialSessionController(
            messageStore: messageStore,
            endpointStore: tutorialEndpointStore,
            fallbackPlanController: tutorialPlanController,
            ignoredWindowProvider: {
                [popupPanel, edgeTabController.window, bboxPanel]
            },
            screenProvider: screenProvider
        )
        sessionControllerRef = tutorialSessionController
        errorStatusCancellable = tutorialSessionController.$status
            .receive(on: DispatchQueue.main)
            .sink { [weak errorIndicator] status in
                guard let errorIndicator else { return }
                if case .failed(let message) = status {
                    errorIndicator.show(message: message)
                } else {
                    errorIndicator.hide()
                }
            }
        let tutorialActionConsumer = TutorialActionConsumer(
            groundInstruction: { [weak self, weak popupPanel, screenProvider] instruction in
                if let self, let screen = screenProvider() {
                    let excluded: [NSWindow] = [popupPanel, edgeTabController.window, self.stabilityIndicator?.window]
                        .compactMap { $0 }
                    self.stabilityWatcher.prewarm(on: screen, excludingWindows: excluded)
                }
                return await screenGroundingController.submit(instruction)
            },
            presentNonSpatial: { [weak self, weak bboxPanel, weak clipboardPopoverController, weak tutorialTooltipController, screenProvider] step, actionIndex in
                bboxPanel?.orderOut(nil)
                clipboardPopoverController?.hide()
                self?.focusMaskController?.hide()
                self?.screenGroundingController?.clearCache()
                self?.stabilityWatcher.cancel()

                guard step.actions.indices.contains(actionIndex) else { return "" }
                let action = step.actions[actionIndex]

                if case .userChoice = action, !step.instruction.isEmpty,
                   let screen = screenProvider() {
                    let anchor = CGRect(
                        x: screen.frame.midX - 1,
                        y: screen.frame.midY - 1,
                        width: 2,
                        height: 2
                    )
                    tutorialTooltipController?.show(beside: anchor, message: step.instruction)
                } else {
                    tutorialTooltipController?.hide()
                }

                return "Showing instruction inline for \(action.type)."
            }
        )
        let handleTutorialStep: (TutorialStep, Int) async -> String = { step, actionIndex in
            await tutorialActionConsumer.consume(step: step, actionIndex: actionIndex)
        }
        tutorialSessionController.setTutorialActionHandler(handleTutorialStep)

        popupPanel.contentView = NSHostingView(rootView: ChatPopupView(
            sessionController: tutorialSessionController,
            recordingController: recordingController,
            onTutorialStepSelected: { step in
                await handleTutorialStep(step, 0)
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
                popupController.collapse()
            },
            onShowRecordings: { [weak self] in
                self?.statusBarController?.showRecordings()
            }
        ))
        popupResizeCancellable = tutorialSessionController.objectWillChange.sink { [weak self] _ in
            DispatchQueue.main.async { [weak self] in
                self?.fitPopupToContent()
            }
        }

        self.debugBboxController = debugController
        self.applicationMenuController = ApplicationMenuController(
            onConfigureBoundingBoxes: { debugController.showReplacementBbox() }
        )
        self.edgeTabController = edgeTabController
        self.focusMaskController = focusMaskController
        self.popupController = popupController
        self.screenGroundingController = screenGroundingController
        self.statusBarController = StatusBarController(
            endpointStore: endpointStore,
            tutorialEndpointStore: tutorialEndpointStore,
            recordingController: recordingController,
            onShowOverlay: { popupController.restore() },
            onTestBbox: { debugController.showReplacementBbox() }
        )
        self.tutorialActionConsumer = tutorialActionConsumer
        self.tutorialPlanController = tutorialPlanController
        self.tutorialSessionController = tutorialSessionController
        self.clipboardPopoverController = clipboardPopoverController

        popupController.showPopup()
        edgeTabController.start()
        fitPopupToContent()
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
        edgeTabController?.stop()
        popupController = nil
        applicationMenuController = nil
        debugBboxController = nil
        edgeTabController = nil
        focusMaskController = nil
        screenGroundingController = nil
        statusBarController = nil
        popupResizeCancellable = nil
        errorStatusCancellable = nil
        errorIndicator?.hide()
        errorIndicator = nil
        tutorialActionConsumer = nil
        tutorialPlanController = nil
        tutorialSessionController = nil
        clipboardPopoverController?.hide()
        clipboardPopoverController = nil
        devSettingsWindowController?.close()
        devSettingsWindowController = nil
    }

    private func initialPopupFrame(on screen: CGRect) -> CGRect {
        CGRect(x: screen.midX - 170, y: screen.midY - 180, width: 340, height: 360)
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
        edgeTabController?.reanchor()
        fitPopupToContent()
    }

    private func fitPopupToContent() {
        guard let screen = screenProvider() else { return }
        popupController?.fitPopupHeight(to: screen.frame)
    }

    private func showDevSettings() {
        if devSettingsWindowController == nil {
            devSettingsWindowController = DevSettingsWindowController(
                visualStore: endpointStore,
                webStore: webGroundingEndpointStore,
                tutorialStore: tutorialEndpointStore
            )
        }
        devSettingsWindowController?.show()
    }
}
