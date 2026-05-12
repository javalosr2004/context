import XCTest
@testable import ContextApp

final class GroundingEndpointStoreTests: XCTestCase {
    func testSavedEndpointOverridesEnvironmentEndpoint() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = GroundingEndpointStore(
            defaults: defaults,
            environment: ["CONTEXT_GROUNDING_ENDPOINT": "https://env.example/ground"]
        )

        store.save(" https://saved.example/ground ")

        XCTAssertEqual(store.endpoint, "https://saved.example/ground")
    }

    func testFallsBackToEnvironmentWhenSavedEndpointIsCleared() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = GroundingEndpointStore(
            defaults: defaults,
            environment: ["CONTEXT_GROUNDING_ENDPOINT": "https://env.example/ground"]
        )

        store.save("https://saved.example/ground")
        store.clearSavedEndpoint()

        XCTAssertEqual(store.endpoint, "https://env.example/ground")
    }

    func testEmptyEndpointIsTreatedAsMissing() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = GroundingEndpointStore(defaults: defaults, environment: [:])

        store.save("   ")

        XCTAssertNil(store.endpoint)
    }
}
