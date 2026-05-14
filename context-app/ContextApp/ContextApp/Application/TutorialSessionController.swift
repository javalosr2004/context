import AppKit
import Combine
import Dispatch
import Foundation
import OSLog

struct TutorialSessionQuestion: Equatable {
    let questionID: String
    let prompt: String
}

enum TutorialSessionUIStatus: Equatable {
    case ready
    case preparingScreen
    case sending
    case requestReceived
    case planning(String)
    case needsContext
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
        case .requestReceived:
            return "Request received"
        case .planning(let label):
            return label
        case .needsContext:
            return "Needs context"
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
        case .preparingScreen, .sending, .requestReceived, .planning:
            return true
        case .ready, .needsContext, .awaitingConfirmation, .completed, .failed:
            return false
        }
    }
}

@MainActor
final class TutorialSessionController: ObservableObject {
    @Published private(set) var awaitingConfirmationStepID: String?
    @Published private(set) var currentStepID: String?
    @Published private(set) var messages: [ChatMessage]
    @Published private(set) var pendingQuestion: TutorialSessionQuestion?
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

    private var listenTask: Task<Void, Never>?
    private var sessionID: String?
    private var socket: URLSessionWebSocketTask?

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

        if let pendingQuestion {
            await sendAnswer(trimmedText, question: pendingQuestion)
            return
        }

        await sendUserMessage(trimmedText)
    }

    func markStepStarted(stepID: String) async {
        do {
            let socket = try await connectedSocket()
            try await client.send(.stepStarted(stepID: stepID), on: socket)
        } catch {
            applyFailure("Could not start tutorial step: \(error.localizedDescription)")
        }
    }

    func confirmStep(stepID: String, confirmed: Bool, note: String?) async {
        do {
            status = confirmed ? .sending : .preparingScreen
            let screen = confirmed ? nil : try await captureScreenSnapshot()
            let socket = try await connectedSocket()
            status = .sending
            try await client.send(
                .userConfirmation(
                    stepID: stepID,
                    confirmed: confirmed,
                    note: note,
                    screen: screen
                ),
                on: socket
            )
            awaitingConfirmationStepID = nil
            status = confirmed ? .requestReceived : .planning("Replanning from current screen")
        } catch {
            applyFailure("Could not confirm tutorial step: \(error.localizedDescription)")
        }
    }

    func appendTutorialText(_ text: String) {
        guard messageStore.appendTutorialText(text) != nil else { return }
        messages = messageStore.messages
    }

    func appendUserText(_ text: String) {
        guard messageStore.appendUserText(text) != nil else { return }
        messages = messageStore.messages
    }

    func stop() {
        clearSocket()
    }

    private func sendUserMessage(_ text: String) async {
        appendUserText(text)

        do {
            status = .preparingScreen
            let screen = try await captureScreenSnapshot()
            let socket = try await connectedSocket()
            status = .sending
            try await client.send(.userMessage(text: text, screen: screen), on: socket)
        } catch {
            await runFallbackPlanIfAvailable(text: text, originalError: error)
        }
    }

    private func sendAnswer(_ text: String, question: TutorialSessionQuestion) async {
        appendUserText(text)

        do {
            status = .preparingScreen
            let screen = try await captureScreenSnapshot()
            let socket = try await connectedSocket()
            pendingQuestion = nil
            status = .sending
            try await client.send(
                .userAnswer(
                    questionID: question.questionID,
                    text: text,
                    screen: screen
                ),
                on: socket
            )
        } catch {
            applyFailure("Could not send answer: \(error.localizedDescription)")
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
        if let socket, socket.closeCode == .invalid {
            return socket
        }
        clearSocket()

        guard let baseURL = endpointStore.baseURL.flatMap(URL.init(string:)) else {
            throw TutorialAPIEndpointStoreError.missingBaseURL
        }

        let createdSession = try await client.createSession(baseURL: baseURL)
        let newSocket = try client.openSocket(baseURL: baseURL, sessionID: createdSession.sessionID)
        sessionID = createdSession.sessionID
        socket = newSocket
        startListening(on: newSocket)
        return newSocket
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
                    self.clearSocket()
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

    private func apply(_ event: TutorialSessionServerEvent) {
        switch event {
        case .sessionReady:
            status = .ready
        case .requestReceived:
            status = .requestReceived
        case .statusChanged(let rawStatus, let label):
            applyStatus(rawStatus, label: label)
        case .assistantQuestion(let questionID, let prompt):
            pendingQuestion = TutorialSessionQuestion(questionID: questionID, prompt: prompt)
            appendTutorialText(prompt)
            status = .needsContext
        case .planReady(let plan):
            pendingQuestion = nil
            appendTutorialPlan(plan)
            status = .ready
        case .planUpdated(let plan):
            pendingQuestion = nil
            appendTutorialPlan(plan)
            status = .ready
        case .stepReady(let stepID):
            currentStepID = stepID
            status = .ready
        case .awaitingConfirmation(let stepID):
            awaitingConfirmationStepID = stepID
            status = .awaitingConfirmation
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
        case "planning":
            status = .planning(label)
        case "needs_context":
            status = .needsContext
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
