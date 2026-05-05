import XCTest
@testable import ContextApp

final class ScreenBoundsKeeperTests: XCTestCase {
    private let keeper = ScreenBoundsKeeper()
    private let screen = CGRect(x: 0, y: 0, width: 1000, height: 800)

    func testFullyOnScreenFrameIsUnchanged() {
        let frame = CGRect(x: 100, y: 100, width: 300, height: 200)

        XCTAssertEqual(keeper.clamp(frame: frame, into: screen, minimumVisible: 80), frame)
    }

    func testClampsFramePastRightEdge() {
        let frame = CGRect(x: 980, y: 100, width: 300, height: 200)
        let clamped = keeper.clamp(frame: frame, into: screen, minimumVisible: 80)

        XCTAssertEqual(clamped.origin.x, 920)
        XCTAssertEqual(clamped.origin.y, 100)
    }

    func testClampsFramePastBottomEdge() {
        let frame = CGRect(x: 100, y: -190, width: 300, height: 200)
        let clamped = keeper.clamp(frame: frame, into: screen, minimumVisible: 80)

        XCTAssertEqual(clamped.origin.x, 100)
        XCTAssertEqual(clamped.origin.y, -120)
    }

    func testClampsFullyOffScreenFrame() {
        let frame = CGRect(x: -400, y: 900, width: 300, height: 200)
        let clamped = keeper.clamp(frame: frame, into: screen, minimumVisible: 80)

        XCTAssertEqual(clamped.origin.x, -220)
        XCTAssertEqual(clamped.origin.y, 720)
    }

    func testLargerThanScreenPrefersVisibilityWithoutResizing() {
        let frame = CGRect(x: -1400, y: -900, width: 1400, height: 900)
        let clamped = keeper.clamp(frame: frame, into: screen, minimumVisible: 80)

        XCTAssertEqual(clamped.size, frame.size)
        XCTAssertEqual(clamped.origin.x, -1320)
        XCTAssertEqual(clamped.origin.y, -820)
    }
}

