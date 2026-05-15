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
    private var instructionCardController: InstructionCardController?
    private var popupController: PopupController?
    private var screenGroundingController: ScreenGroundingController?
    private var screenObserver: NSObjectProtocol?
    private var statusBarController: StatusBarController?
    private var tutorialActionConsumer: TutorialActionConsumer?
    private var tutorialPlanController: TutorialPlanController?
    private var tutorialSessionController: TutorialSessionController?
    private var tutorialTooltipController: TutorialTooltipController?

    init(screenProvider: @escaping () -> NSScreen?) {
        self.screenProvider = screenProvider
    }

    func start() {
        guard let screen = screenProvider() else { return }

        let popupPanel = PopupPanel(frame: initialPopupFrame(on: screen.frame))
        let iconPanel = IconPanel(frame: initialIconFrame(on: screen.frame))
        let bboxPanel = DebugBboxPanel(frame: CGRect(origin: .zero, size: DebugBoundingBox.size))

        var sessionControllerRef: TutorialSessionController?
        var instructionCardControllerRef: InstructionCardController?
        let tooltipController = TutorialTooltipController(screenProvider: screenProvider)
        let focusMaskController = FocusMaskController(
            screenProvider: screenProvider,
            interactiveWindowsProvider: {
                var windows: [NSWindow] = [popupPanel, iconPanel]
                if let instructionWindow = instructionCardControllerRef?.interactiveWindow {
                    windows.append(instructionWindow)
                }
                return windows
            },
            onExit: { [weak bboxPanel] in
                bboxPanel?.orderOut(nil)
                instructionCardControllerRef?.hide()
                tooltipController.hide()
            },
            onInsideClick: { [weak bboxPanel] in
                bboxPanel?.orderOut(nil)
                instructionCardControllerRef?.hide()
                tooltipController.hide()
                guard let sessionController = sessionControllerRef,
                      let stepID = sessionController.currentStepID else { return }
                Task { @MainActor in
                    await sessionController.confirmStep(stepID: stepID, confirmed: true, note: nil)
                }
            },
            onOutsideClick: { [weak bboxPanel] in
                bboxPanel?.orderOut(nil)
                instructionCardControllerRef?.hide()
                tooltipController.hide()
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
            screenProvider: screenProvider,
            tooltipController: tooltipController
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
        let instructionCardController: InstructionCardController
        instructionCardController = InstructionCardController(
            screenProvider: screenProvider,
            onDone: { stepID in
                Task { @MainActor in
                    await tutorialSessionController.confirmStep(stepID: stepID, confirmed: true, note: nil)
                }
            },
            onCopy: { text in
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(text, forType: .string)
            }
        )
        instructionCardControllerRef = instructionCardController
        let tutorialActionConsumer = TutorialActionConsumer(
            groundInstruction: { instruction in
                await screenGroundingController.submit(instruction)
            },
            presentNonSpatial: { step in
                await MainActor.run {
                    instructionCardController.show(
                        stepID: step.stepId,
                        title: Self.instructionCardTitle(for: step.action),
                        message: step.instruction,
                        copyableText: nil
                    )
                }
                return "Showing instruction card for \(step.action.type)."
            }
        )
        let handleTutorialStep: (TutorialStep) async -> String = { step in
            let result = await tutorialActionConsumer.consume(step: step)
            if case .type(let action) = step.action, !action.text.isEmpty {
                await MainActor.run {
                    instructionCardController.show(
                        stepID: step.stepId,
                        title: "Type",
                        message: step.instruction,
                        copyableText: action.text
                    )
                }
            }
            return result
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
        self.instructionCardController = instructionCardController
        self.tutorialActionConsumer = tutorialActionConsumer
        self.tutorialPlanController = tutorialPlanController
        self.tutorialSessionController = tutorialSessionController
        self.tutorialTooltipController = tooltipController

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
        instructionCardController?.hide()
        tutorialTooltipController?.hide()
        tutorialSessionController?.stop()
        popupController = nil
        applicationMenuController = nil
        iconMenuController = nil
        debugBboxController = nil
        focusMaskController = nil
        instructionCardController = nil
        screenGroundingController = nil
        statusBarController = nil
        tutorialActionConsumer = nil
        tutorialPlanController = nil
        tutorialSessionController = nil
        tutorialTooltipController = nil
    }

    private static func instructionCardTitle(for action: TutorialAction) -> String {
        switch action {
        case .scroll(let action):
            return "Scroll \(action.direction.rawValue)"
        case .pressKey(let action):
            return "Press \(action.key)"
        case .wait:
            return "Wait"
        case .confirm:
            return "Confirm"
        default:
            return "Next step"
        }
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
