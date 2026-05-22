import Foundation

enum TutorialSessionAPIClientError: LocalizedError {
    case invalidResponse
    case badStatusCode(Int, String)
    case decodingFailed(Error)
    case invalidWebSocketURL(URL)
    case unsupportedWebSocketMessage
    case unexpectedSocketReadyEvent
    case mismatchedSocketSession(expected: String, actual: String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "The tutorial session endpoint did not return an HTTP response."
        case .badStatusCode(let statusCode, let message):
            return "The tutorial session endpoint returned HTTP \(statusCode): \(message)"
        case .decodingFailed(let error):
            return "The tutorial session response could not be decoded: \(error.localizedDescription)"
        case .invalidWebSocketURL(let url):
            return "Could not create a WebSocket URL from \(url.absoluteString)."
        case .unsupportedWebSocketMessage:
            return "The tutorial session socket returned an unsupported message."
        case .unexpectedSocketReadyEvent:
            return "The tutorial session socket did not become ready."
        case .mismatchedSocketSession(let expected, let actual):
            return "The tutorial session socket became ready for \(actual), but expected \(expected)."
        }
    }
}

enum StepAnnotationVerdict: String, Codable, Equatable {
    case correct
    case offTrack = "off_track"
    case ambiguous
}

enum StepAnnotationCategory: String, Codable, Equatable {
    case plan
    case grounding
    case verifier
    case loop
}

/// How a user resolved a VerificationHintEvent toast.
enum TutorialHintResponseAction: String, Codable, Equatable {
    case acknowledgeOff = "acknowledge_off"
    case dismiss
    case timeout
}

/// Verifier verdict that triggered a VerificationHintEvent. `onTrack` is
/// included for completeness with the backend's 4-way verdict; only the
/// three negative verdicts are ever surfaced as a hint.
enum TutorialVerificationVerdict: String, Codable, Equatable {
    case onTrack = "on_track"
    case unsure
    case blocked
    case diverged
}

struct StepAnnotationCorrections: Codable, Equatable {
    let instruction: String?
    let targetBbox: [Double]?
    let verifierShouldHaveSaid: String?

    private enum CodingKeys: String, CodingKey {
        case instruction
        case targetBbox = "target_bbox"
        case verifierShouldHaveSaid = "verifier_should_have_said"
    }
}

struct TutorialSessionScreenSnapshot: Codable, Equatable {
    let mimeType: String
    let dataBase64: String

    private enum CodingKeys: String, CodingKey {
        case mimeType = "mime_type"
        case dataBase64 = "data_base64"
    }
}

struct CreateTutorialSessionResponse: Codable, Equatable {
    let sessionID: String
    let status: String

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case status
    }
}

enum TutorialSessionClientEvent: Codable, Equatable {
    case userMessage(text: String, uploadedImages: [TutorialSessionScreenSnapshot] = [])
    case stepStarted(stepID: String, actionIndex: Int)
    case userConfirmation(
        stepID: String,
        actionIndex: Int,
        confirmed: Bool,
        note: String?,
        screen: TutorialSessionScreenSnapshot? = nil
    )
    case userScreen(requestID: String, screen: TutorialSessionScreenSnapshot)
    case userCompletionResponse(confirmed: Bool, note: String?)
    case userAnswer(batchID: String, answers: [TutorialUserAnswer])
    case userStepAnnotation(
        stepID: String,
        actionIndex: Int,
        frameHash: String?,
        verdict: StepAnnotationVerdict,
        category: StepAnnotationCategory?,
        note: String?,
        corrections: StepAnnotationCorrections?
    )
    /// Response to a `VerificationHintEvent` toast.
    ///
    /// `action` is "acknowledge_off" (user confirmed off-track), "dismiss"
    /// (user explicitly closed the toast), or "timeout" (toast auto-dismissed
    /// with no interaction). Backend resolves the open hint per verdict —
    /// see backend/tutorial_session.handle_user_hint_response.
    case userHintResponse(stepID: String, action: TutorialHintResponseAction)

