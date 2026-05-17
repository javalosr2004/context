import XCTest
@testable import ContextApp

final class ScreenStabilityWatcherTests: XCTestCase {
    func testStabilityCounterTriggersWhenDifferenceStopsChanging() {
        var counter = StabilityCounter(requiredUnchangedFrames: 3, differenceTolerance: 0.001)

        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.05))
        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.0505))
        XCTAssertTrue(counter.didReachUnchangedLimit(diff: 0.0508))
    }

    func testStabilityCounterResetsWhenDifferenceChanges() {
        var counter = StabilityCounter(requiredUnchangedFrames: 3, differenceTolerance: 0.001)

        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.05))
        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.06))
        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.0605))
        XCTAssertTrue(counter.didReachUnchangedLimit(diff: 0.0608))
    }

    func testStabilityCounterResetClearsPreviousDifference() {
        var counter = StabilityCounter(requiredUnchangedFrames: 2, differenceTolerance: 0.001)

        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.05))
        counter.reset()

        XCTAssertFalse(counter.didReachUnchangedLimit(diff: 0.0505))
        XCTAssertTrue(counter.didReachUnchangedLimit(diff: 0.0508))
    }
}
