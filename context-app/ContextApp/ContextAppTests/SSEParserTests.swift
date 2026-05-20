import XCTest
@testable import ContextApp

final class SSEParserTests: XCTestCase {
    func testParsesSingleFrame() {
        let buf = "id: 42\nevent: enriched\ndata: {\"x\":1}\n\n"
        let (frames, leftover) = SSEParser.parse(buf)
        XCTAssertEqual(frames.count, 1)
        XCTAssertEqual(frames[0].id, 42)
        XCTAssertEqual(frames[0].event, "enriched")
        XCTAssertEqual(frames[0].data, "{\"x\":1}")
        XCTAssertEqual(leftover, "")
    }

    func testParsesMultipleFramesAndLeavesLeftover() {
        let buf = "id: 1\nevent: a\ndata: one\n\nid: 2\nevent: b\ndata: two\n\nid: 3"
        let (frames, leftover) = SSEParser.parse(buf)
        XCTAssertEqual(frames.count, 2)
        XCTAssertEqual(frames[0].event, "a")
        XCTAssertEqual(frames[1].event, "b")
        XCTAssertEqual(leftover, "id: 3")
    }

    func testIgnoresCommentLines() {
        let buf = ": ping\nid: 7\nevent: progress\ndata: ok\n\n"
        let (frames, _) = SSEParser.parse(buf)
        XCTAssertEqual(frames.first?.id, 7)
        XCTAssertEqual(frames.first?.event, "progress")
    }

    func testMultiLineDataIsJoined() {
        let buf = "event: x\ndata: first\ndata: second\n\n"
        let (frames, _) = SSEParser.parse(buf)
        XCTAssertEqual(frames.first?.data, "first\nsecond")
    }
}
