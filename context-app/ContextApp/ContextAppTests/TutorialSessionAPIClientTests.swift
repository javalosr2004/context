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
            confirmed: false,
            note: "Wrong target",
            screen: TutorialSessionScreenSnapshot(
                mimeType: "image/jpeg",
                dataBase64: "abc123"
            )
        )

        let data = try JSONEncoder().encode(event)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let screen = try XCTUnwrap(object["screen"] as? [String: Any])

        XCTAssertEqual(object["type"] as? String, "user_confirmation")
        XCTAssertEqual(object["step_id"] as? String, "step_001")
        XCTAssertEqual(object["confirmed"] as? Bool, false)
        XCTAssertEqual(object["note"] as? String, "Wrong target")
        XCTAssertEqual(screen["mime_type"] as? String, "image/jpeg")
        XCTAssertEqual(screen["data_base64"] as? String, "abc123")
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
                "action": {
                  "type": "click",
                  "target": {
                    "kind": "element",
                    "label": "Message",
                    "role": "text field"
                  }
                },
                "confidence": 0.93,
                "requires_confirmation": false
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
            "action": {
              "type": "click",
              "target": {
                "kind": "element",
                "label": "Message",
                "role": "text field",
                "description": "A rounded input at the bottom of the chat."
              }
            },
            "confidence": 0.93,
            "requires_confirmation": false
          }
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .tutorialAction(let step) = event else {
            return XCTFail("Expected tutorialAction, got \(event)")
        }
        XCTAssertEqual(step.stepId, "step_001")
        XCTAssertEqual(step.action.type, "click")
    }

    func testServerEventDecodingTutorialActionDelta() throws {
        let data = Data("""
        {
          "type": "tutorial_action_delta",
          "step": {
            "step_id": "step_001",
            "instruction": "Click the message field.",
            "action": {
              "type": "click",
              "target": {
                "kind": "element",
                "label": "Message",
                "role": "text field",
                "description": "A rounded input at the bottom of the chat."
              }
            },
            "confidence": 0.93,
            "requires_confirmation": false
          }
        }
        """.utf8)

        let event = try JSONDecoder().decode(TutorialSessionServerEvent.self, from: data)

        guard case .tutorialActionDelta(let step) = event else {
            return XCTFail("Expected tutorialActionDelta, got \(event)")
        }
        XCTAssertEqual(step.stepId, "step_001")
        XCTAssertEqual(step.action.type, "click")
    }

    func testStatusLabelsAndBusyStates() {
        XCTAssertEqual(TutorialSessionUIStatus.preparingScreen.label, "Preparing screen")
        XCTAssertTrue(TutorialSessionUIStatus.sending.isBusy)
        XCTAssertFalse(TutorialSessionUIStatus.needsContext.isBusy)
    }
}
