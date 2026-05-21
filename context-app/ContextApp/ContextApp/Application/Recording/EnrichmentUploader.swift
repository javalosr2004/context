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
        let endpoint = baseURL.appendingPathComponent("recordings")
        let sketch = Self.bundleSketch(at: bundleDir)
        Self.log.info(
            "upload start endpoint=\(endpoint.absoluteString, privacy: .public) bundle=\(bundleDir.lastPathComponent, privacy: .public) \(sketch, privacy: .public)"
        )
        let zipURL: URL
        do {
            zipURL = try await zipBundle(at: bundleDir)
        } catch {
            Self.log.error("upload zip_failed err=\(error.localizedDescription, privacy: .public)")
            throw error
        }
        defer { try? FileManager.default.removeItem(at: zipURL) }
        let data = try Data(contentsOf: zipURL)
        Self.log.info("upload zip_ready bytes=\(data.count, privacy: .public)")

        let boundary = "Boundary-\(UUID().uuidString)"
        var req = URLRequest(url: endpoint)
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = Self.multipartBody(boundary: boundary, fieldName: "bundle", fileName: "bundle.zip", data: data)

        let respData: Data
        let response: URLResponse
        do {
            (respData, response) = try await session.data(for: req)
        } catch {
            Self.log.error(
                "upload transport_failed endpoint=\(endpoint.absoluteString, privacy: .public) err=\(error.localizedDescription, privacy: .public)"
            )
            throw error
        }
        guard let http = response as? HTTPURLResponse else {
            Self.log.error("upload malformed_response non_http")
            throw EnrichmentUploaderError.malformedResponse
        }
        let bodyPreview = String(data: respData.prefix(512), encoding: .utf8) ?? "<\(respData.count) bytes>"
        Self.log.info(
            "upload http_response status=\(http.statusCode, privacy: .public) bytes=\(respData.count, privacy: .public) body=\(bodyPreview, privacy: .public)"
        )
        if http.statusCode >= 400 {
            let body = String(data: respData, encoding: .utf8) ?? "<\(respData.count) bytes>"
            throw EnrichmentUploaderError.requestFailed(http.statusCode, body)
        }
        do {
            let remote = try JSONDecoder().decode(RemoteRecording.self, from: respData)
            Self.log.info("upload ok recording_id=\(remote.id, privacy: .public) total=\(remote.totalEvents, privacy: .public)")
            return remote
        } catch {
            Self.log.error("upload decode_failed body=\(bodyPreview, privacy: .public)")
            throw EnrichmentUploaderError.malformedResponse
        }
    }

    /// One-line summary of the manifest the user is about to upload, for logs.
    /// Returns "manifest_read_failed=..." if the manifest cannot be parsed —
    /// useful signal in itself because that's a bundle bug the server would
    /// reject anyway.
    static func bundleSketch(at bundleDir: URL) -> String {
        let manifestURL = bundleDir.appendingPathComponent("manifest.json")
        let eventsURL = bundleDir.appendingPathComponent("events.jsonl")
        let framesDir = bundleDir.appendingPathComponent("frames")
        guard let data = try? Data(contentsOf: manifestURL) else {
            return "manifest_missing=\(manifestURL.path)"
        }
        let manifest: Manifest
        do {
            manifest = try JSONDecoder().decode(Manifest.self, from: data)
        } catch {
            return "manifest_decode_failed=\(error.localizedDescription)"
        }
        let eventCount = (try? String(contentsOf: eventsURL, encoding: .utf8))?
            .split(whereSeparator: { $0.isNewline })
            .count ?? -1
        let frameCount = (try? FileManager.default.contentsOfDirectory(atPath: framesDir.path).count) ?? -1
        return "recording_id=\(manifest.recordingId) schema_version=\(manifest.schemaVersion) "
            + "app_version=\(manifest.appVersion) goal_chars=\(manifest.goal.text.count) "
            + "events=\(eventCount) frames=\(frameCount) aborted=\(manifest.aborted)"
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
