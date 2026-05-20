import XCTest
@testable import ContextApp

final class KeyTypingSessionizerTests: XCTestCase {
    // MARK: - Classifier

    func testPrintableLetterIsTyping() {
        let c = KeyTypingSessionizer.classify(keyCode: 0, characters: "a", modifiers: [])
        XCTAssertEqual(c, .typing("a"))
    }

    func testShiftedLetterStillTyping() {
        let c = KeyTypingSessionizer.classify(keyCode: 0, characters: "A", modifiers: ["shift"])
        XCTAssertEqual(c, .typing("A"))
    }

    func testCmdLetterIsDiscreteShortcut() {
        let c = KeyTypingSessionizer.classify(keyCode: 8, characters: "c", modifiers: ["cmd"])
        XCTAssertEqual(c, .discrete)
    }

    func testCtrlOrOptOrFnIsDiscrete() {
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 0, characters: "a", modifiers: ["ctrl"]), .discrete)
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 0, characters: "a", modifiers: ["opt"]), .discrete)
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 0, characters: "a", modifiers: ["fn"]), .discrete)
    }

    func testReturnTabEscapeAreDiscrete() {
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 36, characters: "\r", modifiers: []), .discrete)
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 48, characters: "\t", modifiers: []), .discrete)
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 53, characters: nil, modifiers: []), .discrete)
    }

    func testArrowsAndFunctionKeysAreDiscrete() {
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 123, characters: nil, modifiers: []), .discrete)
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 122, characters: nil, modifiers: []), .discrete)
    }

    func testBackspaceIsEdit() {
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 51, characters: nil, modifiers: []), .backspaceEdit)
    }

    func testEmptyCharactersTreatedAsDiscrete() {
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 200, characters: "", modifiers: []), .discrete)
        XCTAssertEqual(KeyTypingSessionizer.classify(keyCode: 200, characters: nil, modifiers: []), .discrete)
    }

    // MARK: - Session behavior

    func testTypingRunCoalescesAndFlush() {
        let s = KeyTypingSessionizer()
        XCTAssertNil(s.ingest(classification: .typing("h"), hostTimeMs: 0, cursor: .zero, frameId: "f0"))
        XCTAssertNil(s.ingest(classification: .typing("i"), hostTimeMs: 50, cursor: .zero, frameId: "f1"))
        let closed = s.flush()
        XCTAssertEqual(closed?.text, "hi")
        XCTAssertEqual(closed?.keyCount, 2)
        XCTAssertEqual(closed?.backspaceCount, 0)
        XCTAssertEqual(closed?.startFrameId, "f0")
        XCTAssertEqual(closed?.endFrameId, "f1")
        XCTAssertEqual(closed?.durationMs, 50)
    }

    func testBackspaceShrinksBuffer() {
        let s = KeyTypingSessionizer()
        _ = s.ingest(classification: .typing("a"), hostTimeMs: 0, cursor: .zero, frameId: nil)
        _ = s.ingest(classification: .typing("b"), hostTimeMs: 10, cursor: .zero, frameId: nil)
        _ = s.ingest(classification: .backspaceEdit, hostTimeMs: 20, cursor: .zero, frameId: nil)
        _ = s.ingest(classification: .typing("c"), hostTimeMs: 30, cursor: .zero, frameId: nil)
        let closed = s.flush()
        XCTAssertEqual(closed?.text, "ac")
        XCTAssertEqual(closed?.keyCount, 4)
        XCTAssertEqual(closed?.backspaceCount, 1)
    }

    func testBackspacingEntireBufferEmitsNothing() {
        let s = KeyTypingSessionizer()
        _ = s.ingest(classification: .typing("a"), hostTimeMs: 0, cursor: .zero, frameId: nil)
        _ = s.ingest(classification: .backspaceEdit, hostTimeMs: 10, cursor: .zero, frameId: nil)
        XCTAssertNil(s.flush())
        XCTAssertFalse(s.isOpen)
    }

    func testIdleGapClosesPreviousAndOpensNew() {
        let s = KeyTypingSessionizer()
        _ = s.ingest(classification: .typing("a"), hostTimeMs: 0, cursor: .zero, frameId: "f0")
        let closed = s.ingest(classification: .typing("b"), hostTimeMs: 5_000, cursor: .zero, frameId: "f1")
        XCTAssertEqual(closed?.text, "a")
        let next = s.flush()
        XCTAssertEqual(next?.text, "b")
        XCTAssertEqual(next?.startFrameId, "f1")
    }

    func testTickClosesAfterIdleGap() {
        let s = KeyTypingSessionizer()
        _ = s.ingest(classification: .typing("a"), hostTimeMs: 0, cursor: .zero, frameId: nil)
        XCTAssertNil(s.tick(nowMs: 500))
        XCTAssertNotNil(s.tick(nowMs: 5_000))
        XCTAssertFalse(s.isOpen)
    }

    func testFlushOnEmptyReturnsNil() {
        let s = KeyTypingSessionizer()
        XCTAssertNil(s.flush())
    }
}

final class TypingBurstSchemaTests: XCTestCase {
    func testTypeEventRoundTripsSnakeCase() throws {
        let event = RecordedEvent(
            id: "abc",
            timestampMs: 1,
            kind: .type,
            cursor: Point(x: 0, y: 0),
            typing: TypingBurst(
                text: "hello",
                keyCount: 5,
                backspaceCount: 0,
                startFrameId: "f0",
                endFrameId: "f1",
                durationMs: 240
            ),
            frameId: "f0"
        )
        let data = try JSONEncoder().encode(event)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"kind\":\"type\""))
        XCTAssertTrue(json.contains("\"key_count\":5"))
        XCTAssertTrue(json.contains("\"backspace_count\":0"))
        XCTAssertTrue(json.contains("\"start_frame_id\":\"f0\""))
        XCTAssertTrue(json.contains("\"duration_ms\":240"))

        let decoded = try JSONDecoder().decode(RecordedEvent.self, from: data)
        XCTAssertEqual(decoded.kind, .type)
        XCTAssertEqual(decoded.typing?.text, "hello")
    }

    func testSchemaVersionBumped() {
        XCTAssertEqual(kRecordingSchemaVersion, 2)
    }
}