    private enum CodingKeys: String, CodingKey {
        case type
        case text
        case uploadedImages = "uploaded_images"
        case screen
        case stepID = "step_id"
        case actionIndex = "action_index"
        case requestID = "request_id"
        case confirmed
        case note
        case frameHash = "frame_hash"
        case verdict
        case category
        case corrections
        case batchID = "batch_id"
        case answers
        case action
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)

        switch type {
        case "user_message":
            self = .userMessage(
                text: try container.decode(String.self, forKey: .text),
                uploadedImages: try container.decodeIfPresent(
                    [TutorialSessionScreenSnapshot].self,
                    forKey: .uploadedImages
                ) ?? []
            )
        case "step_started":
            self = .stepStarted(
                stepID: try container.decode(String.self, forKey: .stepID),
                actionIndex: try container.decode(Int.self, forKey: .actionIndex)
            )
        case "user_confirmation":
            self = .userConfirmation(
                stepID: try container.decode(String.self, forKey: .stepID),
                actionIndex: try container.decode(Int.self, forKey: .actionIndex),
                confirmed: try container.decode(Bool.self, forKey: .confirmed),
                note: try container.decodeIfPresent(String.self, forKey: .note),
                screen: try container.decodeIfPresent(
                    TutorialSessionScreenSnapshot.self,
                    forKey: .screen
                )
            )
        case "user_screen":
            self = .userScreen(
                requestID: try container.decode(String.self, forKey: .requestID),
                screen: try container.decode(TutorialSessionScreenSnapshot.self, forKey: .screen)
            )
        case "user_completion_response":
            self = .userCompletionResponse(
                confirmed: try container.decode(Bool.self, forKey: .confirmed),
                note: try container.decodeIfPresent(String.self, forKey: .note)
            )
        case "user_answer":
            self = .userAnswer(
                batchID: try container.decode(String.self, forKey: .batchID),
                answers: try container.decode([TutorialUserAnswer].self, forKey: .answers)
            )
        case "user_step_annotation":
            self = .userStepAnnotation(
                stepID: try container.decode(String.self, forKey: .stepID),
                actionIndex: try container.decode(Int.self, forKey: .actionIndex),
                frameHash: try container.decodeIfPresent(String.self, forKey: .frameHash),
                verdict: try container.decode(StepAnnotationVerdict.self, forKey: .verdict),
                category: try container.decodeIfPresent(StepAnnotationCategory.self, forKey: .category),
                note: try container.decodeIfPresent(String.self, forKey: .note),
                corrections: try container.decodeIfPresent(StepAnnotationCorrections.self, forKey: .corrections)
            )
        case "user_hint_response":
            self = .userHintResponse(
                stepID: try container.decode(String.self, forKey: .stepID),
                action: try container.decode(TutorialHintResponseAction.self, forKey: .action)
            )
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .type,
                in: container,
                debugDescription: "Unknown tutorial session client event type '\(type)'."
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)

