import XCTest
@testable import ContextApp

final class ChatMessageStoreTests: XCTestCase {
    func testAppendUserTextTrimsAndStoresMessage() {
        let store = ChatMessageStore()
        let now = Date(timeIntervalSince1970: 10)

        let message = store.appendUserText("  hello  ", now: { now })

        XCTAssertEqual(message?.role, .user)
        XCTAssertEqual(message?.content, .text("hello"))
        XCTAssertEqual(message?.createdAt, now)
        XCTAssertEqual(store.messages.map(\.content), [.text("hello")])
    }

    func testAppendTutorialTextStoresTutorialRole() {
        let store = ChatMessageStore()

        let message = store.appendTutorialText("  next step  ")

        XCTAssertEqual(message?.role, .tutorial)
        XCTAssertEqual(message?.content, .text("  next step  "))
    }

    func testAppendTutorialTextDeltaExtendsLastTutorialText() {
        let store = ChatMessageStore()
        let now = Date(timeIntervalSince1970: 10)
        let message = store.appendTutorialText("Looking", now: { now })

        let updated = store.appendTutorialTextDelta(" at the screen")

        XCTAssertEqual(updated?.id, message?.id)
        XCTAssertEqual(updated?.createdAt, now)
        XCTAssertEqual(store.messages.map(\.content), [.text("Looking at the screen")])
    }

    func testAppendTutorialTextDeltaStartsMessageWhenNeeded() {
        let store = ChatMessageStore()

        store.appendUserText("Create a repo")
        store.appendTutorialTextDelta("Looking...")

        XCTAssertEqual(store.messages.map(\.role), [.user, .tutorial])
        XCTAssertEqual(store.messages.map(\.content), [.text("Create a repo"), .text("Looking...")])
    }

    func testAppendTutorialTextDeltaPreservesLeadingSpaceWhenStartingMessage() {
        let store = ChatMessageStore()

        store.appendUserText("Create a repo")
        store.appendTutorialTextDelta(" a company account")

        XCTAssertEqual(store.messages.map(\.content), [.text("Create a repo"), .text(" a company account")])
    }

    func testAppendTutorialTextDeltaPreservesStandaloneSpaceChunk() {
        let store = ChatMessageStore()

        store.appendTutorialTextDelta("a")
        store.appendTutorialTextDelta(" ")
        store.appendTutorialTextDelta("company")

        XCTAssertEqual(store.messages.map(\.content), [.text("a company")])
    }

    func testReplaceLastTutorialTextKeepsExistingMessageIdentity() {
        let store = ChatMessageStore()
        let now = Date(timeIntervalSince1970: 10)
        let message = store.appendTutorialTextDelta("Run", now: { now })

        let updated = store.replaceLastTutorialText("RunPod is a cloud GPU host.")

        XCTAssertEqual(updated?.id, message?.id)
        XCTAssertEqual(updated?.createdAt, now, "createdAt should not be recreated")
        XCTAssertEqual(store.messages.map(\.content), [.text("RunPod is a cloud GPU host.")])
    }

    func testAppendRejectsEmptyTextAfterTrimming() {
        let store = ChatMessageStore()

        XCTAssertNil(store.appendUserText(" \n\t "))
        XCTAssertNil(store.appendTutorialText(" \n\t "))
        XCTAssertNil(store.appendTutorialTextDelta(" \n\t "))
        XCTAssertTrue(store.messages.isEmpty)
    }

    func testAppendTutorialPlanStoresPlanContent() {
        let store = ChatMessageStore()
        let plan = tutorialPlan()

        let message = store.appendTutorialPlan(plan)

        XCTAssertEqual(message?.role, .tutorial)
        XCTAssertEqual(message?.content, .tutorialPlan(plan))
    }

    func testAppendPreservesInsertionOrder() {
        let store = ChatMessageStore()

        store.appendUserText("first")
        store.appendTutorialText("second")
        store.appendTutorialPlan(tutorialPlan())

        XCTAssertEqual(store.messages.map(\.role), [.user, .tutorial, .tutorial])
        XCTAssertEqual(store.messages.first?.content, .text("first"))
        XCTAssertEqual(store.messages.dropFirst().first?.content, .text("second"))
    }

    func testRemoveAllClearsMessages() {
        let store = ChatMessageStore()

        store.appendUserText("first")
        store.appendTutorialText("second")
        store.removeAll()

        XCTAssertTrue(store.messages.isEmpty)
    }

    private func tutorialPlan() -> TutorialPlan {
        TutorialPlan(
            goal: "Send a message",
            summary: "Open chat and send text.",
            steps: [
                TutorialStep(
                    stepId: "step-1",
                    instruction: "Click the message field.",
                    actions: [.click(ClickAction(target: ActionTarget(
                        kind: .element,
                        label: "Message",
                        role: "text field",
                        description: "The chat composer field",
                        textNearby: ["Send"]
                    ), requiresConfirmation: false))],
                    confidence: 0.93
                )
            ]
        )
    }
}

final class MarkdownTextRendererTests: XCTestCase {
    func testRendererPreservesActualNewlines() {
        let rendered = renderedText(from: "First\nSecond")

        XCTAssertEqual(rendered, "First\nSecond")
    }

    func testRendererConvertsEscapedNewlines() {
        let rendered = renderedText(from: "First\\nSecond")

        XCTAssertEqual(rendered, "First\nSecond")
    }

    func testRendererConvertsDoubleEscapedNewlines() {
        let rendered = renderedText(from: "First\\\\nSecond")

        XCTAssertEqual(rendered, "First\nSecond")
    }

    func testRendererConvertsEscapedBlankLineBeforeMarkdownParsing() {
        let rendered = renderedText(from: "First\\n\\n**Second**")

        XCTAssertEqual(rendered, "First\n\nSecond")
    }

    func testRendererConvertsEscapedCarriageReturnNewline() {
        let rendered = renderedText(from: "First\\r\\nSecond")

        XCTAssertEqual(rendered, "First\nSecond")
    }

    func testRendererPreservesEscapedIndentedListAfterColon() {
        let rendered = renderedText(from: "Defines:\\n  - multiple services\\n  - ports\\n")

        XCTAssertEqual(rendered, "Defines:\n\n• multiple services\n• ports")
    }

    func testRendererPreservesEscapedStandardListAfterColon() {
        let rendered = renderedText(from: "Defines:\\n- multiple services\\n- ports\\n")

        XCTAssertEqual(rendered, "Defines:\n\n• multiple services\n• ports")
    }

    func testRendererPreservesListItemChildBlocks() {
        let rendered = renderedText(from: "- Defines:\\n  - multiple services\\n  - ports\\n")

        XCTAssertEqual(rendered, "• Defines:\n  • multiple services\n  • ports")
    }

    private func renderedText(from source: String) -> String {
        String(MarkdownTextRenderer.attributedString(from: source).characters)
    }
}
