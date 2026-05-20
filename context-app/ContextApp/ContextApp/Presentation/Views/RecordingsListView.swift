import SwiftUI

@MainActor
final class RecordingsListModel: ObservableObject {
    @Published var entries: [LocalRecordingEntry] = []
    private let index: RecordingsIndex

    init(index: RecordingsIndex) {
        self.index = index
        reload()
    }

    func reload() {
        entries = index.entries
    }
}

struct RecordingsListView: View {
    @ObservedObject var model: RecordingsListModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Recordings").font(.title2.bold())
                Spacer()
                Button("Refresh") { model.reload() }
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)

            if model.entries.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "record.circle")
                        .font(.system(size: 40))
                        .foregroundStyle(.secondary)
                    Text("No recordings yet").font(.headline)
                    Text("Start one from the menu bar: Record…")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(model.entries) { entry in
                    RecordingRow(entry: entry)
                }
                .listStyle(.inset)
            }
        }
        .frame(minWidth: 420, minHeight: 320)
    }
}

private struct RecordingRow: View {
    let entry: LocalRecordingEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(entry.goal).font(.body).lineLimit(2)
            HStack(spacing: 8) {
                Text("\(entry.totalEvents) events").font(.caption).foregroundStyle(.secondary)
                StatusPill(status: entry.lastStatus, completed: entry.completed, total: entry.totalEvents)
                Spacer()
                Text(entry.bundlePath).font(.caption).foregroundStyle(.tertiary).lineLimit(1)
            }
        }
        .padding(.vertical, 4)
    }
}

private struct StatusPill: View {
    let status: String
    let completed: Int
    let total: Int

    var body: some View {
        Text(label)
            .font(.caption.monospaced())
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(color.opacity(0.18))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private var label: String {
        switch status {
        case "enriching": return "enriching \(completed)/\(total)"
        case "ready": return "ready"
        case "failed": return "failed"
        case "uploading": return "uploading"
        case "pending": return "pending"
        default: return status
        }
    }

    private var color: Color {
        switch status {
        case "ready": return .green
        case "failed": return .red
        case "enriching", "uploading", "pending": return .blue
        default: return .gray
        }
    }
}
