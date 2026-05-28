import AppKit
import Combine
import CryptoKit
import Dispatch
import Foundation
import OSLog

enum TutorialSessionUIStatus: Equatable {
    case ready
    case preparingScreen
    case sending
    case planning(String)
    case verifying
    case awaitingConfirmation
    case awaitingCompletion
    case completed
    case failed(String)

    var label: String {
        switch self {
        case .ready:
            return "Ready"
        case .preparingScreen:
            return "Capturing screen"
        case .sending:
            return "Sending"
        case .planning(let label):
            return label
        case .verifying:
            return "Checking screen"
        case .awaitingConfirmation:
            return "Awaiting confirmation"
        case .awaitingCompletion:
            return "Confirm completion"
        case .completed:
            return "Completed"
        case .failed:
            return "Error"
        }
    }

    var isBusy: Bool {
        switch self {
        case .preparingScreen, .sending, .planning, .verifying:
            return true
        case .ready, .awaitingConfirmation, .awaitingCompletion, .completed, .failed:
            return false
        }
    }
}

struct PendingCompletionPrompt: Equatable {
    enum Source: String, Equatable {
        case llm
        case backend
    }

    let reason: String
    let source: Source
}

struct PendingQuestionBatch: Equatable {
    let batchID: String
    let reason: String
    let questions: [TutorialAssistantQuestion]
}

/// Open verification hint toast bound to the overlay UI.
///
/// `autoReplanning == true` means the backend has already staged a replan
/// that fires on timeout (verdict was diverged or blocked). The toast can
/// surface a "re-routing…" affordance. `false` means the backend will only
/// replan if the user explicitly taps "off track" (verdict was unsure).
struct PendingVerificationHint: Equatable {
    let stepID: String
    let verdict: TutorialVerificationVerdict
    let reason: String
    let autoReplanning: Bool
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
    @Published private(set) var pendingCompletionPrompt: PendingCompletionPrompt?
    @Published private(set) var pendingQuestionBatch: PendingQuestionBatch?
    @Published private(set) var awaitingHintResponse: PendingVerificationHint?
    @Published private(set) var status: TutorialSessionUIStatus = .ready
    @Published private(set) var agentTurn: (turn: Int, maxTurns: Int)?
    @Published private(set) var webSources: [TutorialSessionWebSource] = []
    @Published private(set) var stepProgress: (stepIndex: Int, totalSteps: Int, actionIndex: Int, totalActions: Int)?
    @Published private(set) var lastPlanDiff: (frozenPrefixLen: Int, newTailLen: Int, refinedCurrent: Bool, totalSteps: Int)?
    /// SHA-256 of the most recent screen capture's JPEG bytes. Used to join
    /// eval annotations to the frame the annotator was looking at.
    @Published private(set) var lastFrameHash: String?

    private let capture: ScreenFrameCapture
    private let client: TutorialSessionAPIClient
    private let endpointStore: TutorialAPIEndpointStore
    private let fallbackPlanController: TutorialPlanController?
    private let ignoredWindowProvider: () -> [NSWindow]
    private let logger = Logger(subsystem: "ContextApp", category: "TutorialSession")
    private let messageStore: ChatMessageStore
    private let screenCaptureTimeoutNanoseconds: UInt64
    private let screenProvider: () -> NSScreen?
    private let isGroundingAutoFireEnabled: () -> Bool

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
        screenCaptureTimeoutNanoseconds: UInt64 = 5_000_000_000,
        isGroundingAutoFireEnabled: @escaping () -> Bool = { false }
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
        self.isGroundingAutoFireEnabled = isGroundingAutoFireEnabled
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

    /// Confirm the backend's "are you done?" prompt and let the session end.
    func confirmCompletion() async {
        guard pendingCompletionPrompt != nil else { return }
        pendingCompletionPrompt = nil
        do {
            status = .sending
            try await sendSessionEvent(
                .userCompletionResponse(confirmed: true, note: nil)
            )
        } catch {
            applyFailure("Could not confirm tutorial completion: \(error.localizedDescription)")
        }
    }

    /// Submit answers to a pending clarifying-question batch. Every
    /// question in ``pendingQuestionBatch`` must have a non-empty entry
    /// in ``answers``; otherwise the call is dropped to match the
    /// backend's validation contract.
    func submitQuestionAnswers(_ answers: [String: String]) async {
        guard let batch = pendingQuestionBatch else { return }
        let trimmed: [TutorialUserAnswer] = batch.questions.compactMap { question in
            let value = answers[question.questionID]?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !value.isEmpty else { return nil }
            return TutorialUserAnswer(questionID: question.questionID, text: value)
        }
        guard trimmed.count == batch.questions.count else { return }
        pendingQuestionBatch = nil
        do {
            status = .planning("Planning with your answers")
            try await sendSessionEvent(
                .userAnswer(batchID: batch.batchID, answers: trimmed)
            )
        } catch {
            applyFailure("Could not submit answers: \(error.localizedDescription)")
        }
    }

    /// Reject the completion prompt; the planner will re-engage with the note
    /// (if any) as context for the next step.
    func rejectCompletion(note: String? = nil) async {
        guard pendingCompletionPrompt != nil else { return }
        pendingCompletionPrompt = nil
        do {
            status = .planning("Replanning")
            try await sendSessionEvent(
                .userCompletionResponse(confirmed: false, note: note)
            )
        } catch {
            applyFailure("Could not reject tutorial completion: \(error.localizedDescription)")
        }
    }

