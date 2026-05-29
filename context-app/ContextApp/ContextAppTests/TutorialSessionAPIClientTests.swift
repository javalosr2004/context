import XCTest
@testable import ContextApp

final class TutorialSessionAPIClientTests: XCTestCase {
    func testSocketURLConvertsHTTPToWebSocket() throws {
        let baseURL = try XCTUnwrap(URL(string: "http://localhost:8000"))

        let url = try TutorialSessionAPIClient.socketURL(from: baseURL, sessionID: "session-1")

        XCTAssertEqual(url.absoluteString, "ws://localhost:8000/tutorial-sessions/session-1/socket")
    }

    func testSocketURLConvertsHTTPSToSecureWebSocket() throws {
        let baseURL = try XCTUnwrap(URL(string: "https://api.example.com"))

        let url = try TutorialSessionAPIClient.socketURL(from: baseURL, sessionID: "session-1")

        XCTAssertEqual(url.absoluteString, "wss://api.example.com/tutorial-sessions/session-1/socket")
    }

    func testSocketURLRejectsUnsupportedScheme() throws {
        let baseURL = try XCTUnwrap(URL(string: "file:///tmp/context"))

        XCTAssertThrowsError(try TutorialSessionAPIClient.socketURL(from: baseURL, sessionID: "session-1"))
    }

