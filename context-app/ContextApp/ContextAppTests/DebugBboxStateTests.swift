import XCTest
@testable import ContextApp

final class DebugBboxStateTests: XCTestCase {
    func testReplaceStoresSingleCurrentBbox() {
        let state = DebugBboxState()
        let first = DebugBoundingBox(origin: CGPoint(x: 10, y: 20))
        let second = DebugBoundingBox(origin: CGPoint(x: 30, y: 40))

        state.replace(with: first)
        state.replace(with: second)

        XCTAssertEqual(state.current, second)
    }

    func testReplaceWithNilClearsCurrentBbox() {
        let state = DebugBboxState()
        state.replace(with: DebugBoundingBox(origin: CGPoint(x: 10, y: 20)))

        state.replace(with: nil)

        XCTAssertNil(state.current)
    }
}

