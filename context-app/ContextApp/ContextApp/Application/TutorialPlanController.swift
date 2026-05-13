import AppKit
import Dispatch
import Foundation
import OSLog

@MainActor
final class TutorialPlanController {
    private let capture: ScreenFrameCapture
    private let client: TutorialPlanAPIClient
    private let conversationID: String
    private let endpointStore: TutorialAPIEndpointStore
    private let ignoredWindowProvider: () -> [NSWindow]
    private let logger = Logger(subsystem: "ContextApp", category: "TutorialPlan")
    private let screenProvider: () -> NSScreen?

    init(
        endpointStore: TutorialAPIEndpointStore,
        client: TutorialPlanAPIClient = TutorialPlanAPIClient(),
        capture: ScreenFrameCapture = ScreenFrameCapture(),
        conversationID: String = UUID().uuidString,
        ignoredWindowProvider: @escaping () -> [NSWindow] = { [] },
        screenProvider: @escaping () -> NSScreen?
    ) {
        self.capture = capture
        self.client = client
        self.conversationID = conversationID
        self.endpointStore = endpointStore
        self.ignoredWindowProvider = ignoredWindowProvider
        self.screenProvider = screenProvider
    }

    func submit(_ text: String) async throws -> TutorialPlan {
        let startedAt = DispatchTime.now().uptimeNanoseconds

        do {
            let planURL = try endpointStore.planURL()
            guard let baseURL = endpointStore.baseURL.flatMap(URL.init(string:)) else {
                throw TutorialAPIEndpointStoreError.missingBaseURL
            }
            guard let screen = screenProvider() else {
                throw TutorialPlanControllerError.noScreen
            }

            let captureStartedAt = DispatchTime.now().uptimeNanoseconds
            let frame = try await capture.captureFrame(on: screen)
            let captureEndedAt = DispatchTime.now().uptimeNanoseconds
            let ignoredWindowFrames = ignoredWindowProvider()
                .filter(\.isVisible)
                .map(\.frame)
            let screenJPEGData = try ScreenFrameMasker.mask(
                jpegData: frame.jpegData,
                screenFrame: screen.frame,
                ignoredWindowFrames: ignoredWindowFrames
            )
            let maskEndedAt = DispatchTime.now().uptimeNanoseconds

            logger.info(
                "Creating tutorial plan at \(planURL.absoluteString, privacy: .public) conversation_id=\(self.conversationID, privacy: .public) text_chars=\(text.count, privacy: .public) image_bytes=\(screenJPEGData.count, privacy: .public) masked_windows=\(ignoredWindowFrames.count, privacy: .public)"
            )
            let apiStartedAt = DispatchTime.now().uptimeNanoseconds
            let plan = try await client.createTutorialPlan(
                baseURL: baseURL,
                submission: TutorialPlanSubmission(
                    conversationID: conversationID,
                    text: text,
                    screenJPEGData: screenJPEGData
                )
            )
            let finishedAt = DispatchTime.now().uptimeNanoseconds
            logger.info(
                "Tutorial plan created steps=\(plan.steps.count, privacy: .public) total_ms=\(self.milliseconds(from: startedAt, to: finishedAt), privacy: .public) capture_ms=\(self.milliseconds(from: captureStartedAt, to: captureEndedAt), privacy: .public) mask_ms=\(self.milliseconds(from: captureEndedAt, to: maskEndedAt), privacy: .public) api_ms=\(self.milliseconds(from: apiStartedAt, to: finishedAt), privacy: .public)"
            )
            return plan
        } catch {
            logger.error("Tutorial plan failed: \(error.localizedDescription, privacy: .public)")
            throw error
        }
    }

    private func milliseconds(from start: UInt64, to end: UInt64) -> Int {
        guard end >= start else { return 0 }
        return Int((end - start) / 1_000_000)
    }
}

enum TutorialPlanControllerError: LocalizedError {
    case noScreen

    var errorDescription: String? {
        switch self {
        case .noScreen:
            return "No screen was available for tutorial planning."
        }
    }
}
