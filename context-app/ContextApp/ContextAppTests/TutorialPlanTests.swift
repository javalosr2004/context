import XCTest
@testable import ContextApp

final class TutorialPlanTests: XCTestCase {
    func testDecodesSupportedTutorialPlan() throws {
        let data = Data("""
        {
          "schema_version": "tutorial_plan.v1",
          "goal": "Send a message",
          "summary": "Open chat and send text.",
          "steps": [
            {
              "step_id": "step-1",
              "instruction": "Click the message field.",
              "actions": [{
                "type": "click",
                "target": {
                  "kind": "element",
                  "label": "Message",
                  "role": "text field",
                  "description": "The chat composer field",
                  "text_nearby": ["Send"]
                },
                "requires_confirmation": false
              }],
              "confidence": 0.93
            }
          ]
        }
        """.utf8)

        let plan = try JSONDecoder().decode(TutorialPlan.self, from: data)

        XCTAssertEqual(plan.schemaVersion, "tutorial_plan.v1")
        XCTAssertEqual(plan.steps.first?.stepId, "step-1")
        XCTAssertEqual(plan.steps.first?.actions.first?.type, "click")
        XCTAssertEqual(plan.steps.first?.actions.first?.requiresConfirmation, false)
    }

    func testRejectsUnsupportedSchemaVersion() {
        let data = Data("""
        {
          "schema_version": "tutorial_plan.v2",
          "goal": "Send a message",
          "summary": "Open chat and send text.",
          "steps": []
        }
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder().decode(TutorialPlan.self, from: data)) { error in
            guard case DecodingError.dataCorrupted(let context) = error else {
                return XCTFail("Expected dataCorrupted, got \(error)")
            }

            XCTAssertTrue(context.debugDescription.contains("Unsupported tutorial plan schema_version"))
        }
    }

    func testRejectsUnknownActionType() {
        let data = Data("""
        {
          "schema_version": "tutorial_plan.v1",
          "goal": "Send a message",
          "summary": "Open chat and send text.",
          "steps": [
            {
              "step_id": "step-1",
              "instruction": "Tap the field.",
              "actions": [{ "type": "tap", "requires_confirmation": true }],
              "confidence": 0.5
            }
          ]
        }
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder().decode(TutorialPlan.self, from: data)) { error in
            guard case DecodingError.dataCorrupted(let context) = error else {
                return XCTFail("Expected dataCorrupted, got \(error)")
            }

            XCTAssertTrue(context.debugDescription.contains("Unknown tutorial action type 'tap'"))
        }
    }

    func testActionEncodingPreservesDiscriminatorKeys() throws {
        let action = TutorialAction.pressKey(PressKeyAction(key: "command+return", requiresConfirmation: false))
        let data = try JSONEncoder().encode(action)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(object?["type"] as? String, "press_key")
        XCTAssertEqual(object?["key"] as? String, "command+return")
        XCTAssertEqual(object?["requires_confirmation"] as? Bool, false)
    }

    func testStepJSONFormatterIncludesEntireStepPayload() throws {
        let step = TutorialStep(
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

        let json = TutorialStepJSONFormatter.displayString(for: step)
        let object = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]
        let actions = object?["actions"] as? [[String: Any]]
        let action = actions?.first
        let target = action?["target"] as? [String: Any]

        XCTAssertEqual(object?.keys.sorted(), [
            "actions",
            "confidence",
            "instruction",
            "step_id"
        ])
        XCTAssertEqual(object?["step_id"] as? String, "step-1")
        XCTAssertEqual(object?["instruction"] as? String, "Click the message field.")
        XCTAssertEqual(object?["confidence"] as? Double, 0.93)
        XCTAssertEqual(action?["type"] as? String, "click")
        XCTAssertEqual(action?["requires_confirmation"] as? Bool, false)
        XCTAssertEqual(target?["label"] as? String, "Message")
        XCTAssertEqual(target?["text_nearby"] as? [String], ["Send"])
    }

    func testDecodesFlatWaitAction() throws {
        let data = Data("""
        {
          "type": "wait",
          "duration_ms": 750,
          "requires_confirmation": false
        }
        """.utf8)

        let action = try JSONDecoder().decode(TutorialAction.self, from: data)

        XCTAssertEqual(action, .wait(WaitAction(durationMs: 750, requiresConfirmation: false)))
    }

    func testDecodesFlatConfirmAction() throws {
        let data = Data("""
        {
          "type": "confirm",
          "requires_confirmation": true
        }
        """.utf8)

        let action = try JSONDecoder().decode(TutorialAction.self, from: data)

        XCTAssertEqual(action, .confirm(ConfirmAction()))
    }

    func testDecodingMissingRequiredPayloadFieldThrowsKeyNotFound() {
        let data = Data("""
        {
          "type": "type",
          "target": { "kind": "element", "label": "Message" },
          "requires_confirmation": true
        }
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder().decode(TutorialAction.self, from: data)) { error in
            guard case DecodingError.keyNotFound(let key, _) = error else {
                return XCTFail("Expected keyNotFound, got \(error)")
            }

            XCTAssertEqual(key.stringValue, "text")
        }
    }
}
