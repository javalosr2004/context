import XCTest
@testable import ContextApp

final class GroundingBoundingBoxTests: XCTestCase {
    func testRejectsInvalidValues() {
        XCTAssertNil(GroundingBoundingBox(values: [0.1, 0.2, 0.3]))
        XCTAssertNil(GroundingBoundingBox(values: [-0.1, 0.2, 0.3, 0.4]))
        XCTAssertNil(GroundingBoundingBox(values: [0.1, 0.2, 0, 0.4]))
        XCTAssertNil(GroundingBoundingBox(values: [0.1, 0.2, 0.3, -0.1]))
        XCTAssertNil(GroundingBoundingBox(values: [0.8, 0.2, 0.3, 0.4]))
        XCTAssertNil(GroundingBoundingBox(values: [0.1, 0.8, 0.3, 0.4]))
        XCTAssertNil(GroundingBoundingBox(values: [Double.nan, 0.2, 0.3, 0.4]))
    }

    func testMapsNormalizedTopLeftCoordinatesToBottomLeftScreenCoordinates() throws {
        let bbox = try XCTUnwrap(GroundingBoundingBox(values: [0.05, 0.2, 0.15, 0.4]))
        let rect = try XCTUnwrap(bbox.screenRect(
            captureSize: CGSize(width: 2000, height: 1000),
            screenFrame: CGRect(x: 10, y: 20, width: 1000, height: 500)
        ))

        XCTAssertEqual(rect.origin.x, 60, accuracy: 0.001)
        XCTAssertEqual(rect.origin.y, 220, accuracy: 0.001)
        XCTAssertEqual(rect.width, 150, accuracy: 0.001)
        XCTAssertEqual(rect.height, 200, accuracy: 0.001)
    }

    func testDecodesSnakeCaseEndpointResponse() throws {
        let data = Data(#"{"bounding_box":[0.1,0.2,0.3,0.4]}"#.utf8)
        let response = try JSONDecoder().decode(GroundingResponse.self, from: data)

        XCTAssertEqual(response.boundingBox, GroundingBoundingBox(values: [0.1, 0.2, 0.3, 0.4]))
    }
}
