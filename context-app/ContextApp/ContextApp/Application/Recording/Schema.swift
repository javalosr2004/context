import Foundation

/// Pinned schema version for recording bundles. Bump only in dedicated phases.
let kRecordingSchemaVersion: Int = 1

enum RecordedEventKind: String, Codable {
    case click
    case scroll
    case keyDown = "key_down"
    case flags
}

enum MouseButton: String, Codable {
    case left
    case right
    case other
}

struct Point: Codable, Equatable {
    let x: Int
    let y: Int
}

struct ScrollDelta: Codable, Equatable {
    let startFrameId: String
    let endFrameId: String
    let dx: Int
    let dy: Int
    let durationMs: Int
    let direction: String

    enum CodingKeys: String, CodingKey {
        case startFrameId = "start_frame_id"
        case endFrameId = "end_frame_id"
        case dx
        case dy
        case durationMs = "duration_ms"
        case direction
    }
}

struct KeyStroke: Codable, Equatable {
    let keyCode: Int
    let characters: String?
    let modifiers: [String]

    enum CodingKeys: String, CodingKey {
        case keyCode = "key_code"
        case characters
        case modifiers
    }
}

struct RecordedEvent: Codable {
    let id: String
    let timestampMs: Int64
    let kind: RecordedEventKind
    let cursor: Point
    let button: MouseButton?
    let scroll: ScrollDelta?
    let key: KeyStroke?
    let frameId: String?
    let targetCropPath: String?
    let contextCropPath: String?

    enum CodingKeys: String, CodingKey {
        case id
        case timestampMs = "timestamp_ms"
        case kind
        case cursor
        case button
        case scroll
        case key
        case frameId = "frame_id"
        case targetCropPath = "target_crop_path"
        case contextCropPath = "context_crop_path"
    }
}

struct Goal: Codable, Equatable {
    let text: String
    let enteredAtMs: Int64

    enum CodingKeys: String, CodingKey {
        case text
        case enteredAtMs = "entered_at_ms"
    }
}

struct DisplayInfo: Codable, Equatable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let scaleFactor: Double

    enum CodingKeys: String, CodingKey {
        case x
        case y
        case width
        case height
        case scaleFactor = "scale_factor"
    }
}

struct Manifest: Codable {
    let recordingId: String
    let schemaVersion: Int
    let startedAtMs: Int64
    var endedAtMs: Int64?
    let display: DisplayInfo
    let goal: Goal
    let appVersion: String
    var aborted: Bool

    enum CodingKeys: String, CodingKey {
        case recordingId = "recording_id"
        case schemaVersion = "schema_version"
        case startedAtMs = "started_at_ms"
        case endedAtMs = "ended_at_ms"
        case display
        case goal
        case appVersion = "app_version"
        case aborted
    }
}

/// On-disk layout for a single recording bundle.
struct BundleLayout {
    let root: URL

    var manifestURL: URL { root.appendingPathComponent("manifest.json") }
    var eventsURL: URL { root.appendingPathComponent("events.jsonl") }
    var framesDir: URL { root.appendingPathComponent("frames") }
    var cropsDir: URL { root.appendingPathComponent("crops") }

    func frameURL(frameId: String) -> URL {
        framesDir.appendingPathComponent("\(frameId).jpg")
    }

    func targetCropURL(eventId: String) -> URL {
        cropsDir.appendingPathComponent("\(eventId)_target.jpg")
    }

    func contextCropURL(eventId: String) -> URL {
        cropsDir.appendingPathComponent("\(eventId)_context.jpg")
    }
}