    /// Resolve an open VerificationHintEvent toast. The backend tracks the
    /// open hint by `stepID`; if the toast has already been replaced (a
    /// later verifier verdict arrived first), it drops the response as
    /// stale — so it's safe to fire this even if the local state has
    /// moved on. We clear the local slot eagerly so the toast disappears.
    func respondToHint(action: TutorialHintResponseAction) async {
        guard let pending = awaitingHintResponse else { return }
        awaitingHintResponse = nil
        do {
            try await sendSessionEvent(
                .userHintResponse(stepID: pending.stepID, action: action)
            )
        } catch {
            // Best-effort: the toast has already been dismissed locally,
            // so a send failure just leaves the backend's open-hint slot
            // to be cleaned up by the next instruction transition.
            logger.error("respondToHint(\(action.rawValue, privacy: .public)) failed: \(error.localizedDescription, privacy: .public)")
        }
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
            if confirmed, isGroundingAutoFireEnabled() {
                advanceOptimistically(after: stepID, actionIndex: actionIndex)
            }
        } catch {
            applyFailure("Could not confirm tutorial step: \(error.localizedDescription)")
        }
    }

    // Eagerly ground the next slot to mask the backend's per-step LLM re-ground
    // round-trip. Skipped when the just-confirmed action is a `type`: the
    // confirm there fires on a click that only focuses the field, so the user
    // is still mid-typing — grounding the next slot now races their input.
    private func advanceOptimistically(after stepID: String, actionIndex: Int) {
        if confirmedActionIsType(stepID: stepID, actionIndex: actionIndex) { return }
        guard let next = nextSlot(after: stepID, actionIndex: actionIndex) else { return }
        currentStepID = next.stepID
        currentActionIndex = next.actionIndex
        optimisticallyGroundedSlot = next
        groundStep(stepID: next.stepID, actionIndex: next.actionIndex)
    }

    private func confirmedActionIsType(stepID: String, actionIndex: Int) -> Bool {
        actionIsType(stepID: stepID, actionIndex: actionIndex)
    }

    func actionIsType(stepID: String, actionIndex: Int) -> Bool {
        guard let step = latestStep(withID: stepID),
              actionIndex >= 0, actionIndex < step.actions.count else { return false }
        if case .type = step.actions[actionIndex] { return true }
        return false
    }

    private func nextSlot(after stepID: String, actionIndex: Int) -> (stepID: String, actionIndex: Int)? {
        guard let plan = latestPlan(),
              let stepIndex = plan.steps.firstIndex(where: { $0.stepId == stepID }) else {
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
        pendingCompletionPrompt = nil
        pendingQuestionBatch = nil
        awaitingHintResponse = nil
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
            status = .planning("Thinking")
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
            pendingCompletionPrompt = nil
            pendingQuestionBatch = nil
            awaitingHintResponse = nil
            appendTutorialText("Tutorial completed.")
            status = .completed
        case .instructionVerificationStarted:
            status = .verifying
        case .instructionVerified:
            // Subsequent events (status_changed, step_ready, plan_updated, …)
            // will move us out of .verifying. No-op here keeps the spinner
            // honest until the next real signal arrives.
            break
        case .verificationHint(let stepID, let verdict, let reason, let autoReplanning):
            awaitingHintResponse = PendingVerificationHint(
                stepID: stepID,
                verdict: verdict,
                reason: reason,
                autoReplanning: autoReplanning
            )
        case .completionProposed(let reason, let source):
            let promptSource = PendingCompletionPrompt.Source(rawValue: source) ?? .backend
            pendingCompletionPrompt = PendingCompletionPrompt(
                reason: reason,
                source: promptSource
            )
            status = .awaitingCompletion
        case .assistantQuestion(let batchID, let reason, let questions):
            pendingQuestionBatch = PendingQuestionBatch(
                batchID: batchID,
                reason: reason,
                questions: questions
            )
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
        case "needs_answer":
            // The question card itself is the UI signal; the underlying
            // status stays "awaiting" so the composer/advance affordances
            // do not present as busy spinners.
            status = .awaitingConfirmation
        case "awaiting_confirmation":
            status = .awaitingConfirmation
        case "awaiting_completion":
            status = .awaitingCompletion
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
        Task { [weak self] in
            await self?.markStepStarted(stepID: stepID, actionIndex: actionIndex)
        }
        if let grounded = optimisticallyGroundedSlot,
           grounded.stepID == stepID,
           grounded.actionIndex == actionIndex {
            optimisticallyGroundedSlot = nil
            return
        }
        optimisticallyGroundedSlot = nil
        guard isGroundingAutoFireEnabled() else { return }
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
        let digest = SHA256.hash(data: screenJPEGData)
        lastFrameHash = digest.map { String(format: "%02x", $0) }.joined()
        return TutorialSessionScreenSnapshot(
            mimeType: "image/jpeg",
            dataBase64: screenJPEGData.base64EncodedString()
        )
    }

    func sendStepAnnotation(
        verdict: StepAnnotationVerdict,
        note: String? = nil,
        category: StepAnnotationCategory? = nil,
        corrections: StepAnnotationCorrections? = nil
    ) async {
        guard let stepID = currentStepID else { return }
        let actionIndex = currentActionIndex ?? 0
        do {
            try await sendSessionEvent(
                .userStepAnnotation(
                    stepID: stepID,
                    actionIndex: actionIndex,
                    frameHash: lastFrameHash,
                    verdict: verdict,
                    category: category,
                    note: note,
                    corrections: corrections
                )
            )
        } catch {
            logger.error("sendStepAnnotation failed: \(error.localizedDescription, privacy: .public)")
        }
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
