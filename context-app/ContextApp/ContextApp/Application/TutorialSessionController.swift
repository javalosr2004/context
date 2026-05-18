import AppKit
import Combine
import Dispatch
import Foundation
import OSLog

enum TutorialSessionUIStatus: Equatable {
    case ready
    case preparingScreen
    case sending
    case planning(String)
    case awaitingConfirmation
    case completed
    case failed(String)

    var label: String {
        switch self {
        case .ready:
            return "Ready"
        case .preparingScreen:
            return "Preparing screen"
        case .sending:
            return "Sending"
        case .planning(let label):
            return label
        case .awaitingConfirmation:
            return "Awaiting confirmation"
        case .completed:
            return "Completed"
        case .failed:
            return "Error"
        }
    }

    var isBusy: Bool {
        switch self {
        case .preparingScreen, .sending, .planning:
            return true
        case .ready, .awaitingConfirmation, .completed, .failed:
            return false
        }
    }
}

@MainActor
final class TutorialSessionController: ObservableObject {
    @Published private(set) var awaitingConfirmationStepID: String?
    @Published private(set) var awaitingActionIndex: Int?
    @Published private(set) var currentStepID: String?
    @Published private(set) var currentActionIndex: Int?
    @Published private(set) var draftPlan: DraftPlan?
    @Published private(set) var messages: [ChatMessage]
    @Published private(set) var pendingContinuePromptStepID: String?
    @Published private(set) var status: TutorialSessionUIStatus = .ready
    @Published private(set) var agentTurn: (turn: Int, maxTurns: Int)?
    @Published private(set) var webSources: [TutorialSessionWebSource] = []
    @Published private(set) var stepProgress: (stepIndex: Int, totalSteps: Int, actionIndex: Int, totalActions: Int)?
    @Published private(set) var lastPlanDiff: (frozenPrefixLen: Int, newTailLen: Int, refinedCurrent: Bool, totalSteps: Int)?

    private let capture: ScreenFrameCapture
    private let client: TutorialSessionAPIClient
    private let endpointStore: TutorialAPIEndpointStore
    private let fallbackPlanController: TutorialPlanController?
    private let ignoredWindowProvider: () -> [NSWindow]
    private let logger = Logger(subsystem: "ContextApp", category: "TutorialSession")
    private let messageStore: ChatMessageStore
    private let screenCaptureTimeoutNanoseconds: UInt64
    private let screenProvider: () -> NSScreen?

    private var tutorialActionHandler: ((TutorialStep, Int) async -> String)?
    private var listenTask: Task<Void, Never>?
    private var sessionID: String?
    private var socket: URLSessionWebSocketTask?
    private var isStreamingTutorialText = false
    // Slot we've already grounded via optimistic advance; suppresses the
    // duplicate grounding when the matching step_ready eventually arrives.
    private var optimisticallyGroundedSlot: (stepID: String, actionIndex: Int)?

    init(
        messageStore: ChatMessageStore,
        endpointStore: TutorialAPIEndpointStore,
        fallbackPlanController: TutorialPlanController? = nil,
        client: TutorialSessionAPIClient = TutorialSessionAPIClient(),
        capture: ScreenFrameCapture = ScreenFrameCapture(),
        ignoredWindowProvider: @escaping () -> [NSWindow] = { [] },
        screenProvider: @escaping () -> NSScreen?,
        screenCaptureTimeoutNanoseconds: UInt64 = 5_000_000_000
    ) {
        self.capture = capture
        self.client = client
        self.endpointStore = endpointStore
        self.fallbackPlanController = fallbackPlanController
        self.ignoredWindowProvider = ignoredWindowProvider
        self.messageStore = messageStore
        self.messages = messageStore.messages
        self.screenProvider = screenProvider
        self.screenCaptureTimeoutNanoseconds = screenCaptureTimeoutNanoseconds
    }

    func sendComposerText(_ text: String) async {
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedText.isEmpty, !status.isBusy else { return }

        await sendUserMessage(trimmedText)
    }

    func markStepStarted(stepID: String, actionIndex: Int) async {
        do {
            try await sendSessionEvent(.stepStarted(stepID: stepID, actionIndex: actionIndex))
        } catch {
            applyFailure("Could not start tutorial step: \(error.localizedDescription)")
        }
    }

    func presentContinuePrompt(stepID: String) {
        pendingContinuePromptStepID = stepID
    }

    func dismissContinuePrompt() {
        pendingContinuePromptStepID = nil
    }

