import Foundation
import XCTest
@testable import ContextApp

final class TutorialPlanAPIClientTests: XCTestCase {
    func testPlanURLDerivesPlanRouteFromBaseURL() throws {
        let baseURL = try XCTUnwrap(URL(string: "http://localhost:8000"))

        XCTAssertEqual(
            TutorialPlanAPIClient.planURL(from: baseURL).absoluteString,
            "http://localhost:8000/tutorials/plan"
        )
    }

    func testPlanRequestDataBuildsMultipartFormRequest() throws {
        let baseURL = try XCTUnwrap(URL(string: "http://localhost:8000"))
        let submission = TutorialPlanSubmission(
            conversationID: "conversation-1",
            text: "Show me how to create a repo.",
            screenJPEGData: Data("jpeg-data".utf8)
        )

        let requestData = TutorialPlanAPIClient.planRequestData(
            baseURL: baseURL,
            submission: submission,
            boundary: "TestBoundary"
        )
        let body = try XCTUnwrap(String(data: requestData.body, encoding: .utf8))

        XCTAssertEqual(requestData.request.url?.absoluteString, "http://localhost:8000/tutorials/plan")
        XCTAssertEqual(requestData.request.httpMethod, "POST")
        XCTAssertEqual(
            requestData.request.value(forHTTPHeaderField: "Content-Type"),
            "multipart/form-data; boundary=TestBoundary"
        )
        XCTAssertEqual(requestData.request.value(forHTTPHeaderField: "Accept"), "application/json")
        XCTAssertTrue(body.contains("name=\"conversation_id\"\r\n\r\nconversation-1\r\n"))
        XCTAssertTrue(body.contains("name=\"text\"\r\n\r\nShow me how to create a repo.\r\n"))
        XCTAssertTrue(body.contains("name=\"images\"; filename=\"screen.jpg\""))
        XCTAssertTrue(body.contains("Content-Type: image/jpeg\r\n\r\njpeg-data\r\n"))
        XCTAssertTrue(body.hasSuffix("--TestBoundary--\r\n"))
    }
}
