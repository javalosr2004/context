import Foundation
import OSLog
#if canImport(UIKit)
import UIKit
typealias PlatformImage = UIImage
#else
import AppKit
typealias PlatformImage = NSImage
#endif

struct GroundingInstruction {
    let text: String
    let referenceImageData: Data?
    let imageEncodingConfig: ScreenFrameEncodingConfig
    let submittedAtUptimeNanoseconds: UInt64?
    let tooltip: String?
    let copiableText: String?

    init(
        text: String,
        referenceImageData: Data?,
        imageEncodingConfig: ScreenFrameEncodingConfig,
        submittedAtUptimeNanoseconds: UInt64?,
        tooltip: String? = nil,
        copiableText: String? = nil
    ) {
        self.text = text
        self.referenceImageData = referenceImageData
        self.imageEncodingConfig = imageEncodingConfig
        self.submittedAtUptimeNanoseconds = submittedAtUptimeNanoseconds
        self.tooltip = tooltip
        self.copiableText = copiableText
    }
}

enum GroundingClientError: LocalizedError {
    case missingEndpoint
    case invalidEndpoint(String)
    case invalidResponse
    case requestFailed(Int, String)
    case encodingFailed
    case missingBoundingBox

    var errorDescription: String? {
        switch self {
        case .missingEndpoint:
            return "Set CONTEXT_GROUNDING_ENDPOINT before sending an instruction."
        case .invalidEndpoint(let value):
            return "CONTEXT_GROUNDING_ENDPOINT is not a valid URL: \(value)"
        case .invalidResponse:
            return "The grounding endpoint did not return an HTTP response."
        case .requestFailed(let statusCode, let message):
            return "The grounding endpoint returned HTTP \(statusCode): \(message)"
        case .encodingFailed:
            return "Could not encode the grounding image as JPEG."
        case .missingBoundingBox:
            return "The grounding endpoint did not return a bounding box."
        }
    }
}

struct GuiActorResponse: Decodable {
    struct Point: Decodable {
        let x: Double
        let y: Double
    }

    struct Bbox: Decodable {
        let x1: Double
        let y1: Double
        let x2: Double
        let y2: Double
    }

    struct Size: Decodable {
        let width: Int
        let height: Int
    }

    let point: Point
    let pointPixel: Point
    let bbox: Bbox?
    let bboxPixel: Bbox?
    let bboxScore: Double?
    let bboxLabel: String?
    let bboxSource: String
    let imageSize: Size
    let numDetections: Int

    private enum CodingKeys: String, CodingKey {
        case point
        case pointPixel = "point_pixel"
        case bbox
        case bboxPixel = "bbox_pixel"
        case bboxScore = "bbox_score"
        case bboxLabel = "bbox_label"
        case bboxSource = "bbox_source"
        case imageSize = "image_size"
        case numDetections = "num_detections"
    }
}

enum GuiActorImageEncoder {
    static func jpegData(
        from imageData: Data,
        compressionQuality: CGFloat = ScreenFrameEncodingConfig.groundingRequest.jpegCompressionQuality,
        maxPixelWidth: Int = ScreenFrameEncodingConfig.groundingRequest.maxPixelWidth
    ) -> Data? {
        guard let image = PlatformImage(data: imageData) else { return nil }
        return jpegData(
            from: image,
            compressionQuality: compressionQuality,
            maxPixelWidth: maxPixelWidth
        )
    }

