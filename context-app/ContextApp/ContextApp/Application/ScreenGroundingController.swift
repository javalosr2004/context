import AppKit
import Dispatch
import Foundation
import OSLog

@MainActor
final class ScreenGroundingController {
    private let logger = Logger(subsystem: "ContextApp", category: "ScreenGrounding")
    private let bboxController: DebugBboxController
    private let capture: ScreenFrameCapture
    private let endpointStore: GroundingEndpointStore
    private let ignoredWindowProvider: () -> [NSWindow]
    private let screenProvider: () -> NSScreen?

    init(
        bboxController: DebugBboxController,
        capture: ScreenFrameCapture = ScreenFrameCapture(),
        endpointStore: GroundingEndpointStore,
        ignoredWindowProvider: @escaping () -> [NSWindow] = { [] },
        screenProvider: @escaping () -> NSScreen?
    ) {
        self.bboxController = bboxController
        self.capture = capture
        self.endpointStore = endpointStore
        self.ignoredWindowProvider = ignoredWindowProvider
        self.screenProvider = screenProvider
    }

    func submit(_ instruction: GroundingInstruction) async -> String {
        let controllerStartedAt = DispatchTime.now().uptimeNanoseconds
        let roundTripStartedAt = instruction.submittedAtUptimeNanoseconds ?? controllerStartedAt

        do {
            guard let screen = screenProvider() else {
                return "No screen was available for grounding."
            }

            let client = try GroundingClient.fromEndpointStore(endpointStore)
            let captureStartedAt = DispatchTime.now().uptimeNanoseconds
            let frame = try await capture.captureFrame(
                on: screen,
                encodingConfig: instruction.imageEncodingConfig
            )
            let captureEndedAt = DispatchTime.now().uptimeNanoseconds
            logger.info(
                "Captured display \(frame.displayID, privacy: .public) size \(Int(frame.pixelSize.width), privacy: .public)x\(Int(frame.pixelSize.height), privacy: .public) quality=\(instruction.imageEncodingConfig.jpegCompressionQuality, privacy: .public) maxWidth=\(instruction.imageEncodingConfig.maxPixelWidth, privacy: .public) for screen frame \(String(describing: screen.frame), privacy: .public)"
            )

            let maskingStartedAt = DispatchTime.now().uptimeNanoseconds
            let ignoredWindowFrames = ignoredWindowProvider()
                .filter(\.isVisible)
                .map(\.frame)
            let screenshotJPEGData = try ScreenFrameMasker.mask(
                jpegData: frame.jpegData,
                screenFrame: screen.frame,
                ignoredWindowFrames: ignoredWindowFrames,
                encodingConfig: instruction.imageEncodingConfig
            )
            let maskingEndedAt = DispatchTime.now().uptimeNanoseconds
            logger.info("Masked \(ignoredWindowFrames.count, privacy: .public) app windows before grounding request.")

            let apiStartedAt = DispatchTime.now().uptimeNanoseconds
            let bbox = try await client.locate(instruction: instruction, screenshotJPEGData: screenshotJPEGData)
            let apiEndedAt = DispatchTime.now().uptimeNanoseconds
            let mappingStartedAt = DispatchTime.now().uptimeNanoseconds
            guard let rect = bbox.screenRect(captureSize: frame.pixelSize, screenFrame: screen.frame) else {
                return "Could not map the returned bounding box to the current screen."
            }
            let mappingEndedAt = DispatchTime.now().uptimeNanoseconds

            logger.info(
                "Mapped bbox x=\(bbox.x, privacy: .public) y=\(bbox.y, privacy: .public) width=\(bbox.width, privacy: .public) height=\(bbox.height, privacy: .public) to screen rect \(String(describing: rect), privacy: .public)"
            )
            let overlayStartedAt = DispatchTime.now().uptimeNanoseconds
            bboxController.show(rect: rect)
            let overlayEndedAt = DispatchTime.now().uptimeNanoseconds
            let timing = GroundingRoundTripTiming(
                totalMilliseconds: milliseconds(from: roundTripStartedAt, to: overlayEndedAt),
                controllerQueueMilliseconds: milliseconds(from: roundTripStartedAt, to: controllerStartedAt),
                captureMilliseconds: milliseconds(from: captureStartedAt, to: captureEndedAt),
                maskingMilliseconds: milliseconds(from: maskingStartedAt, to: maskingEndedAt),
                apiMilliseconds: milliseconds(from: apiStartedAt, to: apiEndedAt),
                mappingMilliseconds: milliseconds(from: mappingStartedAt, to: mappingEndedAt),
                overlayMilliseconds: milliseconds(from: overlayStartedAt, to: overlayEndedAt)
            )
            logger.info("\(timing.logSummary, privacy: .public)")
            return """
            Displayed bounding box: \(Int(bbox.x)), \(Int(bbox.y)), \(Int(bbox.width)), \(Int(bbox.height))
            \(timing.chatSummary)
            """
        } catch {
            logger.error("Input instruction failed: \(error.localizedDescription, privacy: .public)")
            return "Input instruction failed: \(error.localizedDescription)"
        }
    }

    private func milliseconds(from start: UInt64, to end: UInt64) -> Int {
        guard end >= start else { return 0 }
        return Int((end - start) / 1_000_000)
    }
}

private struct GroundingRoundTripTiming {
    let totalMilliseconds: Int
    let controllerQueueMilliseconds: Int
    let captureMilliseconds: Int
    let maskingMilliseconds: Int
    let apiMilliseconds: Int
    let mappingMilliseconds: Int
    let overlayMilliseconds: Int

    var chatSummary: String {
        "Round trip: \(totalMilliseconds) ms (queue \(controllerQueueMilliseconds), capture \(captureMilliseconds), mask \(maskingMilliseconds), api \(apiMilliseconds), map \(mappingMilliseconds), overlay \(overlayMilliseconds))"
    }

    var logSummary: String {
        "Grounding timing total_ms=\(totalMilliseconds) queue_ms=\(controllerQueueMilliseconds) capture_ms=\(captureMilliseconds) mask_ms=\(maskingMilliseconds) api_ms=\(apiMilliseconds) map_ms=\(mappingMilliseconds) overlay_ms=\(overlayMilliseconds)"
    }
}
