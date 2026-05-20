import CoreGraphics
import Foundation

/// Coarse "scroll tick" emitted by the sessionizer to its host.
struct SessionizedScroll {
    let startHostTimeMs: Int64
    let endHostTimeMs: Int64
    let startFrameId: String?
    let endFrameId: String?
    let cursor: CGPoint
    let dx: Int
    let dy: Int
    let direction: String

    var durationMs: Int { Int(endHostTimeMs - startHostTimeMs) }
}

/// Buffers raw `scrollWheel` events into one semantic scroll session.
/// Pure logic — knows nothing about frame streams or disk. The caller is
/// responsible for attaching frame ids and flushing on stop.
final class ScrollSessionizer {
    static let idleGapMs: Int64 = 350

    private(set) var isOpen: Bool = false
    private var startHostMs: Int64 = 0
    private var lastHostMs: Int64 = 0
    private var startFrameId: String?
    private var endFrameId: String?
    private var startCursor: CGPoint = .zero
    private var accumDx: Double = 0
    private var accumDy: Double = 0
    private var sawMomentumEnded: Bool = false

    /// Feed a scrollWheel event. Returns a closed session if the input caused
    /// the previous session to close before this one starts (idle gap exceeded).
    /// The caller should also poll `tick(now:)` to detect timeout closures.
    @discardableResult
    func ingest(
        hostTimeMs: Int64,
        cursor: CGPoint,
        dx: Double,
        dy: Double,
        phaseRaw: UInt32,
        momentumPhaseRaw: UInt32,
        frameId: String?
    ) -> SessionizedScroll? {
        var closed: SessionizedScroll? = nil
        if isOpen && (hostTimeMs - lastHostMs) > Self.idleGapMs {
            closed = closeSession()
        }
        if !isOpen {
            isOpen = true
            startHostMs = hostTimeMs
            startCursor = cursor
            startFrameId = frameId
            accumDx = 0
            accumDy = 0
            sawMomentumEnded = false
        }
        accumDx += dx
        accumDy += dy
        endFrameId = frameId
        lastHostMs = hostTimeMs

        // CGMomentumScrollPhase: 0 = none, 1 = begin, 2 = continue, 3 = end.
        if momentumPhaseRaw == 3 {
            sawMomentumEnded = true
        }
        // CGScrollPhase: kCGScrollPhaseEnded = 0x80 (128).
        let ended = (phaseRaw == 0x80) && sawMomentumEnded
        if ended {
            let s = closeSession()
            return closed ?? s
        }
        return closed
    }

    /// Call periodically (or before stopping). Closes an open session if it
    /// has been idle longer than `idleGapMs`.
    func tick(nowMs: Int64) -> SessionizedScroll? {
        guard isOpen else { return nil }
        if nowMs - lastHostMs > Self.idleGapMs {
            return closeSession()
        }
        return nil
    }

    /// Forcefully close any open session and return it.
    func flush() -> SessionizedScroll? {
        guard isOpen else { return nil }
        return closeSession()
    }

    private func closeSession() -> SessionizedScroll {
        let dx = Int(accumDx.rounded())
        let dy = Int(accumDy.rounded())
        let direction: String = {
            if abs(dy) >= abs(dx) {
                return dy < 0 ? "down" : "up"
            } else {
                return dx < 0 ? "right" : "left"
            }
        }()
        let session = SessionizedScroll(
            startHostTimeMs: startHostMs,
            endHostTimeMs: lastHostMs,
            startFrameId: startFrameId,
            endFrameId: endFrameId,
            cursor: startCursor,
            dx: dx,
            dy: dy,
            direction: direction
        )
        isOpen = false
        startFrameId = nil
        endFrameId = nil
        accumDx = 0
        accumDy = 0
        sawMomentumEnded = false
        return session
    }
}
