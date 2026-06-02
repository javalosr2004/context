import XCTest
@testable import ContextApp

final class FocusMaskClickClassifierTests: XCTestCase {
    func testIgnoredControlClickDoesNotBecomeOutsideCutout() {
        let classifier = FocusMaskClickClassifier()
        let cutout = CGRect(x: 100, y: 100, width: 80, height: 80)

        let target = classifier.target(
            for: CGPoint(x: 20, y: 20),
            cutout: cutout,
            isIgnoredControl: true
        )

        XCTAssertEqual(target, .ignoredControl)
    }

    func testClickInsideCutoutIsInsideCutout() {
        let classifier = FocusMaskClickClassifier()
        let cutout = CGRect(x: 100, y: 100, width: 80, height: 80)

        let target = classifier.target(
            for: CGPoint(x: 120, y: 120),
            cutout: cutout,
            isIgnoredControl: false
        )

        XCTAssertEqual(target, .insideCutout)
    }

    func testClickOutsideCutoutIsOutsideCutout() {
        let classifier = FocusMaskClickClassifier()
        let cutout = CGRect(x: 100, y: 100, width: 80, height: 80)

        let target = classifier.target(
            for: CGPoint(x: 20, y: 20),
            cutout: cutout,
            isIgnoredControl: false
        )

        XCTAssertEqual(target, .outsideCutout)
    }

    func testClickInsideCutoutBeatsIgnoredControl() {
        let classifier = FocusMaskClickClassifier()
        let cutout = CGRect(x: 100, y: 100, width: 80, height: 80)

        let target = classifier.target(
            for: CGPoint(x: 120, y: 120),
            cutout: cutout,
            isIgnoredControl: true
        )

        XCTAssertEqual(target, .insideCutout)
    }

    func testInvalidCutoutDoesNotClassifyClick() {
        let classifier = FocusMaskClickClassifier()

        let target = classifier.target(
            for: CGPoint(x: 20, y: 20),
            cutout: .null,
            isIgnoredControl: false
        )

        XCTAssertNil(target)
    }
}
