import XCTest
@testable import ContextApp

final class ScrollSessionizerTests: XCTestCase {
    func testSingleDeltaPlusFlushClosesOneSession() {
        let s = ScrollSessionizer()
        XCTAssertNil(s.ingest(hostTimeMs: 0, cursor: .zero, dx: 0, dy: -120, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "a"))
        let closed = s.flush()
        XCTAssertNotNil(closed)
        XCTAssertEqual(closed?.dy, -120)
        XCTAssertEqual(closed?.direction, "down")
        XCTAssertEqual(closed?.startFrameId, "a")
    }

    func testBurstCollapsesAndAccumulates() {
        let s = ScrollSessionizer()
        _ = s.ingest(hostTimeMs: 0, cursor: .zero, dx: 0, dy: -10, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "a")
        _ = s.ingest(hostTimeMs: 50, cursor: .zero, dx: 0, dy: -20, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "b")
        _ = s.ingest(hostTimeMs: 100, cursor: .zero, dx: 0, dy: -30, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "c")
        let closed = s.flush()
        XCTAssertEqual(closed?.dy, -60)
        XCTAssertEqual(closed?.startFrameId, "a")
        XCTAssertEqual(closed?.endFrameId, "c")
        XCTAssertEqual(closed?.durationMs, 100)
    }

    func testIdleGapClosesPreviousAndOpensNew() {
        let s = ScrollSessionizer()
        _ = s.ingest(hostTimeMs: 0, cursor: .zero, dx: 0, dy: -10, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "a")
        let closed = s.ingest(hostTimeMs: 1000, cursor: .zero, dx: 0, dy: -20, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "b")
        XCTAssertNotNil(closed)
        XCTAssertEqual(closed?.dy, -10)
        // New session is open with the second event.
        let next = s.flush()
        XCTAssertEqual(next?.dy, -20)
        XCTAssertEqual(next?.startFrameId, "b")
    }

    func testMomentumEndCloses() {
        let s = ScrollSessionizer()
        _ = s.ingest(hostTimeMs: 0, cursor: .zero, dx: 0, dy: -10, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "a")
        // momentum end (3) + phase ended (0x80) flips the session closed inline.
        let closed = s.ingest(hostTimeMs: 50, cursor: .zero, dx: 0, dy: -5, phaseRaw: 0x80, momentumPhaseRaw: 3, frameId: "b")
        XCTAssertNotNil(closed)
        XCTAssertFalse(s.isOpen)
    }

    func testTickClosesAfterIdleGap() {
        let s = ScrollSessionizer()
        _ = s.ingest(hostTimeMs: 0, cursor: .zero, dx: 0, dy: -10, phaseRaw: 0, momentumPhaseRaw: 0, frameId: "a")
        XCTAssertNil(s.tick(nowMs: 200))
        XCTAssertNotNil(s.tick(nowMs: 500))
        XCTAssertFalse(s.isOpen)
    }

    func testDirectionPicksDominantAxis() {
        let s = ScrollSessionizer()
        _ = s.ingest(hostTimeMs: 0, cursor: .zero, dx: -200, dy: -10, phaseRaw: 0, momentumPhaseRaw: 0, frameId: nil)
        XCTAssertEqual(s.flush()?.direction, "right")
    }
}
