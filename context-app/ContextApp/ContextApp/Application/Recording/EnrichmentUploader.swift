import Foundation
import os

struct RemoteRecording: Codable, Equatable {
    let id: String
    let status: String
    let totalEvents: Int

    enum CodingKeys: String, CodingKey {
        case id = "recording_id"
        case status
        case totalEvents = "total_events"
    }
}

enum EnrichmentUploaderError: LocalizedError {
    case zipFailed(String)
    case requestFailed(Int, String)
    case malformedResponse

    var errorDescription: String? {
        switch self {
        case .zipFailed(let m): return "Failed to zip bundle: \(m)"
        case .requestFailed(let code, let body): return "Upload failed (HTTP \(code)): \(body)"
        case .malformedResponse: return "Upload returned an unparseable response."
        }
    }
}

/// Bundle-to-server uploader. Zips the bundle dir on a background queue and
/// POSTs multipart to the recording-enrichment service.
final class EnrichmentUploader {
    private static let log = Logger(subsystem: "ContextApp.Recording", category: "Uploader")

    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    func upload(bundleDir: URL) async throws -> RemoteRecording {
        let zipURL = try await zipBundle(at: bundleDir)
        defer { try? FileManager.default.removeItem(at: zipURL) }
        let data = try Data(contentsOf: zipURL)

        let boundary = "Boundary-\(UUID().uuidString)"
        var req = URLRequest(url: baseURL.appendingPathComponent("recordings"))
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = Self.multipartBody(boundary: boundary, fieldName: "bundle", fileName: "bundle.zip", data: data)

        let (respData, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw EnrichmentUploaderError.malformedResponse
        }
        if http.statusCode >= 400 {
            let body = String(data: respData, encoding: .utf8) ?? "<\(respData.count) bytes>"
            throw EnrichmentUploaderError.requestFailed(http.statusCode, body)
        }
        do {
            let remote = try JSONDecoder().decode(RemoteRecording.self, from: respData)
            Self.log.info("Uploaded recording_id=\(remote.id) total=\(remote.totalEvents)")
            return remote
        } catch {
            throw EnrichmentUploaderError.malformedResponse
        }
    }

    // MARK: - Helpers

    static func multipartBody(boundary: String, fieldName: String, fileName: String, data: Data) -> Data {
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/zip\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        return body
    }

    private func zipBundle(at dir: URL) async throws -> URL {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<URL, Error>) in
            DispatchQueue.global(qos: .utility).async {
                do {
                    let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).zip")
                    try BundleZipper.zip(directory: dir, to: tmp)
                    cont.resume(returning: tmp)
                } catch {
                    cont.resume(throwing: EnrichmentUploaderError.zipFailed(error.localizedDescription))
                }
            }
        }
    }
}

/// Minimal directory zipper using `NSFileCoordinator`'s built-in `.forUploading` option.
/// This produces a single .zip the server can unpack.
enum BundleZipper {
    enum ZipError: LocalizedError {
        case coordinatorFailed(String)
        var errorDescription: String? { switch self { case .coordinatorFailed(let m): return m } }
    }

    static func zip(directory: URL, to destination: URL) throws {
        let coordinator = NSFileCoordinator()
        var coordinatorError: NSError?
        var thrown: Error?
        coordinator.coordinate(readingItemAt: directory, options: [.forUploading], error: &coordinatorError) { tmpZip in
            do {
                if FileManager.default.fileExists(atPath: destination.path) {
                    try FileManager.default.removeItem(at: destination)
                }
                try FileManager.default.copyItem(at: tmpZip, to: destination)
            } catch {
                thrown = error
            }
        }
        if let coordinatorError {
            throw ZipError.coordinatorFailed(coordinatorError.localizedDescription)
        }
        if let thrown {
            throw thrown
        }
    }
}
