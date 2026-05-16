import XCTest
@testable import ContextApp

final class TutorialPlanDisplayTests: XCTestCase {
    func testDefaultsToFirstStepWhenNoCurrentStepIsReady() {
        let plan = tutorialPlan(steps: [
            step(id: "step-1", instruction: "Open the address bar.", action: .pressKey(PressKeyAction(key: "command+l"))),
            step(id: "step-2", instruction: "Click Sign In.", action: .click(target("Sign In")))
        ])

        let display = TutorialPlanDisplay.make(from: plan, currentStepID: nil)

        XCTAssertEqual(display.currentStep?.step.stepId, "step-1")
        XCTAssertEqual(display.progressText, "Step 1 of 2")
        XCTAssertEqual(display.upcomingSteps.map(\.step.stepId), ["step-2"])
    }

    func testUsesCurrentStepIDForProgressAndUpcomingSteps() {
        let plan = tutorialPlan(steps: [
            step(id: "step-1", instruction: "Open the address bar.", action: .pressKey(PressKeyAction(key: "command+l"))),
            step(id: "step-2", instruction: "Enter the Runpod dashboard URL.", action: .type(TypeAction(target: nil, text: "https://runpod.io"))),
            step(id: "step-3", instruction: "Click Sign In.", action: .click(target("Sign In")))
        ])

        let display = TutorialPlanDisplay.make(from: plan, currentStepID: "step-2")

        XCTAssertEqual(display.currentStep?.step.stepId, "step-2")
        XCTAssertEqual(display.progressText, "Step 2 of 3")
        XCTAssertEqual(display.upcomingSteps.map(\.step.stepId), ["step-3"])
    }

    func testNormalizesNoisyAddressBarTypingStepsForDisplay() {
        let plan = tutorialPlan(steps: [
            step(id: "step-1", instruction: "Type the Runpod dashboard URL into the address bar.", action: .type(TypeAction(target: nil, text: "https://runpod.io"))),
            step(id: "step-2", instruction: "Replace the current address bar text with the Runpod dashboard URL.", action: .type(TypeAction(target: nil, text: "https://runpod.io"))),
            step(id: "step-3", instruction: "Click Sign In.", action: .click(target("Sign In")))
        ])

        let display = TutorialPlanDisplay.make(from: plan, currentStepID: "step-1")

        XCTAssertEqual(display.currentStep?.title, "Enter the Runpod dashboard URL")
        XCTAssertEqual(display.upcomingSteps.map(\.title), ["Click Sign In"])
    }

    func testLimitsUpcomingSteps() {
        let plan = tutorialPlan(steps: [
            step(id: "step-1", instruction: "Open the address bar.", action: .pressKey(PressKeyAction(key: "command+l"))),
            step(id: "step-2", instruction: "Enter URL.", action: .type(TypeAction(target: nil, text: "https://runpod.io"))),
            step(id: "step-3", instruction: "Click Sign In.", action: .click(target("Sign In"))),
            step(id: "step-4", instruction: "Dismiss cookie banner.", action: .click(target("Cookie banner")))
        ])

        let display = TutorialPlanDisplay.make(from: plan, currentStepID: "step-1", upcomingLimit: 2)

        XCTAssertEqual(display.upcomingSteps.map(\.step.stepId), ["step-2", "step-3"])
    }

    private func tutorialPlan(steps: [TutorialStep]) -> TutorialPlan {
        TutorialPlan(
            goal: "Runpod setup",
            summary: "Follow the streamed tutorial actions.",
            steps: steps
        )
    }

    private func step(id: String, instruction: String, action: TutorialAction) -> TutorialStep {
        TutorialStep(
            stepId: id,
            instruction: instruction,
            action: action,
            confidence: 0.92,
            requiresConfirmation: false
        )
    }

    private func target(_ label: String) -> ClickAction {
        ClickAction(target: ActionTarget(
            kind: .element,
            label: label,
            role: "button",
            description: label,
            textNearby: nil
        ))
    }
}
