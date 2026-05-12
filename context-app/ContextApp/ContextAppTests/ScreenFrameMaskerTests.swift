import XCTest
@testable import ContextApp

final class ScreenFrameMaskerTests: XCTestCase {
    func testPixelRectConvertsWindowFrameIntoImageCoordinates() {
        let rect = ScreenFrameMasker.pixelRect(
            for: CGRect(x: 100, y: 200, width: 300, height: 100),
            screenFrame: CGRect(x: 0, y: 0, width: 1000, height: 500),
            imageSize: CGSize(width: 2000, height: 1000),
            padding: 0
        )

        XCTAssertEqual(rect, CGRect(x: 200, y: 400, width: 600, height: 200))
    }

    func testPixelRectClipsPaddedFrameToScreen() {
        let rect = ScreenFrameMasker.pixelRect(
            for: CGRect(x: -10, y: 450, width: 80, height: 80),
            screenFrame: CGRect(x: 0, y: 0, width: 1000, height: 500),
            imageSize: CGSize(width: 2000, height: 1000),
            padding: 20
        )

        XCTAssertEqual(rect, CGRect(x: 0, y: 860, width: 180, height: 140))
    }

    func testPixelRectReturnsNilWhenWindowIsOutsideScreen() {
        let rect = ScreenFrameMasker.pixelRect(
            for: CGRect(x: 1200, y: 200, width: 100, height: 100),
            screenFrame: CGRect(x: 0, y: 0, width: 1000, height: 500),
            imageSize: CGSize(width: 2000, height: 1000),
            padding: 0
        )

        XCTAssertNil(rect)
    }
}
