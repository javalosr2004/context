import XCTest
@testable import ContextApp

final class ChatMessageStoreTests: XCTestCase {
    func testAppendTrimsAndStoresMessage() {
        let store = ChatMessageStore()
        let now = Date(timeIntervalSince1970: 10)

        let message = store.append("  hello  ", now: { now })

        XCTAssertEqual(message?.text, "hello")
        XCTAssertEqual(message?.createdAt, now)
        XCTAssertEqual(store.messages.map(\.text), ["hello"])
    }

    func testAppendRejectsEmptyTextAfterTrimming() {
        let store = ChatMessageStore()

        XCTAssertNil(store.append(" \n\t "))
        XCTAssertTrue(store.messages.isEmpty)
    }

    func testAppendPreservesInsertionOrder() {
        let store = ChatMessageStore()

        store.append("first")
        store.append("second")
        store.append("third")

        XCTAssertEqual(store.messages.map(\.text), ["first", "second", "third"])
    }
}

