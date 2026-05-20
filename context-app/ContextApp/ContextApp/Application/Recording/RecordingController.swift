import AppKit
import Combine
import Foundation
import os

/// Single owner of recording lifecycle: drives `RecordingSession`, persists
/// each finished bundle into `RecordingsIndex`, kicks off the upload, and
/// keeps non-terminal recordings in sync with the backend over SSE.
///
/// Lives once per app and is shared between the menu-bar controller and the
/// chat popup so both UIs can start/stop a recording and reflect the same
/// state.
@MainActor
final class RecordingController: ObservableObject {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "Controller")

    let index: RecordingsIndex
    let enrichmentBaseURL: URL

    @Published private(set) var isRecording: Bool = false
    @Published private(set) var lastError: String?

    private let session: RecordingSession
    private let goalSheet: GoalSheetController
    private let uploader: EnrichmentUploader
    private var streams: [String: EnrichmentStatusStream] = [:]
    private var streamCancellables: [String: Set<AnyCancellable>] = [:]

    init(enrichmentBaseURL: URL = URL(string: "http://localhost:8080")!) {
        self.session = RecordingSession()
        self.goalSheet = GoalSheetController()
        self.index = RecordingsIndex()
        self.enrichmentBaseURL = enrichmentBaseURL
        self.uploader = EnrichmentUploader(baseURL: enrichmentBaseURL)
        attachStreamsForActiveEntries()
    }

    // MARK: - Public

    func toggleRecording() {
        if isRecording {
            Task { await stop() }
        } else {
            Task { await start() }
        }
    }

    func bundleURL(for entry: LocalRecordingEntry) -> URL {
        URL(fileURLWithPath: entry.bundlePath)
    }

    // MARK: - Start / Stop

    private func start() async {
        do {
            let goal = try await goalSheet.prompt()
            _ = try await session.start(goal: goal, screen: NSScreen.main)
            isRecording = true
            lastError = nil
        } catch GoalEntryError.cancelled {
            // no-op
        } catch let RecordingSessionError.permissionsDenied(perms) {
            presentPermissionsAlert(perms: perms)
        } catch {
            presentError(error)
        }
    }

    private func presentPermissionsAlert(perms: RecordingPermissions) {
        let alert = NSAlert()
        alert.messageText = "Permissions required to record"
        var lines: [String] = []
        if perms.needsScreen {
            lines.append("• Screen Recording — capture frames of the workflow.")
        }
        if perms.needsAccessibility {
            lines.append("• Accessibility — observe clicks, scrolls, and keystrokes (read-only).")
        }
        alert.informativeText = lines.joined(separator: "\n")
            + "\n\nGrant the missing permissions in System Settings, then click Record again."
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn {
            let urlString: String = perms.needsAccessibility
                ? "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
                : "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
            if let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
            }
        }
    }

    private func stop() async {
        do {
            let bundleURL = try await session.stop()
            isRecording = false
            let recordingId = bundleURL.lastPathComponent.replacingOccurrences(of: "recording-", with: "")
            let goalText = loadGoalText(from: bundleURL) ?? "(unknown goal)"
            let entry = LocalRecordingEntry(
                id: recordingId,
                bundlePath: bundleURL.path,
                goal: goalText,
                createdAtMs: Int64(Date().timeIntervalSince1970 * 1000),
                remoteId: nil,
                lastStatus: "uploading",
                totalEvents: 0,
                completed: 0,
                failed: 0
            )
            index.upsert(entry)

            do {
                let remote = try await uploader.upload(bundleDir: bundleURL)
                var updated = entry
                updated.remoteId = remote.id
                updated.lastStatus = remote.status
                updated.totalEvents = remote.totalEvents
                index.upsert(updated)
                attachStream(recordingId: remote.id)
            } catch {
                index.updateStatus(id: recordingId, status: "failed")
                presentUploadFailure(bundleURL: bundleURL, error: error)
            }
        } catch {
            isRecording = false
            presentError(error)
        }
    }

    // MARK: - SSE

    private func attachStreamsForActiveEntries() {
        for entry in index.entries where isNonTerminal(entry.lastStatus) {
            let remoteId = entry.remoteId ?? entry.id
            attachStream(recordingId: remoteId)
        }
    }

    private func attachStream(recordingId: String) {
        guard streams[recordingId] == nil else { return }
        let stream = EnrichmentStatusStream(baseURL: enrichmentBaseURL)
        streams[recordingId] = stream
        var bag = Set<AnyCancellable>()
        stream.$status
            .combineLatest(stream.$completed, stream.$total)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status, completed, total in
                guard let self else { return }
                self.index.updateStatus(
                    id: recordingId,
                    status: status.rawValue,
                    completed: completed,
                    total: total > 0 ? total : nil
                )
                if status == .ready || status == .failed {
                    self.detachStream(recordingId: recordingId)
                }
            }
            .store(in: &bag)
        streamCancellables[recordingId] = bag
        stream.connect(recordingId: recordingId)
    }

    private func detachStream(recordingId: String) {
        streams[recordingId]?.disconnect()
        streams[recordingId] = nil
        streamCancellables[recordingId] = nil
    }

    private func isNonTerminal(_ status: String) -> Bool {
        switch status {
        case "ready", "failed": return false
        default: return true
        }
    }

    // MARK: - Helpers

    private func loadGoalText(from bundleURL: URL) -> String? {
        let manifestURL = bundleURL.appendingPathComponent("manifest.json")
        guard let data = try? Data(contentsOf: manifestURL),
              let manifest = try? JSONDecoder().decode(Manifest.self, from: data) else {
            return nil
        }
        return manifest.goal.text
    }

    private func presentError(_ error: Error) {
        lastError = error.localizedDescription
        let alert = NSAlert()
        alert.messageText = "Recording error"
        alert.informativeText = error.localizedDescription
        alert.runModal()
    }

    private func presentUploadFailure(bundleURL: URL, error: Error) {
        let alert = NSAlert()
        alert.messageText = "Recording saved locally (upload failed)"
        alert.informativeText = "\(bundleURL.path)\n\nError: \(error.localizedDescription)"
        alert.runModal()
    }
}
