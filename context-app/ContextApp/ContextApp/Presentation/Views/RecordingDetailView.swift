import AppKit
import Foundation
import SwiftUI

/// One enriched event row, as read off `events.enriched.jsonl` when the
/// recording is in `ready` (or off `events.jsonl` so a still-pending bundle
/// can show its raw timeline).
struct EnrichedRecordingEvent: Identifiable {
    let id: String
    let timestampMs: Int64
    let kind: String
    let cursor: Point
    let frameId: String?
    let targetCropPath: String?
    let contextCropPath: String?
    let targetPhrase: String?
    let visibleText: String?
    let descriptionKind: String?
    let verified: Bool?
    let distancePx: Double?
    /// Populated for kind == "type": the coalesced typed string.
    let typedText: String?
    /// Populated for kind == "type": number of backspaces inside the burst.
    let typedBackspaces: Int?
}

@MainActor
final class RecordingDetailModel: ObservableObject {
    @Published private(set) var events: [EnrichedRecordingEvent] = []
    @Published private(set) var goal: String = ""
    @Published private(set) var error: String?
    @Published private(set) var isEnriched: Bool = false
    @Published var entry: LocalRecordingEntry

    private var bundleURL: URL
    private weak var index: RecordingsIndex?

    init(entry: LocalRecordingEntry, index: RecordingsIndex? = nil) {
        self.entry = entry
        self.bundleURL = URL(fileURLWithPath: entry.bundlePath)
        self.goal = entry.goal
        self.index = index
    }

    func update(entry: LocalRecordingEntry) {
        self.entry = entry
        self.goal = entry.goal
        self.bundleURL = URL(fileURLWithPath: entry.bundlePath)
    }

    func bundleRoot() -> URL { bundleURL }

    func reload() {
        do {
            let enrichedURL = bundleURL.appendingPathComponent("events.enriched.jsonl")
            let rawURL = bundleURL.appendingPathComponent("events.jsonl")
            let sourceURL: URL
            if FileManager.default.fileExists(atPath: enrichedURL.path) {
                sourceURL = enrichedURL
                isEnriched = true
            } else {
                sourceURL = rawURL
                isEnriched = false
            }
            let text = try String(contentsOf: sourceURL, encoding: .utf8)
            events = text
                .split(separator: "\n", omittingEmptySubsequences: true)
                .compactMap(Self.parseLine)
            error = nil
        } catch let readError {
            error = "Could not read events: \(readError.localizedDescription)"
            events = []
        }
    }

    /// Remove a single event from both raw + enriched jsonl (whichever exist),
    /// delete its target/context crops, and decrement the recording's totals
    /// so the list view reflects the new count. Orphaned frame jpegs are left
    /// on disk — they may still be referenced by other events.
    func deleteEvent(id: String) {
        let rawURL = bundleURL.appendingPathComponent("events.jsonl")
        let enrichedURL = bundleURL.appendingPathComponent("events.enriched.jsonl")
        for url in [rawURL, enrichedURL] {
            guard FileManager.default.fileExists(atPath: url.path) else { continue }
            do {
                let text = try String(contentsOf: url, encoding: .utf8)
                let kept = text
                    .split(separator: "\n", omittingEmptySubsequences: true)
                    .filter { Self.eventId(in: String($0)) != id }
                let joined = kept.joined(separator: "\n") + (kept.isEmpty ? "" : "\n")
                try joined.data(using: .utf8)?.write(to: url, options: .atomic)
            } catch {
                self.error = "Failed to rewrite \(url.lastPathComponent): \(error.localizedDescription)"
                return
            }
        }

        let crops = bundleURL.appendingPathComponent("crops")
        try? FileManager.default.removeItem(at: crops.appendingPathComponent("\(id)_target.jpg"))
        try? FileManager.default.removeItem(at: crops.appendingPathComponent("\(id)_context.jpg"))

        events.removeAll { $0.id == id }
        if let idx = index {
            let newTotal = events.count
            let newCompleted = min(entry.completed, newTotal)
            idx.updateStatus(id: entry.id, status: entry.lastStatus, completed: newCompleted, total: newTotal)
            if let refreshed = idx.entry(id: entry.id) { self.entry = refreshed }
        }
    }

    private static func eventId(in line: String) -> String? {
        guard let data = line.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return json["id"] as? String
    }

    private static func parseLine(_ raw: any StringProtocol) -> EnrichedRecordingEvent? {
        guard let data = String(raw).data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = json["id"] as? String else { return nil }
        let timestampMs = (json["timestamp_ms"] as? Int64) ?? Int64((json["timestamp_ms"] as? Int) ?? 0)
        let kind = json["kind"] as? String ?? "?"
        let cursorJSON = json["cursor"] as? [String: Any] ?? [:]
        let cursor = Point(
            x: (cursorJSON["x"] as? Int) ?? 0,
            y: (cursorJSON["y"] as? Int) ?? 0
        )
        let descJSON = json["description"] as? [String: Any]
        let metaJSON = json["description_meta"] as? [String: Any]
        let typingJSON = json["typing"] as? [String: Any]
        return EnrichedRecordingEvent(
            id: id,
            timestampMs: timestampMs,
            kind: kind,
            cursor: cursor,
            frameId: json["frame_id"] as? String,
            targetCropPath: json["target_crop_path"] as? String,
            contextCropPath: json["context_crop_path"] as? String,
            targetPhrase: descJSON?["target_phrase"] as? String,
            visibleText: descJSON?["visible_text"] as? String,
            descriptionKind: descJSON?["kind"] as? String,
            verified: metaJSON?["verified"] as? Bool,
            distancePx: metaJSON?["distance_px"] as? Double,
            typedText: typingJSON?["text"] as? String,
            typedBackspaces: typingJSON?["backspace_count"] as? Int
        )
    }
}

