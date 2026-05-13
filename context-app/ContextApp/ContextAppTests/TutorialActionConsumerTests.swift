import XCTest
@testable import ContextApp

final class TutorialActionConsumerTests: XCTestCase {
    func testGroundingInstructionTextIncludesTargetMetadata() {
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
            """
            Click the New repository button.
            Target kind: element
            Target label: New repository
            Target role: button
            Target description: Starts repository creation
            Nearby text: Repositories, Import
            """
        )
    }

    func testGroundingInstructionTextIncludesScrollMetadata() {
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
                direction: .down,
                amount: .medium,
                until: "Billing appears"
            )),
            confidence: 0.75,
            requiresConfirmation: false
        )

        XCTAssertEqual(
            TutorialActionConsumer.groundingInstructionText(for: step),
            """
            Scroll down to the billing section.
            Target kind: window
            Target label: Settings
            Target description: The app settings window
            Scroll direction: down
            Scroll amount: medium
            Scroll until: Billing appears
            """
        )
    }

    func testConsumeDispatchesGroundingInstruction() async {
        let step = TutorialStep(
            stepId: "step-3",
            instruction: "Press Command K.",
            action: .pressKey(PressKeyAction(keys: ["Command", "K"])),
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
        XCTAssertEqual(
            receivedText,
            """
            Press Command K.
            Keys: Command + K
            """
        )
    }
}
