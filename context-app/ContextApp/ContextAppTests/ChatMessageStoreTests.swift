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
        XCTAssertEqual(message?.content, .text("next step"))
    }

    func testAppendRejectsEmptyTextAfterTrimming() {
        let store = ChatMessageStore()

        XCTAssertNil(store.appendUserText(" \n\t "))
        XCTAssertNil(store.appendTutorialText(" \n\t "))
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
                    action: .click(ClickAction(target: ActionTarget(
                        kind: .element,
                        label: "Message",
                        role: "text field",
                        description: "The chat composer field",
                        textNearby: ["Send"]
                    ))),
                    confidence: 0.93,
                    requiresConfirmation: false
                )
            ]
        )
    }
}