struct RecordingDetailView: View {
    @ObservedObject var model: RecordingDetailModel
    let onClose: () -> Void

    @State private var pendingDelete: EnrichedRecordingEvent?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            if let err = model.error {
                Text(err)
                    .foregroundStyle(.red)
                    .padding()
                Spacer()
            } else if model.events.isEmpty {
                emptyState
            } else {
                eventList
            }
        }
        .frame(minWidth: 640, minHeight: 480)
        .onAppear { model.reload() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Button(action: onClose) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 13, weight: .semibold))
                }
                .buttonStyle(.borderless)
                .help("Back to recordings")

                Text("Recording")
                    .font(.title3.bold())

                Spacer()

                statusBadge
            }

            Text(model.goal)
                .font(.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 12) {
                Text("\(model.events.count) events").font(.caption)
                Text(model.isEnriched ? "enriched" : "raw timeline")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Show in Finder") { revealInFinder() }
                    .buttonStyle(.borderless)
                    .font(.caption)
            }
        }
        .padding(16)
    }

    private var statusBadge: some View {
        let s = model.entry.lastStatus
        let color: Color = {
            switch s {
            case "ready": return .green
            case "failed": return .red
            case "enriching", "pending", "uploading": return .blue
            default: return .gray
            }
        }()
        return Text(s)
            .font(.caption.monospaced())
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.18))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "doc.text")
                .font(.system(size: 32))
                .foregroundStyle(.secondary)
            Text("No events yet")
                .font(.headline)
            Text("Waiting for enrichment to begin.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var eventList: some View {
        List(model.events) { event in
            EventRow(event: event, bundleRoot: model.bundleRoot())
                .contextMenu {
                    Button(role: .destructive) {
                        pendingDelete = event
                    } label: {
                        Label("Delete event", systemImage: "trash")
                    }
                }
                .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                    Button(role: .destructive) {
                        pendingDelete = event
                    } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
        }
        .listStyle(.inset)
        .confirmationDialog(
            "Delete this event?",
            isPresented: Binding(
                get: { pendingDelete != nil },
                set: { if !$0 { pendingDelete = nil } }
            ),
            presenting: pendingDelete
        ) { event in
            Button("Delete", role: .destructive) {
                model.deleteEvent(id: event.id)
                pendingDelete = nil
            }
            Button("Cancel", role: .cancel) { pendingDelete = nil }
        } message: { event in
            Text("Removes the \(event.kind) event from this recording. Crops are deleted; frames stay on disk.")
        }
    }

    private func revealInFinder() {
        NSWorkspace.shared.activateFileViewerSelecting([model.bundleRoot()])
    }
}

private struct EventRow: View {
    let event: EnrichedRecordingEvent
    let bundleRoot: URL

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            targetCrop
                .frame(width: 64, height: 64)
                .background(Color.black.opacity(0.4))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(event.kind)
                        .font(.caption.monospaced())
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.gray.opacity(0.2))
                        .clipShape(Capsule())
                    Text("(\(event.cursor.x), \(event.cursor.y))")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    if let v = event.verified, let dist = event.distancePx {
                        verifyBadge(v: v, dist: dist)
                    }
                    Spacer()
                    Text(timestampLabel)
                        .font(.caption.monospaced())
                        .foregroundStyle(.tertiary)
                }
                if event.kind == "type", let typed = event.typedText {
                    Text("typed \u{201C}\(typed)\u{201D}")
                        .font(.body)
                        .lineLimit(3)
                    if let bs = event.typedBackspaces, bs > 0 {
                        Text("\(bs) backspace\(bs == 1 ? "" : "s")")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                } else if let phrase = event.targetPhrase {
                    Text(phrase)
                        .font(.body)
                        .lineLimit(2)
                } else {
                    Text("(not enriched yet)")
                        .font(.body)
                        .foregroundStyle(.tertiary)
                }
                if let text = event.visibleText, !text.isEmpty {
                    Text("“\(text)”")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var targetCrop: some View {
        if let rel = event.targetCropPath,
           let image = NSImage(contentsOf: bundleRoot.appendingPathComponent(rel)) {
            Image(nsImage: image).resizable().scaledToFit()
        } else if event.kind == "type" {
            Image(systemName: "keyboard").foregroundStyle(.secondary)
        } else {
            Image(systemName: "photo").foregroundStyle(.tertiary)
        }
    }

    private func verifyBadge(v: Bool, dist: Double) -> some View {
        let symbol = v ? "checkmark.seal.fill" : "xmark.seal.fill"
        let color: Color = v ? .green : .red
        return HStack(spacing: 2) {
            Image(systemName: symbol)
                .font(.caption2)
            Text(String(format: "%.0fpx", dist))
                .font(.caption2.monospaced())
        }
        .foregroundStyle(color)
    }

    private var timestampLabel: String {
        let sec = TimeInterval(event.timestampMs) / 1000
        let date = Date(timeIntervalSince1970: sec)
        let fmt = DateFormatter()
        fmt.dateFormat = "HH:mm:ss"
        return fmt.string(from: date)
    }
}