    func confirmStep(
        stepID: String,
        actionIndex: Int,
        confirmed: Bool,
        note: String?,
        screen: TutorialSessionScreenSnapshot? = nil
    ) async {
        pendingContinuePromptStepID = nil
        do {
            status = .sending
            try await sendSessionEvent(
                .userConfirmation(
                    stepID: stepID,
                    actionIndex: actionIndex,
                    confirmed: confirmed,
                    note: note,
                    screen: screen
                )
            )
            awaitingConfirmationStepID = nil
            awaitingActionIndex = nil
            status = confirmed ? .planning("Continuing") : .planning("Replanning from current screen")
            if confirmed {
                advanceOptimistically(after: stepID, actionIndex: actionIndex)
            }
        } catch {
            applyFailure("Could not confirm tutorial step: \(error.localizedDescription)")
        }
    }

    // The backend re-grounds via an LLM round-trip after every screen-changing
    // confirm before emitting the next step_ready, which stalls the UI. Since
    // the plan is already a hypothesis we render eagerly, advance to the next
    // slot locally so the user can keep moving; if the re-ground amends the
    // plan tail, planUpdated reconciles.
    private func advanceOptimistically(after stepID: String, actionIndex: Int) {
        guard let next = nextSlot(after: stepID, actionIndex: actionIndex) else {
            return
        }
        currentStepID = next.stepID
        currentActionIndex = next.actionIndex
        optimisticallyGroundedSlot = next
        groundStep(stepID: next.stepID, actionIndex: next.actionIndex)
    }

    private func nextSlot(after stepID: String, actionIndex: Int) -> (stepID: String, actionIndex: Int)? {
        guard let plan = latestPlan() else { return nil }
        guard let stepIndex = plan.steps.firstIndex(where: { $0.stepId == stepID }) else {
            return nil
        }
        let step = plan.steps[stepIndex]
        let nextActionIndex = actionIndex + 1
        if nextActionIndex < step.actions.count {
            return (step.stepId, nextActionIndex)
        }
        let nextStepIndex = stepIndex + 1
        guard nextStepIndex < plan.steps.count else { return nil }
        let nextStep = plan.steps[nextStepIndex]
        guard !nextStep.actions.isEmpty else { return nil }
        return (nextStep.stepId, 0)
    }

    private func latestPlan() -> TutorialPlan? {
        for message in messageStore.messages.reversed() {
            if case .tutorialPlan(let plan) = message.content {
                return plan
            }
        }
        return nil
    }

    func appendTutorialText(_ text: String) {
        guard messageStore.appendTutorialText(text) != nil else { return }
        messages = messageStore.messages
    }

    func appendTutorialTextDelta(_ text: String) {
        guard messageStore.appendTutorialTextDelta(text) != nil else { return }
        isStreamingTutorialText = true
        messages = messageStore.messages
    }

    func appendUserText(_ text: String) {
        guard messageStore.appendUserText(text) != nil else { return }
        messages = messageStore.messages
    }

    func stop() {
        clearSocket()
    }

    func startNewChat() {
        clearSocket()
        currentStepID = nil
        currentActionIndex = nil
        awaitingConfirmationStepID = nil
        awaitingActionIndex = nil
        pendingContinuePromptStepID = nil
        draftPlan = nil
        optimisticallyGroundedSlot = nil
        agentTurn = nil
        webSources = []
        stepProgress = nil
        lastPlanDiff = nil
        status = .ready
        messageStore.removeAll()
        messages = messageStore.messages
    }

    func setTutorialActionHandler(_ handler: @escaping (TutorialStep, Int) async -> String) {
        tutorialActionHandler = handler
    }

    private func sendUserMessage(_ text: String) async {
        isStreamingTutorialText = false
        appendUserText(text)

        do {
            status = .sending
            try await sendSessionEvent(.userMessage(text: text))
        } catch {
            await runFallbackPlanIfAvailable(text: text, originalError: error)
        }
    }

    private func handleScreenRequest(requestID: String, reason: String) {
        Task { [weak self] in
            guard let self else { return }
            await self.sendRequestedScreen(requestID: requestID, reason: reason)
        }
    }

    private func sendRequestedScreen(requestID: String, reason: String) async {
        logger.info("Screen requested: \(reason, privacy: .public)")
        do {
            status = .preparingScreen
            let screen = try await captureScreenSnapshot()
            status = .sending
            try await sendSessionEvent(.userScreen(requestID: requestID, screen: screen))
        } catch {
            applyFailure("Could not send requested screen: \(error.localizedDescription)")
        }
    }

