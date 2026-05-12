import AppKit
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
        do {
            guard let screen = screenProvider() else {
                return "No screen was available for grounding."
            }

            let client = try GroundingClient.fromEndpointStore(endpointStore)
            let frame = try await capture.captureFrame(on: screen)
            logger.info(
                "Captured display \(frame.displayID, privacy: .public) size \(Int(frame.pixelSize.width), privacy: .public)x\(Int(frame.pixelSize.height), privacy: .public) for screen frame \(String(describing: screen.frame), privacy: .public)"
            )

            let ignoredWindowFrames = ignoredWindowProvider()
                .filter(\.isVisible)
                .map(\.frame)
            let screenshotJPEGData = try ScreenFrameMasker.mask(
                jpegData: frame.jpegData,
                screenFrame: screen.frame,
                ignoredWindowFrames: ignoredWindowFrames
            )
            logger.info("Masked \(ignoredWindowFrames.count, privacy: .public) app windows before grounding request.")

            let bbox = try await client.locate(instruction: instruction, screenshotJPEGData: screenshotJPEGData)
            guard let rect = bbox.screenRect(captureSize: frame.pixelSize, screenFrame: screen.frame) else {
                return "Could not map the returned bounding box to the current screen."
            }

            logger.info(
                "Mapped bbox x=\(bbox.x, privacy: .public) y=\(bbox.y, privacy: .public) width=\(bbox.width, privacy: .public) height=\(bbox.height, privacy: .public) to screen rect \(String(describing: rect), privacy: .public)"
            )
            bboxController.show(rect: rect)
            return "Displayed bounding box: \(Int(bbox.x)), \(Int(bbox.y)), \(Int(bbox.width)), \(Int(bbox.height))"
        } catch {
            logger.error("Input instruction failed: \(error.localizedDescription, privacy: .public)")
            return "Input instruction failed: \(error.localizedDescription)"
        }
    }
}
