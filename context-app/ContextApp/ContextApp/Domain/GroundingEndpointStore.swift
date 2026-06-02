import Foundation

/// Resolves the visual-grounding endpoint URL.
///
/// Resolution order: saved override (UserDefaults) → env override → derived from
/// the shared `TutorialAPIEndpointStore` base URL with `/grounding` appended.
/// The override path is preserved so the user can point at a remote service
/// (e.g. Colab) without touching the proxy.
final class GroundingEndpointStore {
    private static let endpointKey = "debug.groundingEndpointURL"
    private static let derivedPath = "grounding"

    private let defaults: UserDefaults
    private let environment: [String: String]
    private let baseURLStore: TutorialAPIEndpointStore

    init(
        defaults: UserDefaults = .standard,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        baseURLStore: TutorialAPIEndpointStore = TutorialAPIEndpointStore()
    ) {
        self.defaults = defaults
        self.environment = environment
        self.baseURLStore = baseURLStore
    }

    var savedEndpoint: String? {
        normalized(defaults.string(forKey: Self.endpointKey))
    }

    var endpoint: String? {
        if let override = savedEndpoint ?? normalized(environment["CONTEXT_GROUNDING_ENDPOINT"]) {
            return override
        }
        return derivedEndpoint()
    }

    func save(_ endpoint: String) {
        defaults.set(endpoint.trimmingCharacters(in: .whitespacesAndNewlines), forKey: Self.endpointKey)
    }

    func clearSavedEndpoint() {
        defaults.removeObject(forKey: Self.endpointKey)
    }

    private func derivedEndpoint() -> String? {
        guard let base = baseURLStore.baseURL,
              let baseURL = URL(string: base),
              baseURL.scheme != nil else {
            return nil
        }
        return baseURL.appendingPathComponent(Self.derivedPath).absoluteString
    }

    private func normalized(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return nil
        }

        return trimmed
    }
}