    func testClientEventEncodingUsesWireKeys() throws {
        let event = TutorialSessionClientEvent.userConfirmation(
            stepID: "step_001",
            actionIndex: 1,
            confirmed: false,
            note: "Wrong target"
        )

        let data = try JSONEncoder().encode(event)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])

        XCTAssertEqual(object["type"] as? String, "user_confirmation")
        XCTAssertEqual(object["step_id"] as? String, "step_001")
        XCTAssertEqual(object["action_index"] as? Int, 1)
        XCTAssertEqual(object["confirmed"] as? Bool, false)
        XCTAssertEqual(object["note"] as? String, "Wrong target")
        XCTAssertNil(object["screen"])
    }

    func testUserCompletionResponseEncodingUsesWireKeys() throws {
        let confirm = TutorialSessionClientEvent.userCompletionResponse(
            confirmed: true,
            note: nil
        )
        let confirmData = try JSONEncoder().encode(confirm)
        let confirmObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: confirmData) as? [String: Any]
        )
        XCTAssertEqual(confirmObject["type"] as? String, "user_completion_response")
        XCTAssertEqual(confirmObject["confirmed"] as? Bool, true)
        XCTAssertNil(confirmObject["note"])

        let reject = TutorialSessionClientEvent.userCompletionResponse(
            confirmed: false,
            note: "Still need to save."
        )
        let rejectData = try JSONEncoder().encode(reject)
        let rejectObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: rejectData) as? [String: Any]
        )
        XCTAssertEqual(rejectObject["confirmed"] as? Bool, false)
        XCTAssertEqual(rejectObject["note"] as? String, "Still need to save.")
    }

    func testServerEventDecodingCompletionProposed() throws {
        let data = Data("""
        {
          "type": "completion_proposed",
          "reason": "Confirmation banner is visible.",
          "source": "llm"
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .completionProposed(let reason, let source) = event else {
            return XCTFail("Expected completionProposed, got \(event)")
        }
        XCTAssertEqual(reason, "Confirmation banner is visible.")
        XCTAssertEqual(source, "llm")
    }

    func testUserScreenEventEncodingUsesWireKeys() throws {
        let event = TutorialSessionClientEvent.userScreen(
            requestID: "screen_001",
            screen: TutorialSessionScreenSnapshot(
                mimeType: "image/jpeg",
                dataBase64: "abc123"
            )
        )

        let data = try JSONEncoder().encode(event)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let screen = try XCTUnwrap(object["screen"] as? [String: Any])

        XCTAssertEqual(object["type"] as? String, "user_screen")
        XCTAssertEqual(object["request_id"] as? String, "screen_001")
        XCTAssertEqual(screen["mime_type"] as? String, "image/jpeg")
        XCTAssertEqual(screen["data_base64"] as? String, "abc123")
    }

    func testUserMessageEventEncodingIncludesUploadedImagesWhenPresent() throws {
        let event = TutorialSessionClientEvent.userMessage(
            text: "Use this reference.",
            uploadedImages: [
                TutorialSessionScreenSnapshot(
                    mimeType: "image/png",
                    dataBase64: "abc123"
                )
            ]
        )

        let data = try JSONEncoder().encode(event)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let uploadedImages = try XCTUnwrap(object["uploaded_images"] as? [[String: Any]])

        XCTAssertEqual(object["type"] as? String, "user_message")
        XCTAssertEqual(object["text"] as? String, "Use this reference.")
        XCTAssertEqual(uploadedImages.count, 1)
        XCTAssertEqual(uploadedImages[0]["mime_type"] as? String, "image/png")
        XCTAssertEqual(uploadedImages[0]["data_base64"] as? String, "abc123")
    }

    func testServerEventDecodingPlanReady() throws {
        let data = Data("""
        {
          "type": "plan_ready",
          "plan": {
            "schema_version": "tutorial_plan.v1",
            "goal": "Send a message",
            "summary": "Open chat and send text.",
            "steps": [
              {
                "step_id": "step_001",
                "instruction": "Click the message field.",
                "actions": [{
                  "type": "click",
                  "target": {
                    "kind": "element",
                    "label": "Message",
                    "role": "text field"
                  },
                  "requires_confirmation": false
                }],
                "confidence": 0.93
              }
            ]
          }
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .planReady(let plan) = event else {
            return XCTFail("Expected planReady, got \(event)")
        }
        XCTAssertEqual(plan.schemaVersion, "tutorial_plan.v1")
        XCTAssertEqual(plan.steps.first?.stepId, "step_001")
    }

    func testServerEventDecodingTutorialAction() throws {
        let data = Data("""
        {
          "type": "tutorial_action",
          "step": {
            "step_id": "step_001",
            "instruction": "Click the message field.",
            "actions": [{
              "type": "click",
              "target": {
                "kind": "element",
                "label": "Message",
                "role": "text field",
                "description": "A rounded input at the bottom of the chat."
              },
              "requires_confirmation": false
            }],
            "confidence": 0.93
          }
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .tutorialAction(let step) = event else {
            return XCTFail("Expected tutorialAction, got \(event)")
        }
        XCTAssertEqual(step.stepId, "step_001")
        XCTAssertEqual(step.actions.first?.type, "click")
    }

    func testServerEventDecodingTextResponse() throws {
        let data = Data("""
        {
          "type": "text_response",
          "text": "RunPod is a cloud GPU platform."
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .textResponse(let text) = event else {
            return XCTFail("Expected textResponse, got \(event)")
        }
        XCTAssertEqual(text, "RunPod is a cloud GPU platform.")
    }

    func testServerEventDecodingTutorialTextDelta() throws {
        let data = Data("""
        {
          "type": "tutorial_text_delta",
          "text": "RunPod"
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .textDelta(let text) = event else {
            return XCTFail("Expected textDelta, got \(event)")
        }
        XCTAssertEqual(text, "RunPod")
    }

    func testServerEventDecodingPlanStepPreview() throws {
        let data = Data("""
        {
          "type": "plan_step_preview",
          "index": 2,
          "instruction": "Enter the repository name.",
          "confidence": 0.93
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .planStepPreview(let index, let instruction, let confidence) = event else {
            return XCTFail("Expected planStepPreview, got \(event)")
        }
        XCTAssertEqual(index, 2)
        XCTAssertEqual(instruction, "Enter the repository name.")
        XCTAssertEqual(confidence, 0.93, accuracy: 0.0001)
    }

    func testServerEventDecodingPlanStreamReset() throws {
        let data = Data(#"{ "type": "plan_stream_reset" }"#.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .planStreamReset = event else {
            return XCTFail("Expected planStreamReset, got \(event)")
        }
    }

    func testStatusLabelsAndBusyStates() {
        XCTAssertEqual(TutorialSessionUIStatus.preparingScreen.label, "Preparing screen")
        XCTAssertTrue(TutorialSessionUIStatus.sending.isBusy)
        XCTAssertFalse(TutorialSessionUIStatus.awaitingConfirmation.isBusy)
    }

    func testServerEventDecodingVerificationHint() throws {
        let data = Data("""
        {
          "type": "verification_hint",
          "step_id": "step_042",
          "verdict": "unsure",
          "reason": "title bar text differs from expected",
          "auto_replanning": false
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .verificationHint(let stepID, let verdict, let reason, let autoReplanning) = event else {
            return XCTFail("Expected verificationHint, got \(event)")
        }
        XCTAssertEqual(stepID, "step_042")
        XCTAssertEqual(verdict, .unsure)
        XCTAssertEqual(reason, "title bar text differs from expected")
        XCTAssertFalse(autoReplanning)
    }

    func testServerEventDecodingVerificationHintDiverged() throws {
        let data = Data("""
        {
          "type": "verification_hint",
          "step_id": "step_007",
          "verdict": "diverged",
          "reason": "wrong app in foreground",
          "auto_replanning": true
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .verificationHint(_, let verdict, _, let autoReplanning) = event else {
            return XCTFail("Expected verificationHint, got \(event)")
        }
        XCTAssertEqual(verdict, .diverged)
        XCTAssertTrue(autoReplanning)
    }

    func testUserHintResponseEncodingUsesWireKeys() throws {
        let event = TutorialSessionClientEvent.userHintResponse(
            stepID: "step_042",
            action: .acknowledgeOff
        )

        let data = try JSONEncoder().encode(event)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])

        XCTAssertEqual(object["type"] as? String, "user_hint_response")
        XCTAssertEqual(object["step_id"] as? String, "step_042")
        XCTAssertEqual(object["action"] as? String, "acknowledge_off")
    }

    func testUserHintResponseEncodesAllActionVariants() throws {
        let actions: [(TutorialHintResponseAction, String)] = [
            (.acknowledgeOff, "acknowledge_off"),
            (.dismiss, "dismiss"),
            (.timeout, "timeout"),
        ]
        for (action, wireValue) in actions {
            let event = TutorialSessionClientEvent.userHintResponse(
                stepID: "step_001",
                action: action
            )
            let data = try JSONEncoder().encode(event)
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(object["action"] as? String, wireValue, "wire value mismatch for \(action)")
        }
    }
}
