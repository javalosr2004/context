import Foundation

enum TutorialPlanAPIClientError: LocalizedError {
    case invalidResponse
    case badStatusCode(Int, String)
    case decodingFailed(Error)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "The tutorial plan endpoint did not return an HTTP response."
        case .badStatusCode(let statusCode, let message):
            return "The tutorial plan endpoint returned HTTP \(statusCode): \(message)"
        case .decodingFailed(let error):
            return "The tutorial plan response could not be decoded: \(error.localizedDescription)"
        }
    }
}

struct TutorialPlanSubmission {
    let conversationID: String
    let text: String
    let screenJPEGData: Data
}

final class TutorialPlanAPIClient {
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func createTutorialPlan(baseURL: URL, submission: TutorialPlanSubmission) async throws -> TutorialPlan {
        let requestData = Self.planRequestData(baseURL: baseURL, submission: submission)
        let (data, response) = try await session.upload(for: requestData.request, from: requestData.body)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw TutorialPlanAPIClientError.invalidResponse
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "<non-utf8 \(data.count) bytes>"
            throw TutorialPlanAPIClientError.badStatusCode(httpResponse.statusCode, message)
        }

        do {
            return try JSONDecoder().decode(TutorialPlan.self, from: data)
        } catch {
            throw TutorialPlanAPIClientError.decodingFailed(error)
        }
    }

    static func planURL(from baseURL: URL) -> URL {
        baseURL.appendingPathComponent("tutorials/plan")
    }

    static func planRequestData(
        baseURL: URL,
        submission: TutorialPlanSubmission,
        boundary: String = "Boundary-\(UUID().uuidString)"
    ) -> (request: URLRequest, body: Data) {
        var request = URLRequest(url: planURL(from: baseURL))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let body = multipartBody(
            boundary: boundary,
            submission: submission
        )
        return (request, body)
    }

    private static func multipartBody(
        boundary: String,
        submission: TutorialPlanSubmission
    ) -> Data {
        var body = Data()
        appendField("conversation_id", submission.conversationID, boundary: boundary, body: &body)
        appendField("text", submission.text, boundary: boundary, body: &body)
        appendFile(
            name: "images",
            filename: "screen.jpg",
            data: submission.screenJPEGData,
            boundary: boundary,
            body: &body
        )
        append("--\(boundary)--\r\n", to: &body)
        return body
    }

    private static func appendField(
        _ name: String,
        _ value: String,
        boundary: String,
        body: inout Data
    ) {
        append("--\(boundary)\r\n", to: &body)
        append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n", to: &body)
        append("\(value)\r\n", to: &body)
    }

    private static func appendFile(
        name: String,
        filename: String,
        data: Data,
        boundary: String,
        body: inout Data
    ) {
        append("--\(boundary)\r\n", to: &body)
        append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n", to: &body)
        append("Content-Type: image/jpeg\r\n\r\n", to: &body)
        body.append(data)
        append("\r\n", to: &body)
    }

    private static func append(_ string: String, to data: inout Data) {
        if let encoded = string.data(using: .utf8) {
            data.append(encoded)
        }
    }
}
