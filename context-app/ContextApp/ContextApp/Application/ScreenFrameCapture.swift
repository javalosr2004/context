import AppKit
import CoreImage
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

struct CapturedScreenFrame {
    let jpegData: Data
    let displayID: CGDirectDisplayID
    let pixelSize: CGSize
}

enum ScreenFrameCaptureError: LocalizedError {
    case alreadyCapturing
    case noDisplay
    case noDisplayForScreen(CGDirectDisplayID)
    case imageConversionFailed

    var errorDescription: String? {
        switch self {
        case .alreadyCapturing:
            return "A screen capture is already in progress."
        case .noDisplay:
            return "No display was available for capture."
        case .noDisplayForScreen(let displayID):
            return "No ScreenCaptureKit display matched screen \(displayID)."
        case .imageConversionFailed:
            return "Could not convert the captured frame to JPEG."
        }
    }
}

final class ScreenFrameCapture: NSObject, SCStreamOutput {
    private let imageContext = CIContext()
    private let sampleQueue = DispatchQueue(label: "context.screen.frame.queue")
    private let stateLock = NSLock()
    private var continuation: CheckedContinuation<CapturedScreenFrame, Error>?
    private var targetDisplayID: CGDirectDisplayID?
    private var stream: SCStream?

    func captureFrame(on screen: NSScreen) async throws -> CapturedScreenFrame {
        let displayID = try displayID(for: screen)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                stateLock.lock()
                guard self.continuation == nil else {
                    stateLock.unlock()
                    continuation.resume(throwing: ScreenFrameCaptureError.alreadyCapturing)
                    return
                }

                self.continuation = continuation
                self.targetDisplayID = displayID
                stateLock.unlock()

                Task {
                    do {
                        try await self.start()
                    } catch {
                        self.finish(throwing: error)
                    }
                }
            }
        } onCancel: {
            Task { self.finish(throwing: CancellationError()) }
        }
    }

    func stop() async throws {
        try await stream?.stopCapture()
        stream = nil
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .screen else { return }
        guard let pixelBuffer = sampleBuffer.imageBuffer else { return }

        do {
            let frame = try capturedFrame(from: pixelBuffer)
            finish(returning: frame)
        } catch {
            finish(throwing: error)
        }
    }

    private func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false,
            onScreenWindowsOnly: true
        )

        let display = try selectedDisplay(from: content.displays)
        guard let display else {
            throw ScreenFrameCaptureError.noDisplay
        }

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.width = display.width
        config.height = display.height
        config.minimumFrameInterval = CMTime(value: 1, timescale: 30)
        config.queueDepth = 2
        config.showsCursor = true

        let stream = SCStream(filter: filter, configuration: config, delegate: nil)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: sampleQueue)
        self.stream = stream
        try await stream.startCapture()
    }

    private func capturedFrame(from pixelBuffer: CVPixelBuffer) throws -> CapturedScreenFrame {
        guard let displayID = activeTargetDisplayID() else {
            throw ScreenFrameCaptureError.noDisplay
        }

        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = imageContext.createCGImage(image, from: image.extent) else {
            throw ScreenFrameCaptureError.imageConversionFailed
        }

        let rep = NSBitmapImageRep(cgImage: cgImage)
        guard let jpegData = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.86]) else {
            throw ScreenFrameCaptureError.imageConversionFailed
        }

        return CapturedScreenFrame(
            jpegData: jpegData,
            displayID: displayID,
            pixelSize: CGSize(width: CVPixelBufferGetWidth(pixelBuffer), height: CVPixelBufferGetHeight(pixelBuffer))
        )
    }

    private func selectedDisplay(from displays: [SCDisplay]) throws -> SCDisplay? {
        guard let targetDisplayID = activeTargetDisplayID() else {
            return displays.first
        }

        guard let display = displays.first(where: { $0.displayID == targetDisplayID }) else {
            throw ScreenFrameCaptureError.noDisplayForScreen(targetDisplayID)
        }

        return display
    }

    private func activeTargetDisplayID() -> CGDirectDisplayID? {
        stateLock.lock()
        defer { stateLock.unlock() }
        return targetDisplayID
    }

    private func displayID(for screen: NSScreen) throws -> CGDirectDisplayID {
        guard let value = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            throw ScreenFrameCaptureError.noDisplay
        }

        return CGDirectDisplayID(value.uint32Value)
    }

    private func finish(returning frame: CapturedScreenFrame) {
        stateLock.lock()
        guard let continuation else {
            stateLock.unlock()
            return
        }
        self.continuation = nil
        self.targetDisplayID = nil
        stateLock.unlock()
        continuation.resume(returning: frame)
        Task { try? await stop() }
    }

    private func finish(throwing error: Error) {
        stateLock.lock()
        guard let continuation else {
            stateLock.unlock()
            return
        }
        self.continuation = nil
        self.targetDisplayID = nil
        stateLock.unlock()
        continuation.resume(throwing: error)
        Task { try? await stop() }
    }
}
