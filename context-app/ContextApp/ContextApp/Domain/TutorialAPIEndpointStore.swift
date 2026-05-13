import Foundation

final class TutorialAPIEndpointStore {
    private static let baseURLKey = "tutorial.apiBaseURL"
    private let defaults: UserDefaults
    private let environment: [String: String]

    init(
        defaults: UserDefaults = .standard,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) {
        self.defaults = defaults
        self.environment = environment
    }

    var savedBaseURL: String? {
        normalized(defaults.string(forKey: Self.baseURLKey))
    }

    var baseURL: String? {
        savedBaseURL ?? normalized(environment["CONTEXT_TUTORIAL_API_BASE_URL"])
    }

    func save(_ baseURL: String) {
        defaults.set(baseURL.trimmingCharacters(in: .whitespacesAndNewlines), forKey: Self.baseURLKey)
    }

    func clearSavedBaseURL() {
        defaults.removeObject(forKey: Self.baseURLKey)
    }

    func planURL() throws -> URL {
        guard let baseURL else {
            throw TutorialAPIEndpointStoreError.missingBaseURL
        }

        guard let url = URL(string: baseURL), url.scheme != nil else {
            throw TutorialAPIEndpointStoreError.invalidBaseURL(baseURL)
        }

        return url.appendingPathComponent("tutorials/plan")
    }

    private func normalized(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return nil
        }

        return trimmed
    }
}

enum TutorialAPIEndpointStoreError: LocalizedError {
    case missingBaseURL
    case invalidBaseURL(String)

    var errorDescription: String? {
        switch self {
        case .missingBaseURL:
            return "Set the tutorial API base URL in Context Settings before sending a message."
        case .invalidBaseURL(let value):
            return "The tutorial API base URL is not a valid URL: \(value)"
        }
    }
}
