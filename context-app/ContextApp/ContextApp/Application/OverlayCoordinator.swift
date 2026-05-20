import AppKit
import Combine
import SwiftUI

@MainActor
final class OverlayCoordinator {
    private let endpointStore = GroundingEndpointStore()
    private let messageStore = ChatMessageStore()
    private let screenProvider: () -> NSScreen?
    private let tutorialEndpointStore = TutorialAPIEndpointStore()
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
        let focusMaskController = FocusMaskController(
            screenProvider: screenProvider,
            interactiveWindowsProvider: { [weak clipboardPopoverController] in
                [popupPanel, edgeTabController.window, clipboardPopoverController?.interactiveWindow]
                    .compactMap { $0 }
            },
            onExit: { [weak bboxPanel, weak self, weak clipboardPopoverController] in
                bboxPanel?.orderOut(nil)
                clipboardPopoverController?.hide()
                self?.screenGroundingController?.clearCache()
                self?.stabilityWatcher.cancel()
            },
            onInsideClick: { [weak bboxPanel, weak self, weak popupPanel, weak clipboardPopoverController, screenProvider] () -> Bool in
                guard let sessionController = sessionControllerRef,
                      let stepID = sessionController.currentStepID,
                      let actionIndex = sessionController.currentActionIndex else { return true }
                // For type actions, inside-click is the user focusing the field
                // before typing — not a "done" signal. Keep the mask up; advance
                // is driven by the explicit advance button in the chat popup.
                if sessionController.actionIsType(stepID: stepID, actionIndex: actionIndex) {
                    return false
                }
                bboxPanel?.orderOut(nil)
                clipboardPopoverController?.hide()
                Task { @MainActor in
                    if let screen = screenProvider(), let self {
                        self.stabilityIndicator?.show()
                        let excluded: [NSWindow] = [popupPanel, edgeTabController.window, self.stabilityIndicator?.window]
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
                    let stableScreen = await sessionController.currentScreenSnapshot()
                    await sessionController.confirmStep(
                        stepID: stepID,
                        actionIndex: actionIndex,
                        confirmed: true,
                        note: nil,
                        screen: stableScreen
                    )
                }
                return true
            },
            onOutsideClick: { [weak bboxPanel, weak self, weak clipboardPopoverController] in
                bboxPanel?.orderOut(nil)
                clipboardPopoverController?.hide()
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
            ignoredWindowProvider: { [weak clipboardPopoverController] in
                [popupPanel, edgeTabController.window, bboxPanel, clipboardPopoverController?.interactiveWindow]
                    .compactMap { $0 }
            },
            screenProvider: screenProvider,
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
            presentNonSpatial: { step, actionIndex in
                let kind = step.actions.indices.contains(actionIndex) ? step.actions[actionIndex].type : "<oor>"
                return "Showing instruction inline for \(kind)."
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
