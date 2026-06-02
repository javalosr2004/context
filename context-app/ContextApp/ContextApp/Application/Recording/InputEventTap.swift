import AppKit
import CoreGraphics
import Foundation
import os

enum RawInputEventKind {
    case leftMouseDown
    case rightMouseDown
    case otherMouseDown
    case scrollWheel
    case keyDown
    case flagsChanged
}

struct RawInputEvent {
    let kind: RawInputEventKind
    let hostTimeMs: Int64
    let cursor: CGPoint
    /// Scroll wheel deltas in points (post-acceleration), only set for `.scrollWheel`.
    let scrollDeltaX: Double
    let scrollDeltaY: Double
    /// Raw `CGScrollPhase` mask. 0x0 = no phase / legacy mouse wheel.
    let scrollPhaseRaw: UInt32
    /// Raw `CGMomentumScrollPhase`. 0 = none.
    let scrollMomentumPhaseRaw: UInt32
    /// Key code, only meaningful for `.keyDown` / `.flagsChanged`.
    let keyCode: Int
    let characters: String?
    let modifierFlags: CGEventFlags
}

enum InputEventTapError: LocalizedError {
    case createFailed
    case alreadyRunning

    var errorDescription: String? {
        switch self {
        case .createFailed: return "Could not create the input event tap. Accessibility permission is required."
        case .alreadyRunning: return "Input event tap is already running."
        }
    }
}

/// Listen-only `CGEvent` tap. Runs the tap on a dedicated thread/runloop; marshals
/// each event onto a serial queue before invoking `onEvent`.
final class InputEventTap {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "InputTap")
    private static let deliveryQueue = DispatchQueue(label: "context.recording.inputtap.delivery")

    var onEvent: ((RawInputEvent) -> Void)?

    private var tap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var runLoop: CFRunLoop?
    private var thread: Thread?
    private let stateLock = NSLock()

    func start() throws {
        stateLock.lock()
        if tap != nil { stateLock.unlock(); throw InputEventTapError.alreadyRunning }
        stateLock.unlock()

        let mask: CGEventMask =
            (1 << CGEventType.leftMouseDown.rawValue) |
            (1 << CGEventType.rightMouseDown.rawValue) |
            (1 << CGEventType.otherMouseDown.rawValue) |
            (1 << CGEventType.scrollWheel.rawValue) |
            (1 << CGEventType.keyDown.rawValue) |
            (1 << CGEventType.flagsChanged.rawValue)

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: { _, type, event, refcon in
                guard let refcon else { return Unmanaged.passUnretained(event) }
                let me = Unmanaged<InputEventTap>.fromOpaque(refcon).takeUnretainedValue()
                me.handle(cgType: type, event: event)
                return Unmanaged.passUnretained(event)
            },
            userInfo: selfPtr
        ) else {
            throw InputEventTapError.createFailed
        }

        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        let started = DispatchSemaphore(value: 0)
        let thread = Thread { [weak self] in
            let rl = CFRunLoopGetCurrent()
            self?.stateLock.lock()
            self?.runLoop = rl
            self?.runLoopSource = source
            self?.tap = tap
            self?.stateLock.unlock()
            CFRunLoopAddSource(rl, source, .commonModes)
            CGEvent.tapEnable(tap: tap, enable: true)
            started.signal()
            CFRunLoopRun()
        }
        thread.name = "ContextApp.Recording.InputTap"
        thread.start()
        self.thread = thread
        started.wait()
        Self.log.info("Input event tap started")
    }

    func stop() {
        stateLock.lock()
        let rl = runLoop
        let source = runLoopSource
        let tap = self.tap
        runLoop = nil
        runLoopSource = nil
        self.tap = nil
        stateLock.unlock()

        if let tap { CGEvent.tapEnable(tap: tap, enable: false) }
        if let rl, let source {
            CFRunLoopRemoveSource(rl, source, .commonModes)
            CFRunLoopStop(rl)
        }
        thread = nil
        Self.log.info("Input event tap stopped")
    }

    private func handle(cgType: CGEventType, event: CGEvent) {
        if cgType == .tapDisabledByTimeout || cgType == .tapDisabledByUserInput {
            stateLock.lock()
            let tap = self.tap
            stateLock.unlock()
            if let tap { CGEvent.tapEnable(tap: tap, enable: true) }
            Self.log.warning("Tap re-enabled after disable type=\(cgType.rawValue)")
            return
        }

        let kind: RawInputEventKind
        switch cgType {
        case .leftMouseDown: kind = .leftMouseDown
        case .rightMouseDown: kind = .rightMouseDown
        case .otherMouseDown: kind = .otherMouseDown
        case .scrollWheel: kind = .scrollWheel
        case .keyDown: kind = .keyDown
        case .flagsChanged: kind = .flagsChanged
        default: return
        }

        let hostMs = MonotonicClock.nowMs()
        let location = event.location
        let dx = event.getDoubleValueField(.scrollWheelEventPointDeltaAxis2)
        let dy = event.getDoubleValueField(.scrollWheelEventPointDeltaAxis1)
        let phaseRaw = UInt32(event.getIntegerValueField(.scrollWheelEventScrollPhase))
        let momentumRaw = UInt32(event.getIntegerValueField(.scrollWheelEventMomentumPhase))
        let keyCode = Int(event.getIntegerValueField(.keyboardEventKeycode))
        let chars = (cgType == .keyDown) ? Self.characters(from: event) : nil

        let raw = RawInputEvent(
            kind: kind,
            hostTimeMs: hostMs,
            cursor: location,
            scrollDeltaX: dx,
            scrollDeltaY: dy,
            scrollPhaseRaw: phaseRaw,
            scrollMomentumPhaseRaw: momentumRaw,
            keyCode: keyCode,
            characters: chars,
            modifierFlags: event.flags
        )

        let cb = onEvent
        Self.deliveryQueue.async { cb?(raw) }
    }

    private static func characters(from event: CGEvent) -> String? {
        var length = 0
        var buf = [UniChar](repeating: 0, count: 8)
        event.keyboardGetUnicodeString(maxStringLength: buf.count, actualStringLength: &length, unicodeString: &buf)
        guard length > 0 else { return nil }
        return String(utf16CodeUnits: buf, count: length)
    }
}