        switch self {
        case .userMessage(let text, let uploadedImages):
            try container.encode("user_message", forKey: .type)
            try container.encode(text, forKey: .text)
            if !uploadedImages.isEmpty {
                try container.encode(uploadedImages, forKey: .uploadedImages)
            }
        case .stepStarted(let stepID, let actionIndex):
            try container.encode("step_started", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(actionIndex, forKey: .actionIndex)
        case .userConfirmation(let stepID, let actionIndex, let confirmed, let note, let screen):
            try container.encode("user_confirmation", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(actionIndex, forKey: .actionIndex)
            try container.encode(confirmed, forKey: .confirmed)
            try container.encodeIfPresent(note, forKey: .note)
            try container.encodeIfPresent(screen, forKey: .screen)
        case .userScreen(let requestID, let screen):
            try container.encode("user_screen", forKey: .type)
            try container.encode(requestID, forKey: .requestID)
            try container.encode(screen, forKey: .screen)
        case .userCompletionResponse(let confirmed, let note):
            try container.encode("user_completion_response", forKey: .type)
            try container.encode(confirmed, forKey: .confirmed)
            try container.encodeIfPresent(note, forKey: .note)
        case .userAnswer(let batchID, let answers):
            try container.encode("user_answer", forKey: .type)
            try container.encode(batchID, forKey: .batchID)
            try container.encode(answers, forKey: .answers)
        case .userStepAnnotation(let stepID, let actionIndex, let frameHash, let verdict, let category, let note, let corrections):
            try container.encode("user_step_annotation", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(actionIndex, forKey: .actionIndex)
            try container.encodeIfPresent(frameHash, forKey: .frameHash)
            try container.encode(verdict, forKey: .verdict)
            try container.encodeIfPresent(category, forKey: .category)
            try container.encodeIfPresent(note, forKey: .note)
            try container.encodeIfPresent(corrections, forKey: .corrections)
        case .userHintResponse(let stepID, let action):
            try container.encode("user_hint_response", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(action, forKey: .action)
        }
    }
}

struct TutorialSessionWebSource: Codable, Equatable {
    let title: String
    let url: String
}

enum TutorialAssistantQuestionResponseMode: String, Codable, Equatable {
    case options
    case freeText = "free_text"
}

struct TutorialAssistantQuestion: Codable, Equatable, Identifiable {
    let questionID: String
    let prompt: String
    let responseMode: TutorialAssistantQuestionResponseMode
    let options: [String]
    let allowsCustomAnswer: Bool

    var id: String { questionID }

    private enum CodingKeys: String, CodingKey {
        case questionID = "question_id"
        case prompt
        case responseMode = "response_mode"
        case options
        case allowsCustomAnswer = "allows_custom_answer"
    }
}

struct TutorialUserAnswer: Codable, Equatable {
    let questionID: String
    let text: String

    private enum CodingKeys: String, CodingKey {
        case questionID = "question_id"
        case text
    }
}

enum TutorialSessionServerEvent: Codable, Equatable {
    case sessionReady(sessionID: String)
    case statusChanged(status: String, label: String)
    case textDelta(String)
    case textResponse(String)
    case planReady(TutorialPlan)
    case planUpdated(TutorialPlan)
    case draftPlanReady(DraftPlan)
    case tutorialAction(TutorialStep)
    case unknown(type: String)
    case stepReady(stepID: String, actionIndex: Int)
    case awaitingConfirmation(stepID: String, actionIndex: Int)
    case screenRequested(requestID: String, reason: String)
    case webSearchStarted(query: String)
    case webSearchCompleted(query: String, sourceCount: Int, sources: [TutorialSessionWebSource], elapsedMs: Double)
    case agentTurn(turn: Int, maxTurns: Int)
    case planDiff(frozenPrefixLen: Int, newTailLen: Int, refinedCurrent: Bool, totalSteps: Int)
    case stepProgress(stepID: String, stepIndex: Int, totalSteps: Int, actionIndex: Int, totalActions: Int)
    case sessionCompleted
    case completionProposed(reason: String, source: String)
    case assistantQuestion(batchID: String, reason: String, questions: [TutorialAssistantQuestion])
    case instructionVerificationStarted(stepID: String)
    case instructionVerified(stepID: String, ok: Bool, reason: String?)
    /// Soft toast emitted on any negative verifier verdict. `autoReplanning`
    /// tells the overlay whether the backend has already staged a replan
    /// that will fire on toast timeout (true for diverged/blocked; false
    /// for unsure — those need explicit user acknowledgement to replan).
    case verificationHint(stepID: String, verdict: TutorialVerificationVerdict, reason: String, autoReplanning: Bool)
    case error(code: String, message: String)

    private enum CodingKeys: String, CodingKey {
        case type
        case sessionID = "session_id"
        case status
        case label
        case plan
        case step
        case text
        case stepID = "step_id"
        case actionIndex = "action_index"
        case requestID = "request_id"
        case reason
        case source
        case code
        case message
        case query
        case sourceCount = "source_count"
        case sources
        case elapsedMs = "elapsed_ms"
        case turn
        case maxTurns = "max_turns"
        case frozenPrefixLen = "frozen_prefix_len"
        case newTailLen = "new_tail_len"
        case refinedCurrent = "refined_current"
        case totalSteps = "total_steps"
        case stepIndex = "step_index"
        case totalActions = "total_actions"
        case ok
        case batchID = "batch_id"
        case questions
        case verdict
        case autoReplanning = "auto_replanning"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)

        switch type {
        case "session_ready":
            self = .sessionReady(sessionID: try container.decode(String.self, forKey: .sessionID))
        case "status_changed":
            self = .statusChanged(
                status: try container.decode(String.self, forKey: .status),
                label: try container.decode(String.self, forKey: .label)
            )
        case "tutorial_text_delta":
            self = .textDelta(try container.decode(String.self, forKey: .text))
        case "text_response":
            self = .textResponse(try container.decode(String.self, forKey: .text))
        case "plan_ready":
            self = .planReady(try container.decode(TutorialPlan.self, forKey: .plan))
        case "plan_updated":
            self = .planUpdated(try container.decode(TutorialPlan.self, forKey: .plan))
        case "draft_plan_ready":
            self = .draftPlanReady(try container.decode(DraftPlan.self, forKey: .plan))
        case "tutorial_action":
            self = .tutorialAction(try container.decode(TutorialStep.self, forKey: .step))
        case "step_ready":
            self = .stepReady(
                stepID: try container.decode(String.self, forKey: .stepID),
                actionIndex: try container.decode(Int.self, forKey: .actionIndex)
            )
        case "awaiting_confirmation":
            self = .awaitingConfirmation(
                stepID: try container.decode(String.self, forKey: .stepID),
                actionIndex: try container.decode(Int.self, forKey: .actionIndex)
            )
        case "screen_requested":
            self = .screenRequested(
                requestID: try container.decode(String.self, forKey: .requestID),
                reason: try container.decode(String.self, forKey: .reason)
            )
        case "web_search_started":
            self = .webSearchStarted(query: try container.decode(String.self, forKey: .query))
        case "web_search_completed":
            self = .webSearchCompleted(
                query: try container.decode(String.self, forKey: .query),
                sourceCount: try container.decode(Int.self, forKey: .sourceCount),
                sources: try container.decodeIfPresent([TutorialSessionWebSource].self, forKey: .sources) ?? [],
                elapsedMs: try container.decode(Double.self, forKey: .elapsedMs)
            )
        case "agent_turn":
            self = .agentTurn(
                turn: try container.decode(Int.self, forKey: .turn),
                maxTurns: try container.decode(Int.self, forKey: .maxTurns)
            )
        case "plan_diff":
            self = .planDiff(
                frozenPrefixLen: try container.decode(Int.self, forKey: .frozenPrefixLen),
                newTailLen: try container.decode(Int.self, forKey: .newTailLen),
                refinedCurrent: try container.decode(Bool.self, forKey: .refinedCurrent),
                totalSteps: try container.decode(Int.self, forKey: .totalSteps)
            )
        case "step_progress":
            self = .stepProgress(
                stepID: try container.decode(String.self, forKey: .stepID),
                stepIndex: try container.decode(Int.self, forKey: .stepIndex),
                totalSteps: try container.decode(Int.self, forKey: .totalSteps),
                actionIndex: try container.decode(Int.self, forKey: .actionIndex),
                totalActions: try container.decode(Int.self, forKey: .totalActions)
            )
        case "session_completed":
            self = .sessionCompleted
        case "completion_proposed":
            self = .completionProposed(
                reason: try container.decode(String.self, forKey: .reason),
                source: try container.decode(String.self, forKey: .source)
            )
        case "assistant_question":
            self = .assistantQuestion(
                batchID: try container.decode(String.self, forKey: .batchID),
                reason: try container.decode(String.self, forKey: .reason),
                questions: try container.decode([TutorialAssistantQuestion].self, forKey: .questions)
            )
        case "instruction_verification_started":
            self = .instructionVerificationStarted(
                stepID: try container.decode(String.self, forKey: .stepID)
            )
        case "instruction_verified":
            self = .instructionVerified(
                stepID: try container.decode(String.self, forKey: .stepID),
                ok: try container.decode(Bool.self, forKey: .ok),
                reason: try container.decodeIfPresent(String.self, forKey: .reason)
            )
        case "verification_hint":
            self = .verificationHint(
                stepID: try container.decode(String.self, forKey: .stepID),
                verdict: try container.decode(TutorialVerificationVerdict.self, forKey: .verdict),
                reason: try container.decode(String.self, forKey: .reason),
                autoReplanning: try container.decode(Bool.self, forKey: .autoReplanning)
            )
        case "error":
            self = .error(
                code: try container.decode(String.self, forKey: .code),
                message: try container.decode(String.self, forKey: .message)
            )
        default:
            self = .unknown(type: type)
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)

        switch self {
        case .sessionReady(let sessionID):
            try container.encode("session_ready", forKey: .type)
            try container.encode(sessionID, forKey: .sessionID)
        case .statusChanged(let status, let label):
            try container.encode("status_changed", forKey: .type)
            try container.encode(status, forKey: .status)
            try container.encode(label, forKey: .label)
        case .textDelta(let text):
            try container.encode("tutorial_text_delta", forKey: .type)
            try container.encode(text, forKey: .text)
        case .textResponse(let text):
            try container.encode("text_response", forKey: .type)
            try container.encode(text, forKey: .text)
        case .planReady(let plan):
            try container.encode("plan_ready", forKey: .type)
            try container.encode(plan, forKey: .plan)
        case .planUpdated(let plan):
            try container.encode("plan_updated", forKey: .type)
            try container.encode(plan, forKey: .plan)
        case .draftPlanReady(let plan):
            try container.encode("draft_plan_ready", forKey: .type)
            try container.encode(plan, forKey: .plan)
        case .unknown(let type):
            try container.encode(type, forKey: .type)
        case .tutorialAction(let step):
            try container.encode("tutorial_action", forKey: .type)
            try container.encode(step, forKey: .step)
        case .stepReady(let stepID, let actionIndex):
            try container.encode("step_ready", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(actionIndex, forKey: .actionIndex)
        case .awaitingConfirmation(let stepID, let actionIndex):
            try container.encode("awaiting_confirmation", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(actionIndex, forKey: .actionIndex)
        case .screenRequested(let requestID, let reason):
            try container.encode("screen_requested", forKey: .type)
            try container.encode(requestID, forKey: .requestID)
            try container.encode(reason, forKey: .reason)
        case .webSearchStarted(let query):
            try container.encode("web_search_started", forKey: .type)
            try container.encode(query, forKey: .query)
        case .webSearchCompleted(let query, let sourceCount, let sources, let elapsedMs):
            try container.encode("web_search_completed", forKey: .type)
            try container.encode(query, forKey: .query)
            try container.encode(sourceCount, forKey: .sourceCount)
            try container.encode(sources, forKey: .sources)
            try container.encode(elapsedMs, forKey: .elapsedMs)
        case .agentTurn(let turn, let maxTurns):
            try container.encode("agent_turn", forKey: .type)
            try container.encode(turn, forKey: .turn)
            try container.encode(maxTurns, forKey: .maxTurns)
        case .planDiff(let frozenPrefixLen, let newTailLen, let refinedCurrent, let totalSteps):
            try container.encode("plan_diff", forKey: .type)
            try container.encode(frozenPrefixLen, forKey: .frozenPrefixLen)
            try container.encode(newTailLen, forKey: .newTailLen)
            try container.encode(refinedCurrent, forKey: .refinedCurrent)
            try container.encode(totalSteps, forKey: .totalSteps)
        case .stepProgress(let stepID, let stepIndex, let totalSteps, let actionIndex, let totalActions):
            try container.encode("step_progress", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(stepIndex, forKey: .stepIndex)
            try container.encode(totalSteps, forKey: .totalSteps)
            try container.encode(actionIndex, forKey: .actionIndex)
            try container.encode(totalActions, forKey: .totalActions)
        case .sessionCompleted:
            try container.encode("session_completed", forKey: .type)
        case .completionProposed(let reason, let source):
            try container.encode("completion_proposed", forKey: .type)
            try container.encode(reason, forKey: .reason)
            try container.encode(source, forKey: .source)
        case .assistantQuestion(let batchID, let reason, let questions):
            try container.encode("assistant_question", forKey: .type)
            try container.encode(batchID, forKey: .batchID)
            try container.encode(reason, forKey: .reason)
            try container.encode(questions, forKey: .questions)
        case .instructionVerificationStarted(let stepID):
            try container.encode("instruction_verification_started", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
        case .instructionVerified(let stepID, let ok, let reason):
            try container.encode("instruction_verified", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(ok, forKey: .ok)
            try container.encodeIfPresent(reason, forKey: .reason)
        case .verificationHint(let stepID, let verdict, let reason, let autoReplanning):
            try container.encode("verification_hint", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(verdict, forKey: .verdict)
            try container.encode(reason, forKey: .reason)
            try container.encode(autoReplanning, forKey: .autoReplanning)
        case .error(let code, let message):
            try container.encode("error", forKey: .type)
            try container.encode(code, forKey: .code)
            try container.encode(message, forKey: .message)
        }
    }
}

final class TutorialSessionAPIClient {
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func createSession(baseURL: URL) async throws -> CreateTutorialSessionResponse {
        var request = URLRequest(url: Self.sessionURL(from: baseURL))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw TutorialSessionAPIClientError.invalidResponse
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "<non-utf8 \(data.count) bytes>"
            throw TutorialSessionAPIClientError.badStatusCode(httpResponse.statusCode, message)
        }

        do {
            return try decoder.decode(CreateTutorialSessionResponse.self, from: data)
        } catch {
            throw TutorialSessionAPIClientError.decodingFailed(error)
        }
    }

    func openSocket(baseURL: URL, sessionID: String) throws -> URLSessionWebSocketTask {
        let task = session.webSocketTask(with: try Self.socketURL(from: baseURL, sessionID: sessionID))
        task.resume()
        return task
    }

    func waitUntilReady(on socket: URLSessionWebSocketTask, sessionID: String) async throws {
        let event = try await receive(from: socket)
        guard case .sessionReady(let readySessionID) = event else {
            throw TutorialSessionAPIClientError.unexpectedSocketReadyEvent
        }
        guard readySessionID == sessionID else {
            throw TutorialSessionAPIClientError.mismatchedSocketSession(
                expected: sessionID,
                actual: readySessionID
            )
        }
    }

    func send(_ event: TutorialSessionClientEvent, on socket: URLSessionWebSocketTask) async throws {
        let data = try encoder.encode(event)
        try await socket.send(.data(data))
    }

    func receive(from socket: URLSessionWebSocketTask) async throws -> TutorialSessionServerEvent {
        let message = try await socket.receive()
        let data: Data

        switch message {
        case .data(let payload):
            data = payload
        case .string(let payload):
            data = Data(payload.utf8)
        @unknown default:
            throw TutorialSessionAPIClientError.unsupportedWebSocketMessage
        }

        let rawPayload = String(data: data, encoding: .utf8) ?? "<non-utf8 \(data.count) bytes>"
        print("[TutorialSessionAPIClient] received: \(rawPayload)")

        do {
            return try decoder.decode(TutorialSessionServerEvent.self, from: data)
        } catch {
            throw TutorialSessionAPIClientError.decodingFailed(error)
        }
    }

    static func sessionURL(from baseURL: URL) -> URL {
        baseURL.appendingPathComponent("tutorial-sessions")
    }

    static func socketURL(from baseURL: URL, sessionID: String) throws -> URL {
        let httpURL = sessionURL(from: baseURL)
            .appendingPathComponent(sessionID)
            .appendingPathComponent("socket")
        guard var components = URLComponents(url: httpURL, resolvingAgainstBaseURL: false) else {
            throw TutorialSessionAPIClientError.invalidWebSocketURL(httpURL)
        }

        switch components.scheme {
        case "http":
            components.scheme = "ws"
        case "https":
            components.scheme = "wss"
        default:
            throw TutorialSessionAPIClientError.invalidWebSocketURL(httpURL)
        }

        guard let url = components.url else {
            throw TutorialSessionAPIClientError.invalidWebSocketURL(httpURL)
        }
        return url
    }
}
