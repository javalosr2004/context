import Foundation

struct GroundingInstruction {
    let text: String
    let referenceImageData: Data?
}

enum GroundingClientError: LocalizedError {
    case missingEndpoint
    case invalidEndpoint(String)
    case invalidResponse
    case requestFailed(Int)

    var errorDescription: String? {
        switch self {
        case .missingEndpoint:
            return "Set CONTEXT_GROUNDING_ENDPOINT before sending an instruction."
        case .invalidEndpoint(let value):
            return "CONTEXT_GROUNDING_ENDPOINT is not a valid URL: \(value)"
        case .invalidResponse:
            return "The grounding endpoint did not return an HTTP response."
        case .requestFailed(let statusCode):
            return "The grounding endpoint returned HTTP \(statusCode)."
        }
    }
}

final class GroundingClient {
    private struct Payload: Encodable {
        let instruction: String
        let screenshot_png_base64: String
        let reference_image_base64: String?
    }

    private let endpoint: URL
    private let session: URLSession

    init(endpoint: URL, session: URLSession = .shared) {
        self.endpoint = endpoint
        self.session = session
    }

    static func fromEnvironment(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> GroundingClient {
        guard let value = environment["CONTEXT_GROUNDING_ENDPOINT"], !value.isEmpty else {
            throw GroundingClientError.missingEndpoint
        }

        guard let url = URL(string: value), url.scheme != nil else {
            throw GroundingClientError.invalidEndpoint(value)
        }

        return GroundingClient(endpoint: url)
    }

    func locate(instruction: GroundingInstruction, screenshotPNGData: Data) async throws -> GroundingBoundingBox {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let payload = Payload(
            instruction: instruction.text,
            screenshot_png_base64: screenshotPNGData.base64EncodedString(),
            reference_image_base64: instruction.referenceImageData?.base64EncodedString()
        )
        let requestBody = try JSONEncoder().encode(payload)
        let (data, response) = try await session.upload(for: request, from: requestBody)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw GroundingClientError.invalidResponse
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            throw GroundingClientError.requestFailed(httpResponse.statusCode)
        }

        return try JSONDecoder().decode(GroundingResponse.self, from: data).boundingBox
    }
}
