import XCTest
@testable import ContextApp

final class TutorialActionConsumerTests: XCTestCase {
    func testGroundingInstructionTextIncludesTargetDescription() {
        let step = TutorialStep(
            stepId: "step-1",
            instruction: "Click the New repository button.",
            action: .click(ClickAction(target: ActionTarget(
                kind: .element,
                label: "New repository",
                role: "button",
                description: "Starts repository creation",
                textNearby: ["Repositories", "Import"]
            ))),
            confidence: 0.86,
            requiresConfirmation: false
        )

        XCTAssertEqual(
            TutorialActionConsumer.groundingInstructionText(for: step),
            "Click the New repository button.\n\nTarget: Starts repository creation"
        )
    }

    func testGroundingInstructionTextOmitsMissingTargetDescription() {
        let step = TutorialStep(
            stepId: "step-1b",
            instruction: "Click the icon.",
            action: .click(ClickAction(target: ActionTarget(
                kind: .element,
                label: "Icon",
                role: "button",
                description: nil,
                textNearby: nil
            ))),
            confidence: 0.6,
            requiresConfirmation: false
        )

        XCTAssertEqual(
            TutorialActionConsumer.groundingInstructionText(for: step),
            "Click the icon."
        )
    }

    func testGroundingPayloadJSONIncludesInstructionWithTargetDescription() throws {
        let step = TutorialStep(
            stepId: "step-2",
            instruction: "Scroll down to the billing section.",
            action: .scroll(ScrollAction(
                target: ActionTarget(
                    kind: .window,
                    label: "Settings",
                    role: nil,
                    description: "The app settings window",
                    textNearby: nil
                ),
                direction: .down
            )),
            confidence: 0.75,
            requiresConfirmation: false
        )

        let json = TutorialActionConsumer.groundingPayloadJSONString(for: step)
        let object = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]

        XCTAssertEqual(object?.keys.sorted(), ["instruction"])
        XCTAssertEqual(
            object?["instruction"] as? String,
            "Scroll down to the billing section.\n\nTarget: The app settings window"
        )
    }

    func testSkipsGroundingForTypeWithoutTarget() {
        let action: TutorialAction = .type(TypeAction(target: nil, text: "cmd+a"))
        XCTAssertTrue(TutorialActionConsumer.skipsGrounding(action: action))
    }

    func testGroundsTypeWithTarget() {
        let target = ActionTarget(
            kind: .element,
            label: "Search",
            role: "text field",
            description: nil,
            textNearby: nil
        )
        let action: TutorialAction = .type(TypeAction(target: target, text: "hello"))
        XCTAssertFalse(TutorialActionConsumer.skipsGrounding(action: action))
    }

    func testConsumeDispatchesGroundingInstruction() async {
        let step = TutorialStep(
            stepId: "step-3",
            instruction: "Click the search field.",
            action: .click(ClickAction(target: ActionTarget(
                kind: .element,
                label: "Search",
                role: "text field",
                description: nil,
                textNearby: nil
            ))),
            confidence: 0.91,
            requiresConfirmation: false
        )
        var receivedText: String?
        let consumer = TutorialActionConsumer { instruction in
            receivedText = instruction.text
            return "highlighted"
        }

        let result = await consumer.consume(step: step)

        XCTAssertEqual(result, "highlighted")
        XCTAssertEqual(receivedText, "Click the search field.")
    }
}
