import AppKit
import Foundation

@MainActor
final class ScreenGroundingController {
    private let bboxController: DebugBboxController
    private let capture: ScreenFrameCapture
    private let endpointStore: GroundingEndpointStore
    private let screenProvider: () -> NSScreen?

    init(
        bboxController: DebugBboxController,
        capture: ScreenFrameCapture = ScreenFrameCapture(),
        endpointStore: GroundingEndpointStore,
        screenProvider: @escaping () -> NSScreen?
    ) {
        self.bboxController = bboxController
        self.capture = capture
        self.endpointStore = endpointStore
        self.screenProvider = screenProvider
    }

    func submit(_ instruction: GroundingInstruction) async -> String {
        do {
            let client = try GroundingClient.fromEndpointStore(endpointStore)
            let frame = try await capture.captureFrame()
            let bbox = try await client.locate(instruction: instruction, screenshotJPEGData: frame.jpegData)
            guard let screen = screenProvider(),
                  let rect = bbox.screenRect(captureSize: frame.pixelSize, screenFrame: screen.frame) else {
                return "Could not map the returned bounding box to the current screen."
            }

            bboxController.show(rect: rect)
            return "Displayed bounding box: \(Int(bbox.x)), \(Int(bbox.y)), \(Int(bbox.width)), \(Int(bbox.height))"
        } catch {
            return "Input instruction failed: \(error.localizedDescription)"
        }
    }
}
