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
    case userMessage(text: String)
    case stepStarted(stepID: String)
    case userConfirmation(stepID: String, confirmed: Bool, note: String?)
    case userScreen(requestID: String, screen: TutorialSessionScreenSnapshot)

    private enum CodingKeys: String, CodingKey {
        case type
        case text
        case screen
        case stepID = "step_id"
        case requestID = "request_id"
        case confirmed
        case note
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)

        switch type {
        case "user_message":
            self = .userMessage(text: try container.decode(String.self, forKey: .text))
        case "step_started":
            self = .stepStarted(stepID: try container.decode(String.self, forKey: .stepID))
        case "user_confirmation":
            self = .userConfirmation(
                stepID: try container.decode(String.self, forKey: .stepID),
                confirmed: try container.decode(Bool.self, forKey: .confirmed),
                note: try container.decodeIfPresent(String.self, forKey: .note)
            )
        case "user_screen":
            self = .userScreen(
                requestID: try container.decode(String.self, forKey: .requestID),
                screen: try container.decode(TutorialSessionScreenSnapshot.self, forKey: .screen)
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
        case .userMessage(let text):
            try container.encode("user_message", forKey: .type)
            try container.encode(text, forKey: .text)
        case .stepStarted(let stepID):
            try container.encode("step_started", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
        case .userConfirmation(let stepID, let confirmed, let note):
            try container.encode("user_confirmation", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
            try container.encode(confirmed, forKey: .confirmed)
            try container.encodeIfPresent(note, forKey: .note)
        case .userScreen(let requestID, let screen):
            try container.encode("user_screen", forKey: .type)
            try container.encode(requestID, forKey: .requestID)
            try container.encode(screen, forKey: .screen)
        }
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
    case stepReady(stepID: String)
    case awaitingConfirmation(stepID: String)
    case screenRequested(requestID: String, reason: String)
    case sessionCompleted
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
        case requestID = "request_id"
        case reason
        case code
        case message
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
            self = .stepReady(stepID: try container.decode(String.self, forKey: .stepID))
        case "awaiting_confirmation":
            self = .awaitingConfirmation(stepID: try container.decode(String.self, forKey: .stepID))
        case "screen_requested":
            self = .screenRequested(
                requestID: try container.decode(String.self, forKey: .requestID),
                reason: try container.decode(String.self, forKey: .reason)
            )
        case "session_completed":
            self = .sessionCompleted
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
        case .stepReady(let stepID):
            try container.encode("step_ready", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
        case .awaitingConfirmation(let stepID):
            try container.encode("awaiting_confirmation", forKey: .type)
            try container.encode(stepID, forKey: .stepID)
        case .screenRequested(let requestID, let reason):
            try container.encode("screen_requested", forKey: .type)
            try container.encode(requestID, forKey: .requestID)
            try container.encode(reason, forKey: .reason)
        case .sessionCompleted:
            try container.encode("session_completed", forKey: .type)
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
