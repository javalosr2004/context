import XCTest
@testable import ContextApp

final class PopupStateTests: XCTestCase {
    func testCollapseRemembersLastFrame() {
        let frame = CGRect(x: 10, y: 20, width: 360, height: 440)
        let state = PopupState.expanded(frame: frame)

        XCTAssertEqual(state.collapsed(lastFrame: frame), .collapsed(lastFrame: frame))
    }

    func testExpandTransitionsFromCollapsedToFrame() {
        let frame = CGRect(x: 10, y: 20, width: 360, height: 440)
        let state = PopupState.collapsed(lastFrame: frame)

        XCTAssertEqual(state.expanded(at: frame), .expanded(frame: frame))
    }

    func testLastExpandedFrameIsAvailableInBothStates() {
        let frame = CGRect(x: 10, y: 20, width: 360, height: 440)
        XCTAssertEqual(PopupState.expanded(frame: frame).lastExpandedFrame, frame)
        XCTAssertEqual(PopupState.collapsed(lastFrame: frame).lastExpandedFrame, frame)
    }
}
