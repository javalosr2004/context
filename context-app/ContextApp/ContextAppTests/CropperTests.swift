import XCTest
@testable import ContextApp

final class CropperTests: XCTestCase {
    private let frameSize = CGSize(width: 3000, height: 2000)

    func testCenteredRectAtCenter() {
        let r = Cropper.centeredRect(around: CGPoint(x: 1500, y: 1000), size: 256, in: frameSize)
        XCTAssertEqual(r.origin.x, 1500 - 128)
        XCTAssertEqual(r.origin.y, 1000 - 128)
        XCTAssertEqual(r.width, 256)
        XCTAssertEqual(r.height, 256)
    }

    func testNearLeftEdgeClipsToZeroOriginAndShrinks() {
        let r = Cropper.centeredRect(around: CGPoint(x: 50, y: 1000), size: 256, in: frameSize)
        // Half-width 128, cursor 50: left clamps to 0, right is 178.
        XCTAssertEqual(r.origin.x, 0)
        XCTAssertEqual(r.width, 178)
    }

    func testNearTopLeftCornerShrinksBothAxes() {
        let r = Cropper.centeredRect(around: CGPoint(x: 50, y: 30), size: 256, in: frameSize)
        XCTAssertEqual(r.origin.x, 0)
        XCTAssertEqual(r.origin.y, 0)
        XCTAssertEqual(r.width, 178)
        XCTAssertEqual(r.height, 158)
    }

    func testZeroSizeFrameProducesZeroRect() {
        let r = Cropper.centeredRect(around: CGPoint(x: 0, y: 0), size: 256, in: .zero)
        XCTAssertEqual(r.width, 0)
        XCTAssertEqual(r.height, 0)
    }

    func testContextCropIsLargerThanTarget() {
        let target = Cropper.centeredRect(around: CGPoint(x: 1500, y: 1000), size: Cropper.targetSize, in: frameSize)
        let context = Cropper.centeredRect(around: CGPoint(x: 1500, y: 1000), size: Cropper.contextSize, in: frameSize)
        XCTAssertLessThan(target.width, context.width)
    }
}
