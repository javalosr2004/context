import XCTest
@testable import ContextApp

final class PopupStateTests: XCTestCase {
    func testMinifyTransitionsFromExpandedToIconOrigin() {
        let frame = CGRect(x: 10, y: 20, width: 360, height: 440)
        let state = PopupState.expanded(frame: frame)

        XCTAssertEqual(state.minified(at: CGPoint(x: 30, y: 40)), .minified(iconOrigin: CGPoint(x: 30, y: 40)))
    }

    func testExpandTransitionsFromMinifiedToFrame() {
        let state = PopupState.minified(iconOrigin: CGPoint(x: 30, y: 40))
        let frame = CGRect(x: 10, y: 20, width: 360, height: 440)

        XCTAssertEqual(state.expanded(at: frame), .expanded(frame: frame))
    }
}

