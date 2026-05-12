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

    func testBuildsBoundingBoxFromGuiActorNormalizedResponse() throws {
        let data = Data("""
        {
            "point":{"x":0.2,"y":0.3},
            "point_pixel":{"x":200,"y":300},
            "bbox":{"x1":0.1,"y1":0.2,"x2":0.4,"y2":0.6},
            "bbox_pixel":null,
            "bbox_score":0.9,
            "bbox_label":"button",
            "bbox_source":"detector",
            "image_size":{"width":1000,"height":800},
            "num_detections":1
        }
        """.utf8)
        let response = try JSONDecoder().decode(GuiActorResponse.self, from: data)
        let boundingBox = try XCTUnwrap(GroundingBoundingBox(guiActorResponse: response))

        XCTAssertEqual(boundingBox.x, 0.1, accuracy: 0.001)
        XCTAssertEqual(boundingBox.y, 0.2, accuracy: 0.001)
        XCTAssertEqual(boundingBox.width, 0.3, accuracy: 0.001)
        XCTAssertEqual(boundingBox.height, 0.4, accuracy: 0.001)
    }

    func testBuildsBoundingBoxFromGuiActorPixelResponse() throws {
        let data = Data("""
        {
            "point":{"x":0.2,"y":0.3},
            "point_pixel":{"x":200,"y":300},
            "bbox":null,
            "bbox_pixel":{"x1":100,"y1":160,"x2":400,"y2":480},
            "bbox_score":0.9,
            "bbox_label":"button",
            "bbox_source":"detector",
            "image_size":{"width":1000,"height":800},
            "num_detections":1
        }
        """.utf8)
        let response = try JSONDecoder().decode(GuiActorResponse.self, from: data)
        let boundingBox = try XCTUnwrap(GroundingBoundingBox(guiActorResponse: response))

        XCTAssertEqual(boundingBox.x, 0.1, accuracy: 0.001)
        XCTAssertEqual(boundingBox.y, 0.2, accuracy: 0.001)
        XCTAssertEqual(boundingBox.width, 0.3, accuracy: 0.001)
        XCTAssertEqual(boundingBox.height, 0.4, accuracy: 0.001)
    }

    func testBuildsPredictURLFromBaseEndpoint() {
        let endpoint = URL(string: "https://example.com")!

        XCTAssertEqual(GroundingClient.predictionURL(from: endpoint).absoluteString, "https://example.com/predict")
    }

    func testDoesNotAppendPredictTwice() {
        let endpoint = URL(string: "https://example.com/predict")!

        XCTAssertEqual(GroundingClient.predictionURL(from: endpoint).absoluteString, "https://example.com/predict")
    }
}