    private func runFallbackPlanIfAvailable(text: String, originalError: Error) async {
        guard let fallbackPlanController else {
            applyFailure("Tutorial session failed: \(originalError.localizedDescription)")
            return
        }

        do {
            logger.error("Tutorial session failed, using fallback planner: \(originalError.localizedDescription, privacy: .public)")
            status = .planning("Planning tutorial")
            let plan = try await fallbackPlanController.submit(text)
            appendTutorialPlan(plan)
            status = .ready
        } catch {
            applyFailure("Tutorial session failed: \(originalError.localizedDescription). Fallback failed: \(error.localizedDescription)")
        }
    }

    private func connectedSocket() async throws -> URLSessionWebSocketTask {
        if let socket, socket.closeCode == .invalid, socket.state == .running {
            return socket
        }
        clearSocket()

        guard let baseURL = endpointStore.baseURL.flatMap(URL.init(string:)) else {
            throw TutorialAPIEndpointStoreError.missingBaseURL
        }

        let createdSession = try await client.createSession(baseURL: baseURL)
        let newSocket = try client.openSocket(baseURL: baseURL, sessionID: createdSession.sessionID)
        do {
            try await client.waitUntilReady(on: newSocket, sessionID: createdSession.sessionID)
        } catch {
            newSocket.cancel(with: .goingAway, reason: nil)
            throw error
        }
        sessionID = createdSession.sessionID
        socket = newSocket
        startListening(on: newSocket)
        return newSocket
    }

    private func sendSessionEvent(_ event: TutorialSessionClientEvent) async throws {
        let socket = try await connectedSocket()
        do {
            try await client.send(event, on: socket)
        } catch {
            _ = clearSocketIfCurrent(socket)
            throw error
        }
    }

