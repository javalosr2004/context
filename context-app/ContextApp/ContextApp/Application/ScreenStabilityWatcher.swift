import AppKit
import CoreImage
import CoreImage.CIFilterBuiltins
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

enum ScreenStabilityWatcherError: Error {
    case noDisplay
}

enum StabilityProgress {
    case streamFailed
    case warmingUp(frameCount: Int)
    case comparing(diff: Double)
    case comparisonFailed
}

/// Waits for the screen to visually stabilize after a click before letting
/// the caller proceed. After an initial 500 ms delay, polls every 100 ms and
/// compares the latest captured frame against a frame ~500 ms older. The
/// comparison downscales 3× and applies a Gaussian blur to wash out cursor
/// jitter and aliasing; once the mean per-channel difference is below
/// `stabilityThreshold`, the screen is considered settled. A hard `timeout`
/// guarantees we never block the tutorial indefinitely. If the difference is
/// stuck above the threshold for several comparison windows, we also proceed so
/// persistent animations do not block the next screenshot forever.
@MainActor
final class ScreenStabilityWatcher {
    static let initialDelay: TimeInterval = 0.5
    static let pollInterval: TimeInterval = 0.1
    static let comparisonWindow: TimeInterval = 0.3
    static let timeout: TimeInterval = 5.0
    static let stabilityThreshold: Double = 0.02
    static let unchangedDifferenceFrameLimit = 3
    static let unchangedDifferenceTolerance: Double = 0.001
    static let downscaleFactor: CGFloat = 2.0
    static let blurRadius: Double = 2.0

    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])
    private var activeStream: SCStream?
    private var activeCollector: FrameCollector?
    private var prewarmTask: Task<Void, Never>?

    /// Opens the SCStream so frames are already flowing by the time the user
    /// clicks. Idempotent — safe to call multiple times per step.
    func prewarm(on screen: NSScreen, excludingWindows: [NSWindow] = []) {
        guard prewarmTask == nil, activeStream == nil else { return }
        prewarmTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.prewarmTask = nil }
            guard let displayID = try? Self.displayID(for: screen) else { return }
            let collector = FrameCollector()
            do {
                let stream = try await Self.makeStream(
                    displayID: displayID,
                    excludingWindows: excludingWindows,
                    collector: collector
                )
                self.activeStream = stream
                self.activeCollector = collector
            } catch {
                return
            }
        }
    }

    /// Tears down any prewarmed or active stream. Safe to call when nothing is
    /// running.
    func cancel() {
        prewarmTask?.cancel()
        prewarmTask = nil
        if let stream = activeStream {
            Task { try? await stream.stopCapture() }
        }
        activeStream = nil
        activeCollector = nil
    }

    func waitUntilStable(
        on screen: NSScreen,
        excludingWindows: [NSWindow] = [],
        onProgress: ((StabilityProgress) -> Void)? = nil
    ) async {
        if let task = prewarmTask {
            await task.value
        }

        let collector: FrameCollector
        if let warmed = activeCollector, activeStream != nil {
            collector = warmed
        } else {
            guard let displayID = try? Self.displayID(for: screen) else {
                onProgress?(.streamFailed)
                return
            }
            let fresh = FrameCollector()
            do {
                let stream = try await Self.makeStream(
                    displayID: displayID,
                    excludingWindows: excludingWindows,
                    collector: fresh
                )
                activeStream = stream
                activeCollector = fresh
                collector = fresh
            } catch {
                onProgress?(.streamFailed)
                return
            }
        }

        defer { cancel() }

        try? await Task.sleep(nanoseconds: UInt64(Self.initialDelay * 1_000_000_000))

        let start = Date()
        var stabilityCounter = StabilityCounter(
            requiredUnchangedFrames: Self.unchangedDifferenceFrameLimit,
            differenceTolerance: Self.unchangedDifferenceTolerance
        )
        while Date().timeIntervalSince(start) < (Self.timeout - Self.initialDelay) {
            try? await Task.sleep(nanoseconds: UInt64(Self.pollInterval * 1_000_000_000))
            guard let pair = collector.framePair(window: Self.comparisonWindow) else {
                onProgress?(.warmingUp(frameCount: collector.frameCount()))
                stabilityCounter.reset()
                continue
            }
            guard let diff = meanDifference(current: pair.current, past: pair.past) else {
                onProgress?(.comparisonFailed)
                stabilityCounter.reset()
                continue
            }
            onProgress?(.comparing(diff: diff))
            if diff <= Self.stabilityThreshold {
                return
            }
            if stabilityCounter.didReachUnchangedLimit(diff: diff) {
                return
            }
        }
    }

    private func meanDifference(current: CIImage, past: CIImage) -> Double? {
        let scale = Float(1.0 / Self.downscaleFactor)

        let lanczos = CIFilter.lanczosScaleTransform()
        lanczos.inputImage = current
        lanczos.scale = scale
        guard let curSmall = lanczos.outputImage else { return nil }

        lanczos.inputImage = past
        lanczos.scale = scale
        guard let pastSmall = lanczos.outputImage else { return nil }

        let blur = CIFilter.gaussianBlur()
        blur.radius = Float(Self.blurRadius)
        blur.inputImage = curSmall
        guard let curBlur = blur.outputImage?.cropped(to: curSmall.extent) else { return nil }
        blur.inputImage = pastSmall
        guard let pastBlur = blur.outputImage?.cropped(to: pastSmall.extent) else { return nil }

        let diffFilter = CIFilter.differenceBlendMode()
        diffFilter.inputImage = curBlur
        diffFilter.backgroundImage = pastBlur
        guard let diff = diffFilter.outputImage?.cropped(to: curBlur.extent) else { return nil }

        let area = CIFilter.areaAverage()
        area.inputImage = diff
        area.extent = diff.extent
        guard let avg = area.outputImage else { return nil }

        var bytes: [UInt8] = [0, 0, 0, 0]
        ciContext.render(
            avg,
            toBitmap: &bytes,
            rowBytes: 4,
            bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
            format: .RGBA8,
            colorSpace: CGColorSpaceCreateDeviceRGB()
        )
        let r = Double(bytes[0]) / 255.0
        let g = Double(bytes[1]) / 255.0
        let b = Double(bytes[2]) / 255.0
        return (r + g + b) / 3.0
    }

    private static func makeStream(
        displayID: CGDirectDisplayID,
        excludingWindows: [NSWindow],
        collector: FrameCollector
    ) async throws -> SCStream {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false,
            onScreenWindowsOnly: true
        )
        let match = content.displays.first(where: { $0.displayID == displayID })
        guard let display = match ?? content.displays.first else {
            throw ScreenStabilityWatcherError.noDisplay
        }

        let excludedIDs = Set(excludingWindows.map { CGWindowID($0.windowNumber) })
        let excludedSCWindows = content.windows.filter { excludedIDs.contains($0.windowID) }
        let filter = SCContentFilter(display: display, excludingWindows: excludedSCWindows)
        let config = SCStreamConfiguration()
        let halfWidth = max(1, display.width / 2)
        let halfHeight = max(1, display.height / 2)
        config.width = halfWidth
        config.height = halfHeight
        config.minimumFrameInterval = CMTime(value: 1, timescale: 30)
        config.queueDepth = 8
        config.showsCursor = true

        let stream = SCStream(filter: filter, configuration: config, delegate: nil)
        try stream.addStreamOutput(
            collector,
            type: .screen,
            sampleHandlerQueue: DispatchQueue(label: "context.stability.queue")
        )
        try await stream.startCapture()
        return stream
    }

    private static func displayID(for screen: NSScreen) throws -> CGDirectDisplayID {
        guard
            let value = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber
        else {
            throw ScreenStabilityWatcherError.noDisplay
        }
        return CGDirectDisplayID(value.uint32Value)
    }
}

