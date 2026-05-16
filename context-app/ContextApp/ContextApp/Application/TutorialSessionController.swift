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
    @Published private(set) var currentStepID: String?
    @Published private(set) var draftPlan: DraftPlan?
    @Published private(set) var messages: [ChatMessage]
    @Published private(set) var pendingContinuePromptStepID: String?
    @Published private(set) var status: TutorialSessionUIStatus = .ready

    private let capture: ScreenFrameCapture
    private let client: TutorialSessionAPIClient
    private let endpointStore: TutorialAPIEndpointStore
    private let fallbackPlanController: TutorialPlanController?
    private let ignoredWindowProvider: () -> [NSWindow]
    private let logger = Logger(subsystem: "ContextApp", category: "TutorialSession")
    private let messageStore: ChatMessageStore
    private let screenCaptureTimeoutNanoseconds: UInt64
    private let screenProvider: () -> NSScreen?

    private var tutorialActionHandler: ((TutorialStep) async -> String)?
    private var listenTask: Task<Void, Never>?
    private var sessionID: String?
    private var socket: URLSessionWebSocketTask?
    private var isStreamingTutorialText = false

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

    func markStepStarted(stepID: String) async {
        do {
            try await sendSessionEvent(.stepStarted(stepID: stepID))
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

    func confirmStep(stepID: String, confirmed: Bool, note: String?) async {
        pendingContinuePromptStepID = nil
        do {
            status = .sending
            try await sendSessionEvent(
                .userConfirmation(
                    stepID: stepID,
                    confirmed: confirmed,
                    note: note
                )
            )
            awaitingConfirmationStepID = nil
            status = confirmed ? .planning("Continuing") : .planning("Replanning from current screen")
        } catch {
            applyFailure("Could not confirm tutorial step: \(error.localizedDescription)")
        }
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
        awaitingConfirmationStepID = nil
        pendingContinuePromptStepID = nil
        draftPlan = nil
        status = .ready
        messageStore.removeAll()
        messages = messageStore.messages
    }

    func setTutorialActionHandler(_ handler: @escaping (TutorialStep) async -> String) {
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
        case .tutorialAction(let step):
            applyTutorialAction(step)
        case .stepReady(let stepID):
            currentStepID = stepID
            status = .ready
        case .awaitingConfirmation(let stepID):
            awaitingConfirmationStepID = stepID
            status = .awaitingConfirmation
        case .screenRequested(let requestID, let reason):
            handleScreenRequest(requestID: requestID, reason: reason)
        case .sessionCompleted:
            currentStepID = nil
            awaitingConfirmationStepID = nil
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

    private func applyTutorialAction(_ step: TutorialStep) {
        currentStepID = step.stepId
        guard let tutorialActionHandler else { return }
        Task { [weak self] in
            _ = await tutorialActionHandler(step)
            await MainActor.run {
                self?.status = .ready
            }
        }
    }

    private func applyFailure(_ message: String) {
        logger.error("\(message, privacy: .public)")
        appendTutorialText(message)
        status = .failed(message)
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
