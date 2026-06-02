import Foundation
import os

/// One semantic SSE frame parsed off the wire.
struct SSEFrame: Equatable {
    let id: Int?
    let event: String?
    let data: String
}

enum SSEParser {
    /// Pure parser: feed accumulated buffer text, get back (frames, leftover).
    /// SSE frames are separated by a blank line.
    static func parse(_ buffer: String) -> (frames: [SSEFrame], leftover: String) {
        var frames: [SSEFrame] = []
        var remaining = buffer
        while let range = remaining.range(of: "\n\n") {
            let block = String(remaining[..<range.lowerBound])
            remaining = String(remaining[range.upperBound...])
            if let frame = parseBlock(block) {
                frames.append(frame)
            }
        }
        return (frames, remaining)
    }

    private static func parseBlock(_ block: String) -> SSEFrame? {
        var id: Int? = nil
        var event: String? = nil
        var dataLines: [String] = []
        for raw in block.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(raw)
            if line.hasPrefix(":") { continue }
            if line.hasPrefix("id:") {
                id = Int(line.dropFirst(3).trimmingCharacters(in: .whitespaces))
            } else if line.hasPrefix("event:") {
                event = String(line.dropFirst(6)).trimmingCharacters(in: .whitespaces)
            } else if line.hasPrefix("data:") {
                dataLines.append(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces))
            }
        }
        if id == nil && event == nil && dataLines.isEmpty { return nil }
        return SSEFrame(id: id, event: event, data: dataLines.joined(separator: "\n"))
    }
}

@MainActor
final class EnrichmentStatusStream: ObservableObject {
    enum Status: String { case pending, enriching, ready, failed }

    @Published var status: Status = .pending
    @Published var completed: Int = 0
    @Published var total: Int = 0
    @Published var lastTargetPhrase: String? = nil

    private static let log = Logger(subsystem: "ContextApp.Recording", category: "StatusStream")

    private let baseURL: URL
    private let session: URLSession
    private var task: Task<Void, Never>? = nil
    private var lastSeenId: Int? = nil

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    func connect(recordingId: String) {
        task?.cancel()
        task = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                do {
                    try await self.runOnce(recordingId: recordingId)
                    return
                } catch {
                    Self.log.warning("sse_disconnect retrying error=\(error.localizedDescription, privacy: .public)")
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                }
            }
        }
    }

    func disconnect() {
        task?.cancel()
        task = nil
    }

    private func runOnce(recordingId: String) async throws {
        var req = URLRequest(url: baseURL.appendingPathComponent("recordings/\(recordingId)/events/stream"))
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if let lastSeenId {
            req.setValue(String(lastSeenId), forHTTPHeaderField: "Last-Event-ID")
        }

        let (bytes, _) = try await session.bytes(for: req)
        var buffer = ""
        for try await line in bytes.lines {
            buffer.append(line)
            buffer.append("\n")
            let (frames, leftover) = SSEParser.parse(buffer)
            buffer = leftover
            for frame in frames {
                await handle(frame)
                if frame.event == "done" {
                    return
                }
            }
        }
    }

    private func handle(_ frame: SSEFrame) async {
        if let id = frame.id { lastSeenId = id }
        guard let data = frame.data.data(using: .utf8) else { return }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        switch frame.event {
        case "enriched":
            if let phrase = json["target_phrase"] as? String {
                lastTargetPhrase = phrase
            }
        case "progress":
            if let completed = json["completed"] as? Int { self.completed = completed }
            if let total = json["total"] as? Int { self.total = total }
            if let status = json["status"] as? String, let s = Status(rawValue: status) { self.status = s }
        case "done":
            if let status = json["status"] as? String, let s = Status(rawValue: status) { self.status = s }
        default:
            break
        }
    }
}
