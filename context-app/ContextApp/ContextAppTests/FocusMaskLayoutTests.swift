import XCTest
@testable import ContextApp

final class FocusMaskLayoutTests: XCTestCase {
    func testDimmingRectsLeavePaddedCutoutUncovered() {
        let layout = FocusMaskLayout(cutoutPadding: 10)
        let screen = CGRect(x: 0, y: 0, width: 1000, height: 800)
        let target = CGRect(x: 400, y: 300, width: 120, height: 80)

        let cutout = layout.paddedCutout(screenFrame: screen, targetFrame: target)
        let rects = layout.dimmingRects(screenFrame: screen, targetFrame: target)

        XCTAssertEqual(rects.count, 4)
        XCTAssertTrue(rects.allSatisfy { screen.contains($0) })
        XCTAssertFalse(rects.contains { $0.intersects(cutout) })
    }

    func testCutoutIsClippedToScreenBounds() {
        let layout = FocusMaskLayout(cutoutPadding: 20)
        let screen = CGRect(x: 0, y: 0, width: 1000, height: 800)
        let target = CGRect(x: -10, y: 760, width: 80, height: 80)

        let cutout = layout.paddedCutout(screenFrame: screen, targetFrame: target)

        XCTAssertEqual(cutout.minX, 0, accuracy: 0.001)
        XCTAssertEqual(cutout.maxY, 800, accuracy: 0.001)
        XCTAssertTrue(screen.contains(cutout))
    }

    func testInvalidScreenReturnsNoDimmingRects() {
        let layout = FocusMaskLayout()

        let rects = layout.dimmingRects(
            screenFrame: CGRect(x: 0, y: 0, width: 0, height: 800),
            targetFrame: CGRect(x: 10, y: 10, width: 20, height: 20)
        )

        XCTAssertTrue(rects.isEmpty)
    }
}
