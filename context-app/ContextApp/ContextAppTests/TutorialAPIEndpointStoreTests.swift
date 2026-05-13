import XCTest
@testable import ContextApp

final class TutorialAPIEndpointStoreTests: XCTestCase {
    func testSavedBaseURLOverridesEnvironmentBaseURL() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = TutorialAPIEndpointStore(
            defaults: defaults,
            environment: ["CONTEXT_TUTORIAL_API_BASE_URL": "https://env.example"]
        )

        store.save(" https://saved.example ")

        XCTAssertEqual(store.baseURL, "https://saved.example")
    }

    func testFallsBackToEnvironmentWhenSavedBaseURLIsCleared() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = TutorialAPIEndpointStore(
            defaults: defaults,
            environment: ["CONTEXT_TUTORIAL_API_BASE_URL": "https://env.example"]
        )

        store.save("https://saved.example")
        store.clearSavedBaseURL()

        XCTAssertEqual(store.baseURL, "https://env.example")
    }

    func testEmptyBaseURLIsTreatedAsMissing() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = TutorialAPIEndpointStore(defaults: defaults, environment: [:])

        store.save("   ")

        XCTAssertNil(store.baseURL)
    }

    func testPlanURLDerivesTutorialPlanRoute() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = TutorialAPIEndpointStore(defaults: defaults, environment: [:])

        store.save("http://localhost:8000")

        XCTAssertEqual(try store.planURL().absoluteString, "http://localhost:8000/tutorials/plan")
    }

    func testPlanURLThrowsWhenBaseURLIsMissing() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let store = TutorialAPIEndpointStore(defaults: defaults, environment: [:])

        XCTAssertThrowsError(try store.planURL()) { error in
            XCTAssertEqual(error.localizedDescription, "Set the tutorial API base URL in Context Settings before sending a message.")
        }
    }
}
