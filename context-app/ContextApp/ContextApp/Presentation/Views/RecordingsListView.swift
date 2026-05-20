import SwiftUI

struct RecordingsListView: View {
    @ObservedObject var index: RecordingsIndex
    let onOpen: (LocalRecordingEntry) -> Void
    let onStartRecording: () -> Void
    let isRecording: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Recordings").font(.title2.bold())
                Spacer()
                Button(action: onStartRecording) {
                    HStack(spacing: 4) {
                        Image(systemName: isRecording ? "stop.circle.fill" : "record.circle")
                        Text(isRecording ? "Stop" : "Record")
                    }
                }
                .keyboardShortcut("r", modifiers: [.command])
                .tint(isRecording ? .red : .accentColor)
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)

            if index.entries.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "record.circle")
                        .font(.system(size: 40))
                        .foregroundStyle(.secondary)
                    Text("No recordings yet").font(.headline)
                    Text("Click Record to capture a workflow.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(index.entries) { entry in
                    Button(action: { onOpen(entry) }) {
                        RecordingRow(entry: entry)
                    }
                    .buttonStyle(.plain)
                }
                .listStyle(.inset)
            }
        }
        .frame(minWidth: 460, minHeight: 360)
    }
}

private struct RecordingRow: View {
    let entry: LocalRecordingEntry

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "record.circle.fill")
                .foregroundStyle(.secondary)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 4) {
                Text(entry.goal).font(.body).lineLimit(2)
                HStack(spacing: 8) {
                    Text("\(entry.totalEvents) events").font(.caption).foregroundStyle(.secondary)
                    StatusPill(status: entry.lastStatus, completed: entry.completed, total: entry.totalEvents)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
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