    private func startListening(on socket: URLSessionWebSocketTask) {
        listenTask?.cancel()
        listenTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    guard let self else { return }
                    let event = try await self.client.receive(from: socket)
                    self.apply(event)
                } catch is CancellationError {
                    return
                } catch {
                    guard let self else { return }
                    guard self.clearSocketIfCurrent(socket) else { return }
                    self.applyFailure("Tutorial session socket failed: \(error.localizedDescription)")
                    return
                }
            }
        }
    }

    private func clearSocket() {
        listenTask?.cancel()
        listenTask = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        sessionID = nil
    }

    private func clearSocketIfCurrent(_ socketToClear: URLSessionWebSocketTask) -> Bool {
        guard socket === socketToClear else { return false }
        clearSocket()
        return true
    }

    private func apply(_ event: TutorialSessionServerEvent) {
        switch event {
        case .sessionReady:
            status = .ready
        case .statusChanged(let rawStatus, let label):
            applyStatus(rawStatus, label: label)
        case .textDelta(let text):
            appendTutorialTextDelta(text)
        case .textResponse(let text):
            if isStreamingTutorialText {
                _ = messageStore.replaceLastTutorialText(text)
                messages = messageStore.messages
                isStreamingTutorialText = false
            } else {
                appendTutorialText(text)
            }
            status = .ready
        case .planReady(let plan):
            appendTutorialPlan(plan)
            status = .ready
        case .planUpdated(let plan):
            replaceLatestTutorialPlan(plan)
            status = .ready
        case .draftPlanReady(let plan):
            draftPlan = plan
        case .unknown(let type):
            logger.debug("Ignoring unknown tutorial session event '\(type, privacy: .public)'")
        case .tutorialAction:
            // Backend no longer emits tutorial_action; grounding is triggered on .stepReady.
            // Kept as a decoded-but-ignored case for defensive forward/backward compatibility.
            break
        case .stepReady(let stepID, let actionIndex):
            applyStepReady(stepID: stepID, actionIndex: actionIndex)
        case .awaitingConfirmation(let stepID, let actionIndex):
            awaitingConfirmationStepID = stepID
            awaitingActionIndex = actionIndex
            status = .awaitingConfirmation
        case .screenRequested(let requestID, let reason):
            handleScreenRequest(requestID: requestID, reason: reason)
        case .webSearchStarted:
            webSources = []
            status = .planning("Searching the web…")
        case .webSearchCompleted(_, let sourceCount, let sources, _):
            webSources = sources
            if sourceCount > 0 {
                status = .planning("Found \(sourceCount) source\(sourceCount == 1 ? "" : "s")")
            }
        case .agentTurn(let turn, let maxTurns):
            agentTurn = (turn, maxTurns)
            status = .planning("Thinking (pass \(turn)/\(maxTurns))")
        case .planDiff(let frozenPrefixLen, let newTailLen, let refinedCurrent, let totalSteps):
            lastPlanDiff = (frozenPrefixLen, newTailLen, refinedCurrent, totalSteps)
        case .stepProgress(_, let stepIndex, let totalSteps, let actionIndex, let totalActions):
            stepProgress = (stepIndex, totalSteps, actionIndex, totalActions)
        case .sessionCompleted:
            currentStepID = nil
            currentActionIndex = nil
            awaitingConfirmationStepID = nil
            awaitingActionIndex = nil
            optimisticallyGroundedSlot = nil
            appendTutorialText("Tutorial completed.")
            status = .completed
        case .error(_, let message):
            applyFailure(message)
        }
    }

    private func applyStatus(_ rawStatus: String, label: String) {
        switch rawStatus {
        case "ready", "step_ready":
            status = .ready
        case "planning", "needs_screen":
            status = .planning(label)
        case "awaiting_confirmation":
            status = .awaitingConfirmation
        case "completed":
            status = .completed
        default:
            status = .planning(label)
        }
    }

    private func appendTutorialPlan(_ plan: TutorialPlan) {
        guard messageStore.appendTutorialPlan(plan) != nil else { return }
        messages = messageStore.messages
    }

    private func replaceLatestTutorialPlan(_ plan: TutorialPlan) {
        guard messageStore.replaceLatestTutorialPlan(plan) != nil else { return }
        messages = messageStore.messages
    }

    private func applyStepReady(stepID: String, actionIndex: Int) {
        currentStepID = stepID
        currentActionIndex = actionIndex
        status = .ready
        if let grounded = optimisticallyGroundedSlot,
           grounded.stepID == stepID,
           grounded.actionIndex == actionIndex {
            optimisticallyGroundedSlot = nil
            return
        }
        optimisticallyGroundedSlot = nil
        groundStep(stepID: stepID, actionIndex: actionIndex)
    }

    private func groundStep(stepID: String, actionIndex: Int) {
        guard let tutorialActionHandler else { return }
        guard let step = latestStep(withID: stepID) else {
            logger.debug("grounding skipped: unknown step id '\(stepID, privacy: .public)'")
            return
        }
        guard actionIndex >= 0, actionIndex < step.actions.count else {
            logger.debug("grounding skipped: action_index \(actionIndex, privacy: .public) out of range for step '\(stepID, privacy: .public)'")
            return
        }
        Task { [weak self] in
            _ = await tutorialActionHandler(step, actionIndex)
            await MainActor.run {
                self?.status = .ready
            }
        }
    }

    private func latestStep(withID stepID: String) -> TutorialStep? {
        for message in messageStore.messages.reversed() {
            if case .tutorialPlan(let plan) = message.content,
               let step = plan.steps.first(where: { $0.stepId == stepID }) {
                return step
            }
        }
        return nil
    }

    private func applyFailure(_ message: String) {
        logger.error("\(message, privacy: .public)")
        status = .failed(message)
    }

    /// Best-effort capture for callers (e.g. OverlayCoordinator after a
    /// stability wait) that want to attach the post-action screen to a
    /// confirmation. Returns nil on failure rather than throwing so the
    /// caller can still send the confirmation without a screen.
    func currentScreenSnapshot() async -> TutorialSessionScreenSnapshot? {
        do {
            return try await captureScreenSnapshot()
        } catch {
            logger.error("currentScreenSnapshot capture failed: \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }

    private func captureScreenSnapshot() async throws -> TutorialSessionScreenSnapshot {
        guard let screen = screenProvider() else {
            throw TutorialPlanControllerError.noScreen
        }

        let frame = try await captureFrameWithTimeout(on: screen)
        let ignoredWindowFrames = ignoredWindowProvider()
            .filter(\.isVisible)
            .map(\.frame)
        let screenJPEGData = try ScreenFrameMasker.mask(
            jpegData: frame.jpegData,
            screenFrame: screen.frame,
            ignoredWindowFrames: ignoredWindowFrames
        )
        return TutorialSessionScreenSnapshot(
            mimeType: "image/jpeg",
            dataBase64: screenJPEGData.base64EncodedString()
        )
    }

    private func captureFrameWithTimeout(on screen: NSScreen) async throws -> CapturedScreenFrame {
        let captureTask = Task {
            try await capture.captureFrame(on: screen)
        }
        let timeoutTask = Task {
            try await Task.sleep(nanoseconds: screenCaptureTimeoutNanoseconds)
            captureTask.cancel()
        }

        defer {
            timeoutTask.cancel()
        }

        do {
            return try await captureTask.value
        } catch is CancellationError {
            throw TutorialPlanControllerError.screenCaptureTimedOut
        }
    }
}
