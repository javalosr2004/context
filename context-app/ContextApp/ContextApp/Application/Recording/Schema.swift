import Foundation

/// Pinned schema version for recording bundles. Bump only in dedicated phases.
/// v2: adds `RecordedEventKind.type` and `RecordedEvent.typing` for sessionized
/// printable-key bursts. Discrete `key_down` events are still emitted for
/// shortcuts, control keys, and any keystroke that closes a burst.
let kRecordingSchemaVersion: Int = 2

enum RecordedEventKind: String, Codable {
    case click
    case scroll
    case keyDown = "key_down"
    case flags
    case type
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

/// One coalesced typing run: consecutive printable keystrokes with only
/// shift/caps modifiers, optionally interleaved with backspaces that mutate
/// the in-flight buffer. Closed by any non-printable key, any
/// cmd/ctrl/opt-modified key, mouse/scroll input, an idle gap, or stop().
struct TypingBurst: Codable, Equatable {
    let text: String
    let keyCount: Int
    let backspaceCount: Int
    let startFrameId: String?
    let endFrameId: String?
    let durationMs: Int

    enum CodingKeys: String, CodingKey {
        case text
        case keyCount = "key_count"
        case backspaceCount = "backspace_count"
        case startFrameId = "start_frame_id"
        case endFrameId = "end_frame_id"
        case durationMs = "duration_ms"
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
    let typing: TypingBurst?
    let frameId: String?
    let targetCropPath: String?
    let contextCropPath: String?

    init(
        id: String,
        timestampMs: Int64,
        kind: RecordedEventKind,
        cursor: Point,
        button: MouseButton? = nil,
        scroll: ScrollDelta? = nil,
        key: KeyStroke? = nil,
        typing: TypingBurst? = nil,
        frameId: String? = nil,
        targetCropPath: String? = nil,
        contextCropPath: String? = nil
    ) {
        self.id = id
        self.timestampMs = timestampMs
        self.kind = kind
        self.cursor = cursor
        self.button = button
        self.scroll = scroll
        self.key = key
        self.typing = typing
        self.frameId = frameId
        self.targetCropPath = targetCropPath
        self.contextCropPath = contextCropPath
    }

    enum CodingKeys: String, CodingKey {
        case id
        case timestampMs = "timestamp_ms"
        case kind
        case cursor
        case button
        case scroll
        case key
        case typing
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