struct StabilityCounter {
    private let requiredUnchangedFrames: Int
    private let differenceTolerance: Double
    private var lastDifference: Double?
    private var unchangedFrameCount = 0

    init(requiredUnchangedFrames: Int, differenceTolerance: Double) {
        self.requiredUnchangedFrames = requiredUnchangedFrames
        self.differenceTolerance = differenceTolerance
    }

    mutating func didReachUnchangedLimit(diff: Double) -> Bool {
        guard requiredUnchangedFrames > 0 else { return true }

        guard let previousDifference = lastDifference else {
            lastDifference = diff
            unchangedFrameCount = 1
            return unchangedFrameCount >= requiredUnchangedFrames
        }

        if abs(diff - previousDifference) <= differenceTolerance {
            unchangedFrameCount += 1
        } else {
            unchangedFrameCount = 1
        }

        lastDifference = diff
        return unchangedFrameCount >= requiredUnchangedFrames
    }

    mutating func reset() {
        lastDifference = nil
        unchangedFrameCount = 0
    }
}

private struct TimedFrame {
    let image: CGImage
    /// Capture-side presentation timestamp in seconds. Stable against burst
    /// delivery from SCStream's internal queue.
    let timestampSeconds: Double
}

private final class FrameCollector: NSObject, SCStreamOutput {
    private let lock = NSLock()
    private var frames: [TimedFrame] = []
    private let maxAge: TimeInterval = 2.0
    // Owned context for copying SCK-backed pixel buffers into independent
    // CGImages. Without this copy, CIImages retain the stream's IOSurfaces,
    // queueDepth fills, and SCStream stops delivering new frames.
    private let renderContext = CIContext(options: [.useSoftwareRenderer: false])

    func frameCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return frames.count
    }

    func framePair(window: TimeInterval) -> (current: CIImage, past: CIImage)? {
        lock.lock()
        defer { lock.unlock() }
        guard let latest = frames.last else { return nil }
        if let first = frames.first, let last = frames.last {
            print("frame span:", last.timestampSeconds - first.timestampSeconds, "count:", frames.count)
        }
        let cutoff = latest.timestampSeconds - window
        guard let past = frames.last(where: { $0.timestampSeconds <= cutoff }) else { return nil }
        return (CIImage(cgImage: latest.image), CIImage(cgImage: past.image))
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .screen, let pixelBuffer = sampleBuffer.imageBuffer else { return }
        let pts = CMTimeGetSeconds(sampleBuffer.presentationTimeStamp)
        guard pts.isFinite else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let copied = renderContext.createCGImage(ciImage, from: ciImage.extent) else { return }
        lock.lock()
        frames.append(TimedFrame(image: copied, timestampSeconds: pts))
        let cutoff = pts - maxAge
        frames.removeAll(where: { $0.timestampSeconds < cutoff })
        lock.unlock()
    }
}
