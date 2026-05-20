import XCTest
@testable import ContextApp

final class EnrichmentUploaderTests: XCTestCase {
    func testMultipartBodyContainsFileBytesAndBoundary() {
        let payload = Data([0x01, 0x02, 0x03])
        let body = EnrichmentUploader.multipartBody(
            boundary: "BOUND",
            fieldName: "bundle",
            fileName: "bundle.zip",
            data: payload
        )
        let text = String(data: body, encoding: .ascii) ?? ""
        XCTAssertTrue(text.contains("--BOUND\r\n"))
        XCTAssertTrue(text.contains("Content-Disposition: form-data; name=\"bundle\"; filename=\"bundle.zip\""))
        XCTAssertTrue(text.contains("Content-Type: application/zip"))
        XCTAssertTrue(text.hasSuffix("--BOUND--\r\n"))
        XCTAssertTrue(body.range(of: payload) != nil)
    }

    func testRemoteRecordingDecodesSnakeCase() throws {
        let json = #"{"recording_id":"abc","status":"pending","total_events":7}"#
        let r = try JSONDecoder().decode(RemoteRecording.self, from: Data(json.utf8))
        XCTAssertEqual(r.id, "abc")
        XCTAssertEqual(r.status, "pending")
        XCTAssertEqual(r.totalEvents, 7)
    }

    func testBundleZipperProducesNonEmptyZip() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("bundle-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        try Data("hello".utf8).write(to: tmp.appendingPathComponent("manifest.json"))
        try Data("world".utf8).write(to: tmp.appendingPathComponent("events.jsonl"))
        defer { try? FileManager.default.removeItem(at: tmp) }

        let dst = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).zip")
        defer { try? FileManager.default.removeItem(at: dst) }
        try BundleZipper.zip(directory: tmp, to: dst)
        let data = try Data(contentsOf: dst)
        XCTAssertGreaterThan(data.count, 0)
        // ZIP local file header magic = 0x04034b50 (little endian).
        XCTAssertEqual(data.prefix(4), Data([0x50, 0x4B, 0x03, 0x04]))
    }
}
