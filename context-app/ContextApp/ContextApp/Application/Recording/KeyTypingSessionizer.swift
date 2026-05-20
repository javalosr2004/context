import CoreGraphics
import Foundation

/// One coalesced "type" run handed back to the host after the session closes.
struct SessionizedTyping {
    let text: String
    let keyCount: Int
    let backspaceCount: Int
    let startHostTimeMs: Int64
    let endHostTimeMs: Int64
    let startFrameId: String?
    let endFrameId: String?
    let cursor: CGPoint

    var durationMs: Int { Int(endHostTimeMs - startHostTimeMs) }
}

/// Classification verdict for a single keyDown event. Pure logic — no AppKit.
enum KeyClassification: Equatable {
    /// Printable character with only shift/caps modifiers. Belongs in a burst.
    case typing(String)
    /// Backspace (delete-left) with no non-shift modifier. Edits the buffer.
    case backspaceEdit
    /// Anything else: control keys, navigation, function keys, or any key
    /// combined with cmd/ctrl/opt. Closes any open burst and is emitted
    /// discretely by the host.
    case discrete
}

/// Buffers consecutive printable keystrokes into one semantic typing session.
/// Stateless on classification; the host calls `ingest` only for keys that
/// already classified as `.typing` or `.backspaceEdit`, and flushes the open
/// session whenever a `.discrete` key or a non-key event arrives.
final class KeyTypingSessionizer {
    /// Idle interval after which an open burst auto-closes on the next ingest.
    static let idleGapMs: Int64 = 1500

    /// macOS virtual keycodes that produce no semantic text and should never
    /// be merged into a typing run even if `characters` is non-empty.
    private static let nonTypingKeyCodes: Set<Int> = [
        36,  // return
        76,  // numpad enter
        48,  // tab
        53,  // escape
        51,  // backspace (handled separately as edit)
        117, // forward-delete
        123, 124, 125, 126,            // arrow keys
        115, 116, 119, 121,            // home / pageUp / end / pageDown
        122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, // F1-F12
    ]

    private(set) var isOpen: Bool = false
    private var buffer: String = ""
    private var keyCount: Int = 0
    private var backspaceCount: Int = 0
    private var startHostMs: Int64 = 0
    private var lastHostMs: Int64 = 0
    private var startFrameId: String?
    private var endFrameId: String?
    private var startCursor: CGPoint = .zero

    /// Classify a raw keyDown. Pure; no state mutation.
    static func classify(
        keyCode: Int,
        characters: String?,
        modifiers: [String]
    ) -> KeyClassification {
        if hasShortcutModifier(modifiers) {
            return .discrete
        }
        if keyCode == 51 { return .backspaceEdit }
        if nonTypingKeyCodes.contains(keyCode) { return .discrete }
        guard let chars = characters, !chars.isEmpty else { return .discrete }
        // Reject control characters that some keys still report as "characters".
        for scalar in chars.unicodeScalars {
            if scalar.value < 0x20 || scalar.value == 0x7F {
                return .discrete
            }
        }
        return .typing(chars)
    }

    /// Feed one typing/backspace event. Returns a closed session if the idle
    /// gap forced the previous burst to close before this one starts.
    @discardableResult
    func ingest(
        classification: KeyClassification,
        hostTimeMs: Int64,
        cursor: CGPoint,
        frameId: String?
    ) -> SessionizedTyping? {
        var closed: SessionizedTyping? = nil
        if isOpen && (hostTimeMs - lastHostMs) > Self.idleGapMs {
            closed = closeSession()
        }
        switch classification {
        case .typing(let chars):
            openIfNeeded(hostTimeMs: hostTimeMs, cursor: cursor, frameId: frameId)
            buffer.append(chars)
            keyCount += 1
        case .backspaceEdit:
            openIfNeeded(hostTimeMs: hostTimeMs, cursor: cursor, frameId: frameId)
            if !buffer.isEmpty { buffer.removeLast() }
            keyCount += 1
            backspaceCount += 1
        case .discrete:
            // Host should never feed discrete keys; treat as no-op to be safe.
            return closed
        }
        endFrameId = frameId
        lastHostMs = hostTimeMs
        return closed
    }

    /// Close an open burst due to idle timeout polling. Returns nil if no
    /// burst is open or the burst is still within the idle window.
    func tick(nowMs: Int64) -> SessionizedTyping? {
        guard isOpen else { return nil }
        if nowMs - lastHostMs > Self.idleGapMs {
            return closeSession()
        }
        return nil
    }

    /// Force-close the open burst (mouse/scroll/discrete-key/stop).
    /// Returns nil if no burst is open or the buffer ended up empty (e.g.
    /// the user typed three chars and backspaced them all).
    func flush() -> SessionizedTyping? {
        guard isOpen else { return nil }
        return closeSession()
    }

    private func openIfNeeded(hostTimeMs: Int64, cursor: CGPoint, frameId: String?) {
        if isOpen { return }
        isOpen = true
        buffer = ""
        keyCount = 0
        backspaceCount = 0
        startHostMs = hostTimeMs
        startCursor = cursor
        startFrameId = frameId
        endFrameId = frameId
    }

    private func closeSession() -> SessionizedTyping? {
        let result: SessionizedTyping? = buffer.isEmpty ? nil : SessionizedTyping(
            text: buffer,
            keyCount: keyCount,
            backspaceCount: backspaceCount,
            startHostTimeMs: startHostMs,
            endHostTimeMs: lastHostMs,
            startFrameId: startFrameId,
            endFrameId: endFrameId,
            cursor: startCursor
        )
        isOpen = false
        buffer = ""
        keyCount = 0
        backspaceCount = 0
        startFrameId = nil
        endFrameId = nil
        return result
    }

    private static func hasShortcutModifier(_ modifiers: [String]) -> Bool {
        for m in modifiers {
            if m == "cmd" || m == "ctrl" || m == "opt" || m == "fn" {
                return true
            }
        }
        return false
    }
}
