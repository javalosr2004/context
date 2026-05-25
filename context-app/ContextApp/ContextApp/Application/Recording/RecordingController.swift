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
    @Published private(set) var isRefreshing: Bool = false

    private let session: RecordingSession
    private let goalSheet: GoalSheetController
    private let uploader: EnrichmentUploader
    private let statusClient: RecordingStatusClient
    private var streams: [String: EnrichmentStatusStream] = [:]
    private var streamCancellables: [String: Set<AnyCancellable>] = [:]

    init(enrichmentBaseURL: URL = URL(string: "http://localhost:8080")!) {
        self.session = RecordingSession()
        self.goalSheet = GoalSheetController()
        self.index = RecordingsIndex()
        self.enrichmentBaseURL = enrichmentBaseURL
        self.uploader = EnrichmentUploader(baseURL: enrichmentBaseURL)
        self.statusClient = RecordingStatusClient(baseURL: enrichmentBaseURL)
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
            await performUpload(entry: entry, presentFailure: true)
        } catch {
            isRecording = false
            presentError(error)
        }
    }

    /// Retry an upload from the recordings list. The bundle on disk is the
    /// source of truth — no re-recording happens. Surfaces no modal alert on
    /// failure; the row's status pill goes back to "failed" and the user can
    /// retry again from the same UI.
    func retryUpload(entryId: String) async {
        guard let entry = index.entry(id: entryId) else {
            Self.log.warning("retry_upload missing_entry id=\(entryId, privacy: .public)")
            return
        }
        let bundleURL = URL(fileURLWithPath: entry.bundlePath)
        guard FileManager.default.fileExists(atPath: bundleURL.path) else {
            Self.log.error("retry_upload missing_bundle path=\(bundleURL.path, privacy: .public)")
            index.updateStatus(id: entry.id, status: "failed")
            return
        }
        Self.log.info(
            "retry_upload start id=\(entry.id, privacy: .public) bundle=\(bundleURL.path, privacy: .public)"
        )
        index.updateStatus(id: entry.id, status: "uploading")
        await performUpload(entry: entry, presentFailure: false)
    }

    private func performUpload(entry: LocalRecordingEntry, presentFailure: Bool) async {
        let bundleURL = URL(fileURLWithPath: entry.bundlePath)
        do {
            let remote = try await uploader.upload(bundleDir: bundleURL)
            var updated = entry
            updated.remoteId = remote.id
            updated.lastStatus = remote.status
            updated.totalEvents = remote.totalEvents
            index.upsert(updated)
            Self.log.info(
                "upload_completed id=\(entry.id, privacy: .public) remote=\(remote.id, privacy: .public) status=\(remote.status, privacy: .public)"
            )
            attachStream(recordingId: remote.id)
        } catch {
            Self.log.error(
                "upload_failed id=\(entry.id, privacy: .public) err=\(error.localizedDescription, privacy: .public)"
            )
            index.updateStatus(id: entry.id, status: "failed")
            if presentFailure {
                presentUploadFailure(bundleURL: bundleURL, error: error)
            }
        }
    }

    // MARK: - Refresh

    /// Called by the list view when it appears. Fetches the authoritative
    /// status for every non-terminal entry and reattaches any SSE stream
    /// that has dropped. SSE is the live channel; this repairs drift.
    func refreshStatuses() async {
        guard !isRefreshing else { return }
        let targets = index.entries.filter { isNonTerminal($0.lastStatus) }
        guard !targets.isEmpty else { return }
        isRefreshing = true
        defer { isRefreshing = false }

        await withTaskGroup(of: Void.self) { group in
            for entry in targets {
                let remoteId = entry.remoteId ?? entry.id
                // Skip entries that never got past local "uploading" — no
                // server row exists for them yet.
                guard entry.remoteId != nil || entry.lastStatus != "uploading" else { continue }
                group.addTask { [weak self] in
                    await self?.refreshOne(entryId: entry.id, recordingId: remoteId)
                }
            }
        }
    }

    private func refreshOne(entryId: String, recordingId: String) async {
        do {
            let snap = try await statusClient.fetch(recordingId: recordingId)
            index.updateStatus(
                id: entryId,
                status: snap.status,
                completed: snap.completed,
                total: snap.total > 0 ? snap.total : nil,
                failed: snap.failed
            )
            if isNonTerminal(snap.status) {
                attachStream(recordingId: recordingId)
            } else {
                detachStream(recordingId: recordingId)
            }
        } catch RecordingStatusClientError.notFound {
            Self.log.warning("refresh_status not_found id=\(entryId, privacy: .public)")
        } catch {
            Self.log.warning(
                "refresh_status failed id=\(entryId, privacy: .public) err=\(error.localizedDescription, privacy: .public)"
            )
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
