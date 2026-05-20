import AppKit
import Foundation
import os

enum RecordingSessionState {
    case idle
    case recording
    case stopping
}

enum RecordingSessionError: LocalizedError {
    case alreadyRecording
    case notRecording
    case permissionsDenied(needs: RecordingPermissions)
    case bundleCreationFailed(Error)

    var errorDescription: String? {
        switch self {
        case .alreadyRecording:
            return "A recording is already in progress."
        case .notRecording:
            return "No recording is in progress."
        case .permissionsDenied(let p):
            if p.needsBoth { return "Screen Recording and Accessibility permissions are required." }
            if p.needsScreen { return "Screen Recording permission is required." }
            return "Accessibility permission is required for input capture."
        case .bundleCreationFailed(let e):
            return "Could not create recording bundle: \(e.localizedDescription)"
        }
    }
}

@MainActor
final class RecordingSession {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "Session")

    private let frameStream: ContinuousFrameStream
    private let eventTap: InputEventTap
    private let appVersion: String
    private let baseDir: URL

    private var state: RecordingSessionState = .idle
    private var bundle: BundleLayout?
    private var manifest: Manifest?
    private var eventsFileHandle: FileHandle?
    private var persistedFrameIds: Set<String> = []
    private let writeQueue = DispatchQueue(label: "context.recording.writes")

    /// Allows Phase 2+ to intercept built events before they are written.
    /// Returns an array (typically 0 or 1, scroll sessionizer may emit later).
    var eventTransform: ((RecordedEvent, CapturedFrame?) -> [RecordedEvent])?

    var isRecording: Bool { state != .idle }
    var currentBundle: BundleLayout? { bundle }

    init(
        frameStream: ContinuousFrameStream = ContinuousFrameStream(),
        eventTap: InputEventTap = InputEventTap(),
        appVersion: String = Bundle.main.shortVersionString,
        baseDirectory: URL = RecordingSession.defaultBaseDirectory()
    ) {
        self.frameStream = frameStream
        self.eventTap = eventTap
        self.appVersion = appVersion
        self.baseDir = baseDirectory
    }

    nonisolated static func defaultBaseDirectory() -> URL {
        let fm = FileManager.default
        let support = (try? fm.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )) ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return support.appendingPathComponent("ContextApp/Recordings", isDirectory: true)
    }

    func start(goal: Goal, screen: NSScreen? = NSScreen.main) async throws -> URL {
        guard state == .idle else { throw RecordingSessionError.alreadyRecording }
        let perms = RecordingPermissionsProbe.request()
        guard perms.allGranted else { throw RecordingSessionError.permissionsDenied(needs: perms) }

        let recordingId = UUID().uuidString
        let bundleDir = baseDir.appendingPathComponent("recording-\(recordingId)", isDirectory: true)
        let layout = BundleLayout(root: bundleDir)
        do {
            try FileManager.default.createDirectory(at: layout.framesDir, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: layout.cropsDir, withIntermediateDirectories: true)
        } catch {
            throw RecordingSessionError.bundleCreationFailed(error)
        }

        let resolvedScreen = screen ?? NSScreen.main ?? NSScreen.screens.first
        let display = Self.displayInfo(for: resolvedScreen)
        let manifest = Manifest(
            recordingId: recordingId,
            schemaVersion: kRecordingSchemaVersion,
            startedAtMs: MonotonicClock.wallClockMs(),
            endedAtMs: nil,
            display: display,
            goal: goal,
            appVersion: appVersion,
            aborted: false
        )
        try writeManifest(manifest, to: layout)

        // Open events.jsonl for append.
        FileManager.default.createFile(atPath: layout.eventsURL.path, contents: nil)
        let handle = try FileHandle(forWritingTo: layout.eventsURL)
        self.eventsFileHandle = handle
        self.bundle = layout
        self.manifest = manifest
        self.persistedFrameIds = []

        if let resolvedScreen {
            try await frameStream.start(on: resolvedScreen, fps: 12)
        }

        eventTap.onEvent = { [weak self] raw in
            guard let self else { return }
            Task { @MainActor in self.consume(raw: raw) }
        }
        try eventTap.start()

        state = .recording
        Self.log.info("Recording started id=\(recordingId)")
        return bundleDir
    }

    func stop() async throws -> URL {
        guard state == .recording, let bundle, var manifest else {
            throw RecordingSessionError.notRecording
        }
        state = .stopping
        eventTap.stop()
        try? await frameStream.stop()

        manifest.endedAtMs = MonotonicClock.wallClockMs()
        try writeManifest(manifest, to: bundle)

        try? eventsFileHandle?.close()
        eventsFileHandle = nil
        self.manifest = nil
        self.bundle = nil
        state = .idle
        Self.log.info("Recording stopped id=\(manifest.recordingId)")
        return bundle.root
    }

    func abort(reason: String) {
        Self.log.error("Recording aborted: \(reason, privacy: .public)")
        eventTap.stop()
        Task { try? await frameStream.stop() }
        if let bundle, var manifest {
            manifest.aborted = true
            manifest.endedAtMs = MonotonicClock.wallClockMs()
            try? writeManifest(manifest, to: bundle)
        }
        try? eventsFileHandle?.close()
        eventsFileHandle = nil
        manifest = nil
        bundle = nil
        state = .idle
    }

    // MARK: - Internals

    private func consume(raw: RawInputEvent) {
        guard state == .recording, let bundle else { return }
        let frame = frameStream.latestFrame(near: raw.hostTimeMs)
        let event = Self.makeRecordedEvent(raw: raw, frame: frame)
        let transformed = (eventTransform?(event, frame)) ?? [event]
        for ev in transformed {
            persist(event: ev, frame: frame, bundle: bundle)
        }
    }

    private func persist(event: RecordedEvent, frame: CapturedFrame?, bundle: BundleLayout) {
        if let frame, !persistedFrameIds.contains(frame.frameId) {
            do {
                try frame.jpegData.write(to: bundle.frameURL(frameId: frame.frameId))
                persistedFrameIds.insert(frame.frameId)
            } catch {
                Self.log.warning("frame_write_failed reason=\(error.localizedDescription, privacy: .public)")
            }
        }
        appendEvent(event, bundle: bundle)
    }

    private func appendEvent(_ event: RecordedEvent, bundle: BundleLayout) {
        guard let handle = eventsFileHandle else { return }
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = []
            let data = try encoder.encode(event)
            try handle.write(contentsOf: data)
            try handle.write(contentsOf: Data([0x0A]))
        } catch {
            Self.log.error("events_jsonl_write_failed reason=\(error.localizedDescription, privacy: .public)")
            abort(reason: "events.jsonl write failed")
        }
    }

    private func writeManifest(_ manifest: Manifest, to bundle: BundleLayout) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(manifest)
        try data.write(to: bundle.manifestURL, options: .atomic)
    }

    private static func makeRecordedEvent(raw: RawInputEvent, frame: CapturedFrame?) -> RecordedEvent {
        let kind: RecordedEventKind
        var button: MouseButton? = nil
        var key: KeyStroke? = nil
        switch raw.kind {
        case .leftMouseDown: kind = .click; button = .left
        case .rightMouseDown: kind = .click; button = .right
        case .otherMouseDown: kind = .click; button = .other
        case .scrollWheel: kind = .scroll
        case .keyDown:
            kind = .keyDown
            key = KeyStroke(
                keyCode: raw.keyCode,
                characters: raw.characters,
                modifiers: ModifierFlagsFormatter.names(from: raw.modifierFlags)
            )
        case .flagsChanged:
            kind = .flags
            key = KeyStroke(
                keyCode: raw.keyCode,
                characters: nil,
                modifiers: ModifierFlagsFormatter.names(from: raw.modifierFlags)
            )
        }
        return RecordedEvent(
            id: UUID().uuidString,
            timestampMs: raw.hostTimeMs,
            kind: kind,
            cursor: Point(x: Int(raw.cursor.x.rounded()), y: Int(raw.cursor.y.rounded())),
            button: button,
            scroll: nil,
            key: key,
            frameId: frame?.frameId,
            targetCropPath: nil,
            contextCropPath: nil
        )
    }

    private static func displayInfo(for screen: NSScreen?) -> DisplayInfo {
        let frame = screen?.frame ?? .zero
        let scale = Double(screen?.backingScaleFactor ?? 1.0)
        return DisplayInfo(
            x: Int(frame.origin.x),
            y: Int(frame.origin.y),
            width: Int(frame.size.width),
            height: Int(frame.size.height),
            scaleFactor: scale
        )
    }
}

enum ModifierFlagsFormatter {
    static func names(from flags: CGEventFlags) -> [String] {
        var out: [String] = []
        if flags.contains(.maskCommand) { out.append("cmd") }
        if flags.contains(.maskShift) { out.append("shift") }
        if flags.contains(.maskAlternate) { out.append("opt") }
        if flags.contains(.maskControl) { out.append("ctrl") }
        if flags.contains(.maskAlphaShift) { out.append("caps") }
        if flags.contains(.maskSecondaryFn) { out.append("fn") }
        return out
    }
}

private extension Bundle {
    var shortVersionString: String {
        (infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.0.0"
    }
}