    static func jpegData(
        from image: PlatformImage,
        compressionQuality: CGFloat = ScreenFrameEncodingConfig.groundingRequest.jpegCompressionQuality,
        maxPixelWidth: Int = ScreenFrameEncodingConfig.groundingRequest.maxPixelWidth
    ) -> Data? {
        #if canImport(UIKit)
        let targetSize = ScreenFrameEncodingConfig(
            jpegCompressionQuality: compressionQuality,
            maxPixelWidth: maxPixelWidth
        ).scaledPixelSize(for: image.size)
        let outputImage: UIImage
        if targetSize == image.size {
            outputImage = image
        } else {
            let renderer = UIGraphicsImageRenderer(size: targetSize)
            outputImage = renderer.image { _ in
                image.draw(in: CGRect(origin: .zero, size: targetSize))
            }
        }
        return outputImage.jpegData(compressionQuality: compressionQuality)
        #else
        guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        let targetSize = ScreenFrameEncodingConfig(
            jpegCompressionQuality: compressionQuality,
            maxPixelWidth: maxPixelWidth
        ).scaledPixelSize(for: CGSize(width: cgImage.width, height: cgImage.height))
        let outputImage = resizedImage(cgImage, to: targetSize) ?? cgImage
        let bitmap = NSBitmapImageRep(cgImage: outputImage)
        return bitmap.representation(using: .jpeg, properties: [.compressionFactor: compressionQuality])
        #endif
    }

    #if !canImport(UIKit)
    private static func resizedImage(_ image: CGImage, to size: CGSize) -> CGImage? {
        guard size.width > 0, size.height > 0 else { return nil }
        guard Int(size.width) != image.width || Int(size.height) != image.height else {
            return image
        }

        let colorSpace = image.colorSpace ?? CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: nil,
            width: Int(size.width),
            height: Int(size.height),
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        ) else {
            return nil
        }

        context.interpolationQuality = .high
        context.draw(image, in: CGRect(origin: .zero, size: size))
        return context.makeImage()
    }
    #endif
}

final class GroundingClient {
    private let logger = Logger(subsystem: "ContextApp", category: "GuiActor")
    private let endpoint: URL
    private let session: URLSession

    init(endpoint: URL, session: URLSession = .shared) {
        self.endpoint = endpoint
        self.session = session
    }

    static func fromEnvironment(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> GroundingClient {
        guard let value = environment["CONTEXT_GROUNDING_ENDPOINT"], !value.isEmpty else {
            throw GroundingClientError.missingEndpoint
        }

        guard let url = URL(string: value), url.scheme != nil else {
            throw GroundingClientError.invalidEndpoint(value)
        }

        return GroundingClient(endpoint: url)
    }

    static func fromEndpointStore(_ endpointStore: GroundingEndpointStore) throws -> GroundingClient {
        guard let value = endpointStore.endpoint else {
            throw GroundingClientError.missingEndpoint
        }

        guard let url = URL(string: value), url.scheme != nil else {
            throw GroundingClientError.invalidEndpoint(value)
        }

        return GroundingClient(endpoint: url)
    }

    func locate(instruction: GroundingInstruction, screenshotJPEGData: Data) async throws -> GroundingBoundingBox {
        let response = try await predict(
            inputImageJPEGData: screenshotJPEGData,
            referenceImageJPEGData: referenceJPEGData(from: instruction),
            instruction: instruction.text
        )

        guard let boundingBox = GroundingBoundingBox(guiActorResponse: response) else {
            throw GroundingClientError.missingBoundingBox
        }

        return boundingBox
    }

    func predict(
        inputImage: PlatformImage,
        referenceImage: PlatformImage? = nil,
        instruction: String? = nil,
        scoreThreshold: Double = 0.3
    ) async throws -> GuiActorResponse {
        guard let inputData = GuiActorImageEncoder.jpegData(from: inputImage) else {
            throw GroundingClientError.encodingFailed
        }

        let referenceData = referenceImage.flatMap { GuiActorImageEncoder.jpegData(from: $0) }
        return try await predict(
            inputImageJPEGData: inputData,
            referenceImageJPEGData: referenceData,
            instruction: instruction,
            scoreThreshold: scoreThreshold
        )
    }

    func predict(
        inputImageJPEGData: Data,
        referenceImageJPEGData: Data? = nil,
        instruction: String? = nil,
        scoreThreshold: Double = 0.3
    ) async throws -> GuiActorResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        let requestURL = predictionURL(from: endpoint)
        var request = URLRequest(url: requestURL)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let requestBody = multipartBody(
            boundary: boundary,
            inputImageJPEGData: inputImageJPEGData,
            referenceImageJPEGData: referenceImageJPEGData,
            instruction: instruction,
            scoreThreshold: scoreThreshold
        )
        logger.info(
            "Calling GUI actor predict at \(requestURL.absoluteString, privacy: .public) inputBytes=\(inputImageJPEGData.count, privacy: .public) referenceBytes=\(referenceImageJPEGData?.count ?? 0, privacy: .public)"
        )
        let (data, response) = try await session.upload(for: request, from: requestBody)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw GroundingClientError.invalidResponse
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? ""
            logger.error(
                "GUI actor predict failed status=\(httpResponse.statusCode, privacy: .public) response=\(message, privacy: .public)"
            )
            throw GroundingClientError.requestFailed(httpResponse.statusCode, message)
        }

