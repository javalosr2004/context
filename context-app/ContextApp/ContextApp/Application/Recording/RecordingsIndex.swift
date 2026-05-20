import Foundation
import os

struct LocalRecordingEntry: Codable, Identifiable, Equatable {
    let id: String              // local recording UUID, matches manifest.recording_id
    let bundlePath: String      // file URL path
    let goal: String
    let createdAtMs: Int64
    var remoteId: String?       // server-assigned, identical to id today, but distinct field for future-proofing
    var lastStatus: String      // mirrors latest known server status ("uploading", "pending", ...)
    var totalEvents: Int
    var completed: Int
    var failed: Int
}

@MainActor
final class RecordingsIndex {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "Index")

    private let indexURL: URL
    private(set) var entries: [LocalRecordingEntry] = []

    init(baseDirectory: URL = RecordingSession.defaultBaseDirectory()) {
        let dir = baseDirectory
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.indexURL = dir.appendingPathComponent("index.json")
        load()
    }

    func upsert(_ entry: LocalRecordingEntry) {
        if let idx = entries.firstIndex(where: { $0.id == entry.id }) {
            entries[idx] = entry
        } else {
            entries.insert(entry, at: 0)
        }
        persist()
    }

    func updateStatus(id: String, status: String, completed: Int? = nil, total: Int? = nil, failed: Int? = nil) {
        guard let idx = entries.firstIndex(where: { $0.id == id }) else { return }
        entries[idx].lastStatus = status
        if let completed { entries[idx].completed = completed }
        if let total { entries[idx].totalEvents = total }
        if let failed { entries[idx].failed = failed }
        persist()
    }

    func remove(id: String) {
        entries.removeAll { $0.id == id }
        persist()
    }

    private func load() {
        guard let data = try? Data(contentsOf: indexURL) else { return }
        do {
            entries = try JSONDecoder().decode([LocalRecordingEntry].self, from: data)
        } catch {
            Self.log.warning("index_load_failed err=\(error.localizedDescription, privacy: .public)")
        }
    }

    private func persist() {
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(entries)
            try data.write(to: indexURL, options: .atomic)
        } catch {
            Self.log.error("index_persist_failed err=\(error.localizedDescription, privacy: .public)")
        }
    }
}
