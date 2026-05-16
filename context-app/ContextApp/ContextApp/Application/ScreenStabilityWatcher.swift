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

/// Waits for the screen to visually stabilize after a click before letting
/// the caller proceed. After an initial 500 ms delay, polls every 100 ms and
/// compares the latest captured frame against a frame ~500 ms older. The
/// comparison downscales 3× and applies a Gaussian blur to wash out cursor
/// jitter and aliasing; once the mean per-channel difference is below
/// `stabilityThreshold`, the screen is considered settled. A hard `timeout`
/// guarantees we never block the tutorial indefinitely.
@MainActor
final class ScreenStabilityWatcher {
    static let initialDelay: TimeInterval = 0.5
    static let pollInterval: TimeInterval = 0.1
    static let comparisonWindow: TimeInterval = 0.5
    static let timeout: TimeInterval = 5.0
    static let stabilityThreshold: Double = 0.004
    static let downscaleFactor: CGFloat = 3.0
    static let blurRadius: Double = 2.0

    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    func waitUntilStable(
        on screen: NSScreen,
        excludingWindows: [NSWindow] = [],
        onProgress: ((Double) -> Void)? = nil
    ) async {
        let displayID: CGDirectDisplayID
        do {
            displayID = try Self.displayID(for: screen)
        } catch {
            return
        }

        let collector = FrameCollector()
        let stream: SCStream
        do {
            stream = try await Self.makeStream(
                displayID: displayID,
                excludingWindows: excludingWindows,
                collector: collector
            )
        } catch {
            return
        }

        defer {
            Task { try? await stream.stopCapture() }
        }

        try? await Task.sleep(nanoseconds: UInt64(Self.initialDelay * 1_000_000_000))

        let start = Date()
        while Date().timeIntervalSince(start) < (Self.timeout - Self.initialDelay) {
            try? await Task.sleep(nanoseconds: UInt64(Self.pollInterval * 1_000_000_000))
            guard
                let pair = collector.framePair(window: Self.comparisonWindow),
                let diff = meanDifference(current: pair.current, past: pair.past)
            else {
                continue
            }
            onProgress?(diff)
            if diff <= Self.stabilityThreshold {
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
        config.minimumFrameInterval = CMTime(value: 1, timescale: 10)
        config.queueDepth = 2
        config.showsCursor = false

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

private struct TimedFrame {
    let image: CIImage
    let timestamp: Date
}

private final class FrameCollector: NSObject, SCStreamOutput {
    private let lock = NSLock()
    private var frames: [TimedFrame] = []
    private let maxAge: TimeInterval = 2.0

    func framePair(window: TimeInterval) -> (current: CIImage, past: CIImage)? {
        lock.lock()
        defer { lock.unlock() }
        guard let latest = frames.last else { return nil }
        let cutoff = latest.timestamp.addingTimeInterval(-window)
        guard let past = frames.last(where: { $0.timestamp <= cutoff }) else { return nil }
        return (latest.image, past.image)
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .screen, let pixelBuffer = sampleBuffer.imageBuffer else { return }
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let now = Date()
        lock.lock()
        frames.append(TimedFrame(image: image, timestamp: now))
        let cutoff = now.addingTimeInterval(-maxAge)
        frames.removeAll(where: { $0.timestamp < cutoff })
        lock.unlock()
    }
}
