import XCTest
@testable import ContextApp

final class BboxPositionGeneratorTests: XCTestCase {
    func testGeneratedPositionIsWithinValidRectangle() {
        var rng = SeededRandomNumberGenerator(seed: 42)
        let generator = BboxPositionGenerator()

        for _ in 0..<100 {
            let point = generator.position(
                screen: CGSize(width: 1200, height: 900),
                bbox: CGSize(width: 500, height: 500),
                rng: &rng
            )

            XCTAssertGreaterThanOrEqual(point.x, 0)
            XCTAssertLessThanOrEqual(point.x, 700)
            XCTAssertGreaterThanOrEqual(point.y, 0)
            XCTAssertLessThanOrEqual(point.y, 400)
        }
    }

    func testSeededGeneratorProducesRepeatableSequence() {
        var firstRng = SeededRandomNumberGenerator(seed: 7)
        var secondRng = SeededRandomNumberGenerator(seed: 7)
        let generator = BboxPositionGenerator()

        let first = (0..<10).map { _ in generator.position(screen: CGSize(width: 1200, height: 900), rng: &firstRng) }
        let second = (0..<10).map { _ in generator.position(screen: CGSize(width: 1200, height: 900), rng: &secondRng) }

        XCTAssertEqual(first, second)
    }

    func testTenSeededCallsProduceAtLeastFourDistinctPositions() {
        var rng = SeededRandomNumberGenerator(seed: 99)
        let generator = BboxPositionGenerator()
        let positions = (0..<10).map { _ in generator.position(screen: CGSize(width: 1600, height: 1200), rng: &rng) }

        XCTAssertGreaterThanOrEqual(Set(positions.map { "\($0.x),\($0.y)" }).count, 4)
    }
}

private struct SeededRandomNumberGenerator: RandomNumberGenerator {
    private var state: UInt64

    init(seed: UInt64) {
        self.state = seed
    }

    mutating func next() -> UInt64 {
        state = 2862933555777941757 &* state &+ 3037000493
        return state
    }
}

