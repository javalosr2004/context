import AppKit
import CoreImage
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

struct CapturedScreenFrame {
    let pngData: Data
    let pixelSize: CGSize
}

enum ScreenFrameCaptureError: LocalizedError {
    case alreadyCapturing
    case noDisplay
    case imageConversionFailed

    var errorDescription: String? {
        switch self {
        case .alreadyCapturing:
            return "A screen capture is already in progress."
        case .noDisplay:
            return "No display was available for capture."
        case .imageConversionFailed:
            return "Could not convert the captured frame to PNG."
        }
    }
}

final class ScreenFrameCapture: NSObject, SCStreamOutput {
    private let imageContext = CIContext()
    private let sampleQueue = DispatchQueue(label: "context.screen.frame.queue")
    private let stateLock = NSLock()
    private var continuation: CheckedContinuation<CapturedScreenFrame, Error>?
    private var stream: SCStream?

    func captureFrame() async throws -> CapturedScreenFrame {
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                stateLock.lock()
                guard self.continuation == nil else {
                    stateLock.unlock()
                    continuation.resume(throwing: ScreenFrameCaptureError.alreadyCapturing)
                    return
                }

                self.continuation = continuation
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

        guard let display = content.displays.first else {
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
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = imageContext.createCGImage(image, from: image.extent) else {
            throw ScreenFrameCaptureError.imageConversionFailed
        }

        let rep = NSBitmapImageRep(cgImage: cgImage)
        guard let pngData = rep.representation(using: .png, properties: [:]) else {
            throw ScreenFrameCaptureError.imageConversionFailed
        }

        return CapturedScreenFrame(
            pngData: pngData,
            pixelSize: CGSize(width: CVPixelBufferGetWidth(pixelBuffer), height: CVPixelBufferGetHeight(pixelBuffer))
        )
    }

    private func finish(returning frame: CapturedScreenFrame) {
        stateLock.lock()
        guard let continuation else {
            stateLock.unlock()
            return
        }
        self.continuation = nil
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
        stateLock.unlock()
        continuation.resume(throwing: error)
        Task { try? await stop() }
    }
}
