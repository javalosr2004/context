import Foundation

final class WebGroundingEndpointStore {
    private static let endpointKey = "debug.webGroundingEndpointURL"
    private let defaults: UserDefaults
    private let environment: [String: String]

    init(
        defaults: UserDefaults = .standard,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) {
        self.defaults = defaults
        self.environment = environment
    }

    var savedEndpoint: String? {
        normalized(defaults.string(forKey: Self.endpointKey))
    }

    var endpoint: String? {
        savedEndpoint ?? normalized(environment["CONTEXT_WEB_GROUNDING_ENDPOINT"])
    }

    func save(_ endpoint: String) {
        defaults.set(endpoint.trimmingCharacters(in: .whitespacesAndNewlines), forKey: Self.endpointKey)
    }

    func clearSavedEndpoint() {
        defaults.removeObject(forKey: Self.endpointKey)
    }

    private func normalized(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return nil
        }

        return trimmed
    }
}