        let responseBody = String(data: data, encoding: .utf8) ?? "<non-utf8 \(data.count) bytes>"
        logger.info(
            "GUI actor predict response status=\(httpResponse.statusCode, privacy: .public) body=\(responseBody, privacy: .public)"
        )
        return try JSONDecoder().decode(GuiActorResponse.self, from: data)
    }

    static func predictionURL(from serverURL: URL) -> URL {
        guard serverURL.lastPathComponent != "predict" else { return serverURL }
        return serverURL.appendingPathComponent("predict")
    }

    private func predictionURL(from serverURL: URL) -> URL {
        Self.predictionURL(from: serverURL)
    }

    private func referenceJPEGData(from instruction: GroundingInstruction) throws -> Data? {
        guard let referenceImageData = instruction.referenceImageData else { return nil }
        guard let jpegData = GuiActorImageEncoder.jpegData(
            from: referenceImageData,
            compressionQuality: instruction.imageEncodingConfig.jpegCompressionQuality,
            maxPixelWidth: instruction.imageEncodingConfig.maxPixelWidth
        ) else {
            throw GroundingClientError.encodingFailed
        }

        return jpegData
    }

    private func multipartBody(
        boundary: String,
        inputImageJPEGData: Data,
        referenceImageJPEGData: Data?,
        instruction: String?,
        scoreThreshold: Double
    ) -> Data {
        var body = Data()
        appendFile(
            name: "input_image",
            filename: "screen.jpg",
            data: inputImageJPEGData,
            boundary: boundary,
            body: &body
        )

        if let referenceImageJPEGData {
            appendFile(
                name: "reference_image",
                filename: "ref.jpg",
                data: referenceImageJPEGData,
                boundary: boundary,
                body: &body
            )
        }

        if let instruction {
            appendField("instruction", instruction, boundary: boundary, body: &body)
        }
        appendField("score_threshold", String(scoreThreshold), boundary: boundary, body: &body)
        append("--\(boundary)--\r\n", to: &body)
        return body
    }

    private func appendFile(
        name: String,
        filename: String,
        data: Data,
        boundary: String,
        body: inout Data
    ) {
        append("--\(boundary)\r\n", to: &body)
        append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n", to: &body)
        append("Content-Type: image/jpeg\r\n\r\n", to: &body)
        body.append(data)
        append("\r\n", to: &body)
    }

    private func appendField(_ name: String, _ value: String, boundary: String, body: inout Data) {
        append("--\(boundary)\r\n", to: &body)
        append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n", to: &body)
        append("\(value)\r\n", to: &body)
    }

    private func append(_ value: String, to body: inout Data) {
        body.append(Data(value.utf8))
    }
}

extension GroundingBoundingBox {
    init?(guiActorResponse response: GuiActorResponse) {
        if let bbox = response.bbox {
            self.init(values: [bbox.x1, bbox.y1, bbox.x2 - bbox.x1, bbox.y2 - bbox.y1])
            return
        }

        guard let bbox = response.bboxPixel,
              response.imageSize.width > 0,
              response.imageSize.height > 0 else {
            return nil
        }

        let width = Double(response.imageSize.width)
        let height = Double(response.imageSize.height)
        self.init(values: [
            bbox.x1 / width,
            bbox.y1 / height,
            (bbox.x2 - bbox.x1) / width,
            (bbox.y2 - bbox.y1) / height
        ])
    }
}
