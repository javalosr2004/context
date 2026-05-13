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

final class TutorialPlanAPIClient {
    func fetchTutorialPlan(from url: URL) async throws -> TutorialPlan {
        let (data, response) = try await URLSession.shared.data(from: url)

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
}

enum TutorialPlanUsageExample {
    static func run() async throws {
        let url = URL(string: "https://example.com/tutorial-plan")!
        let client = TutorialPlanAPIClient()
        let consumer = TutorialActionConsumer()
        let plan = try await client.fetchTutorialPlan(from: url)

        for step in plan.steps {
            consumer.consume(step: step)
        }
    }
}
