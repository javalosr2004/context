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
    private let screenCaptureTimeoutNanoseconds: UInt64

    init(
        endpointStore: TutorialAPIEndpointStore,
        client: TutorialPlanAPIClient = TutorialPlanAPIClient(),
        capture: ScreenFrameCapture = ScreenFrameCapture(),
        conversationID: String = UUID().uuidString,
        ignoredWindowProvider: @escaping () -> [NSWindow] = { [] },
        screenProvider: @escaping () -> NSScreen?,
        screenCaptureTimeoutNanoseconds: UInt64 = 5_000_000_000
    ) {
        self.capture = capture
        self.client = client
        self.conversationID = conversationID
        self.endpointStore = endpointStore
        self.ignoredWindowProvider = ignoredWindowProvider
        self.screenProvider = screenProvider
        self.screenCaptureTimeoutNanoseconds = screenCaptureTimeoutNanoseconds
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

            logger.info(
                "Starting tutorial plan submission conversation_id=\(self.conversationID, privacy: .public) endpoint=\(planURL.absoluteString, privacy: .public) text_chars=\(text.count, privacy: .public)"
            )
            let captureStartedAt = DispatchTime.now().uptimeNanoseconds
            let frame = try await captureFrameWithTimeout(on: screen)
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

    private func captureFrameWithTimeout(on screen: NSScreen) async throws -> CapturedScreenFrame {
        let captureTask = Task {
            try await capture.captureFrame(on: screen)
        }
        let timeoutTask = Task {
            try await Task.sleep(nanoseconds: screenCaptureTimeoutNanoseconds)
            captureTask.cancel()
        }

        defer {
            timeoutTask.cancel()
        }

        do {
            return try await captureTask.value
        } catch is CancellationError {
            throw TutorialPlanControllerError.screenCaptureTimedOut
        }
    }
}

enum TutorialPlanControllerError: LocalizedError {
    case noScreen
    case screenCaptureTimedOut

    var errorDescription: String? {
        switch self {
        case .noScreen:
            return "No screen was available for tutorial planning."
        case .screenCaptureTimedOut:
            return "Screen capture timed out before the tutorial plan request could be sent."
        }
    }
}
