import AppKit
import CoreGraphics
import CoreImage
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import ScreenCaptureKit
import os

struct CapturedFrame {
    let frameId: String
    let hostTimeMs: Int64
    let pixelSize: CGSize
    let jpegData: Data
}

enum ContinuousFrameStreamError: LocalizedError {
    case alreadyRunning
    case notRunning
    case noDisplayForScreen(CGDirectDisplayID)

    var errorDescription: String? {
        switch self {
        case .alreadyRunning: return "Frame stream is already running."
        case .notRunning: return "Frame stream is not running."
        case .noDisplayForScreen(let id): return "No ScreenCaptureKit display matched screen \(id)."
        }
    }
}

/// Long-running `SCStream` with a ring buffer of recent frames keyed by host time.
/// Per-frame jpeg sha1 deduplicates identical frames by content.
final class ContinuousFrameStream: NSObject, SCStreamOutput {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "FrameStream")
    private static let jpegQuality: CGFloat = 0.7

    private let ringCapacity: Int
    private let sampleQueue = DispatchQueue(label: "context.recording.framestream")
    private let imageContext = CIContext()

    private let stateLock = NSLock()
    private var ring: [CapturedFrame] = []
    private var byId: [String: CapturedFrame] = [:]
    private var stream: SCStream?
    private var isRunning = false

    init(ringCapacity: Int = 60) {
        self.ringCapacity = ringCapacity
    }

    func start(on screen: NSScreen, fps: Int = 12) async throws {
        stateLock.lock()
        if isRunning {
            stateLock.unlock()
            throw ContinuousFrameStreamError.alreadyRunning
        }
        isRunning = true
        stateLock.unlock()

        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            let targetID = try displayID(for: screen)
            guard let display = content.displays.first(where: { $0.displayID == targetID }) ?? content.displays.first else {
                throw ContinuousFrameStreamError.noDisplayForScreen(targetID)
            }

            let filter = SCContentFilter(display: display, excludingWindows: [])
            let config = SCStreamConfiguration()
            config.width = display.width
            config.height = display.height
            config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(max(1, fps)))
            config.queueDepth = 4
            config.showsCursor = true

            let stream = SCStream(filter: filter, configuration: config, delegate: nil)
            try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: sampleQueue)
            try await stream.startCapture()
            self.stream = stream
            Self.log.info("Started SCStream display=\(display.displayID) fps=\(fps)")
        } catch {
            stateLock.lock()
            isRunning = false
            stateLock.unlock()
            throw error
        }
    }

    func stop() async throws {
        let s: SCStream? = {
            stateLock.lock()
            defer { stateLock.unlock() }
            let s = stream
            stream = nil
            isRunning = false
            return s
        }()
        if let s {
            try await s.stopCapture()
            Self.log.info("Stopped SCStream")
        }
    }

    /// O(1) nearest-by-time lookup against the ring buffer. Returns nil if buffer is empty.
    func latestFrame(near hostTimeMs: Int64) -> CapturedFrame? {
        stateLock.lock()
        defer { stateLock.unlock() }
        guard !ring.isEmpty else { return nil }
        var best = ring[0]
        var bestDelta = abs(best.hostTimeMs - hostTimeMs)
        for f in ring.dropFirst() {
            let d = abs(f.hostTimeMs - hostTimeMs)
            if d < bestDelta { best = f; bestDelta = d }
        }
        return best
    }

    func frame(byId id: String) -> CapturedFrame? {
        stateLock.lock()
        defer { stateLock.unlock() }
        return byId[id]
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, let pixelBuffer = sampleBuffer.imageBuffer else { return }

        let hostMs = MonotonicClock.nowMs()
        guard let jpeg = jpegEncode(pixelBuffer) else {
            Self.log.warning("frame_drop reason=jpeg_encode_failed")
            return
        }
        let frameId = Self.shortHash(of: jpeg)
        let frame = CapturedFrame(
            frameId: frameId,
            hostTimeMs: hostMs,
            pixelSize: CGSize(width: CVPixelBufferGetWidth(pixelBuffer), height: CVPixelBufferGetHeight(pixelBuffer)),
            jpegData: jpeg
        )
        store(frame)
    }

    private func store(_ frame: CapturedFrame) {
        stateLock.lock()
        defer { stateLock.unlock() }
        ring.append(frame)
        byId[frame.frameId] = frame
        if ring.count > ringCapacity {
            let dropped = ring.removeFirst()
            // Only drop from byId if no later ring entry shares the id (dedup by content).
            if !ring.contains(where: { $0.frameId == dropped.frameId }) {
                byId.removeValue(forKey: dropped.frameId)
            }
        }
    }

    private func jpegEncode(_ pixelBuffer: CVPixelBuffer) -> Data? {
        let ci = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cg = imageContext.createCGImage(ci, from: ci.extent) else { return nil }
        let rep = NSBitmapImageRep(cgImage: cg)
        return rep.representation(using: .jpeg, properties: [.compressionFactor: Self.jpegQuality])
    }

    private func displayID(for screen: NSScreen) throws -> CGDirectDisplayID {
        guard let value = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            throw ContinuousFrameStreamError.noDisplayForScreen(0)
        }
        return CGDirectDisplayID(value.uint32Value)
    }

    static func shortHash(of data: Data) -> String {
        let digest = Insecure.SHA1.hash(data: data)
        return digest.prefix(6).map { String(format: "%02x", $0) }.joined()
    }
}
