import XCTest
@testable import ContextApp

final class GroundingBoundingBoxTests: XCTestCase {
    func testRejectsInvalidValues() {
        XCTAssertNil(GroundingBoundingBox(values: [1, 2, 3]))
        XCTAssertNil(GroundingBoundingBox(values: [1, 2, 0, 4]))
        XCTAssertNil(GroundingBoundingBox(values: [1, 2, 3, -1]))
        XCTAssertNil(GroundingBoundingBox(values: [Double.nan, 2, 3, 4]))
    }

    func testMapsTopLeftCaptureCoordinatesToBottomLeftScreenCoordinates() throws {
        let bbox = try XCTUnwrap(GroundingBoundingBox(values: [100, 200, 300, 400]))
        let rect = try XCTUnwrap(bbox.screenRect(
            captureSize: CGSize(width: 2000, height: 1000),
            screenFrame: CGRect(x: 10, y: 20, width: 1000, height: 500)
        ))

        XCTAssertEqual(rect.origin.x, 60)
        XCTAssertEqual(rect.origin.y, 220)
        XCTAssertEqual(rect.width, 150)
        XCTAssertEqual(rect.height, 200)
    }

    func testDecodesSnakeCaseEndpointResponse() throws {
        let data = Data(#"{"bounding_box":[10,20,30,40]}"#.utf8)
        let response = try JSONDecoder().decode(GroundingResponse.self, from: data)

        XCTAssertEqual(response.boundingBox, GroundingBoundingBox(values: [10, 20, 30, 40]))
    }
}
