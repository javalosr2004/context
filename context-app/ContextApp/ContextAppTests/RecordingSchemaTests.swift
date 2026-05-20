import XCTest
@testable import ContextApp

final class RecordingSchemaTests: XCTestCase {
    func testRecordedEventRoundTripsSnakeCaseJSON() throws {
        let event = RecordedEvent(
            id: "abc",
            timestampMs: 1715000000123,
            kind: .click,
            cursor: Point(x: 812, y: 433),
            button: .left,
            scroll: nil,
            key: nil,
            frameId: "f00f00f00f00",
            targetCropPath: "crops/abc_target.jpg",
            contextCropPath: "crops/abc_context.jpg"
        )
        let data = try JSONEncoder().encode(event)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"timestamp_ms\":1715000000123"))
        XCTAssertTrue(json.contains("\"frame_id\":\"f00f00f00f00\""))
        XCTAssertTrue(json.contains("\"target_crop_path\""))
        let decoded = try JSONDecoder().decode(RecordedEvent.self, from: data)
        XCTAssertEqual(decoded.id, "abc")
        XCTAssertEqual(decoded.kind, .click)
        XCTAssertEqual(decoded.button, .left)
    }

    func testManifestEncodesGoalAndSchemaVersion() throws {
        let manifest = Manifest(
            recordingId: "uuid",
            schemaVersion: kRecordingSchemaVersion,
            startedAtMs: 1,
            endedAtMs: 2,
            display: DisplayInfo(x: 0, y: 0, width: 100, height: 50, scaleFactor: 2.0),
            goal: Goal(text: "test workflow", enteredAtMs: 0),
            appVersion: "0.1.0",
            aborted: false
        )
        let data = try JSONEncoder().encode(manifest)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertTrue(json.contains("\"schema_version\":1"))
        XCTAssertTrue(json.contains("\"scale_factor\":2"))
        XCTAssertTrue(json.contains("\"goal\":{"))
    }

    func testBundleLayoutPathsAreRelativeToRoot() {
        let root = URL(fileURLWithPath: "/tmp/recording-x")
        let layout = BundleLayout(root: root)
        XCTAssertEqual(layout.manifestURL.lastPathComponent, "manifest.json")
        XCTAssertEqual(layout.eventsURL.lastPathComponent, "events.jsonl")
        XCTAssertEqual(layout.framesDir.lastPathComponent, "frames")
        XCTAssertEqual(layout.frameURL(frameId: "abc").lastPathComponent, "abc.jpg")
        XCTAssertEqual(layout.targetCropURL(eventId: "evt").lastPathComponent, "evt_target.jpg")
        XCTAssertEqual(layout.contextCropURL(eventId: "evt").lastPathComponent, "evt_context.jpg")
    }
}

final class GoalValidatorTests: XCTestCase {
    func testRejectsTooShort() {
        if case .failure(.tooShort) = GoalValidator.validate("hi") {} else { XCTFail("expected tooShort") }
    }

    func testRejectsBlank() {
        if case .failure(.tooShort) = GoalValidator.validate("   ") {} else { XCTFail("expected tooShort") }
    }

    func testRejectsTooLong() {
        let long = String(repeating: "x", count: 281)
        if case .failure(.tooLong) = GoalValidator.validate(long) {} else { XCTFail("expected tooLong") }
    }

    func testAcceptsTrimmed() {
        switch GoalValidator.validate("  reply to sarah about Q3 hiring  ") {
        case .success(let v): XCTAssertEqual(v, "reply to sarah about Q3 hiring")
        case .failure: XCTFail("expected success")
        }
    }
}

final class ContinuousFrameStreamHashTests: XCTestCase {
    func testShortHashIsDeterministicAnd12Chars() {
        let a = ContinuousFrameStream.shortHash(of: Data([0x00, 0x01, 0x02]))
        let b = ContinuousFrameStream.shortHash(of: Data([0x00, 0x01, 0x02]))
        XCTAssertEqual(a, b)
        XCTAssertEqual(a.count, 12)
        let c = ContinuousFrameStream.shortHash(of: Data([0x00, 0x01, 0x03]))
        XCTAssertNotEqual(a, c)
    }
}

final class ModifierFlagsFormatterTests: XCTestCase {
    func testNamesIncludeOnlySetFlags() {
        let flags: CGEventFlags = [.maskCommand, .maskShift]
        let names = ModifierFlagsFormatter.names(from: flags)
        XCTAssertEqual(Set(names), Set(["cmd", "shift"]))
    }

    func testEmptyForNoFlags() {
        XCTAssertEqual(ModifierFlagsFormatter.names(from: CGEventFlags()), [])
    }
}
