import XCTest
@testable import ContextApp

final class EdgeTabAnchorTests: XCTestCase {
    private let size = CGSize(width: 8, height: 56)
    private let inset = CGSize(width: 8, height: 12)

    func testAnchorsBottomRightInsideVisibleFrame() {
        let visible = CGRect(x: 0, y: 0, width: 1440, height: 900)

        let frame = EdgeTabAnchor.frame(in: visible, size: size, inset: inset)

        XCTAssertEqual(frame.maxX, visible.maxX - inset.width)
        XCTAssertEqual(frame.minY, visible.minY + inset.height)
        XCTAssertEqual(frame.size, size)
    }

    func testHonoursNonZeroOriginForMenuBarAndDock() {
        let visible = CGRect(x: 100, y: 25, width: 1240, height: 800)

        let frame = EdgeTabAnchor.frame(in: visible, size: size, inset: inset)

        XCTAssertEqual(frame.maxX, visible.maxX - inset.width)
        XCTAssertEqual(frame.minY, visible.minY + inset.height)
    }
}
