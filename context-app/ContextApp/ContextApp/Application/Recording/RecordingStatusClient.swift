import Foundation
import os

struct RecordingStatusSnapshot: Decodable, Equatable {
    let status: String
    let total: Int
    let completed: Int
    let failed: Int
}

enum RecordingStatusClientError: Error {
    case notFound
    case badResponse(Int)
    case malformed
}

/// One-shot GET /recordings/{id}/status. Used to repair drift when the list
/// view reopens — the SSE stream is the live channel, this is the corrective.
final class RecordingStatusClient {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "StatusClient")

    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    func fetch(recordingId: String) async throws -> RecordingStatusSnapshot {
        let url = baseURL
            .appendingPathComponent("recordings")
            .appendingPathComponent(recordingId)
            .appendingPathComponent("status")
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw RecordingStatusClientError.malformed
        }
        if http.statusCode == 404 {
            throw RecordingStatusClientError.notFound
        }
        if http.statusCode >= 400 {
            throw RecordingStatusClientError.badResponse(http.statusCode)
        }
        do {
            return try JSONDecoder().decode(RecordingStatusSnapshot.self, from: data)
        } catch {
            Self.log.warning("status_decode_failed id=\(recordingId, privacy: .public)")
            throw RecordingStatusClientError.malformed
        }
    }
}
