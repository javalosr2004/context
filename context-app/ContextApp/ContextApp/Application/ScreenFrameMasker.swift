import AppKit
import CoreImage
import Foundation

enum ScreenFrameMaskerError: LocalizedError {
    case imageDecodingFailed
    case imageEncodingFailed

    var errorDescription: String? {
        switch self {
        case .imageDecodingFailed:
            return "Could not decode the captured screen image before masking."
        case .imageEncodingFailed:
            return "Could not encode the masked screen image."
        }
    }
}

struct ScreenFrameMasker {
    private static let imageContext = CIContext()

    static func mask(
        jpegData: Data,
        screenFrame: CGRect,
        ignoredWindowFrames: [CGRect],
        padding: CGFloat = 12
    ) throws -> Data {
        guard !ignoredWindowFrames.isEmpty else { return jpegData }
        guard let image = CIImage(data: jpegData) else {
            throw ScreenFrameMaskerError.imageDecodingFailed
        }

        let imageBounds = image.extent
        let imageSize = CGSize(width: imageBounds.width, height: imageBounds.height)
        let maskColor = CIImage(color: CIColor(red: 0, green: 0, blue: 0, alpha: 1))

        let maskedImage = ignoredWindowFrames.reduce(image) { currentImage, windowFrame in
            guard let maskRect = pixelRect(
                for: windowFrame,
                screenFrame: screenFrame,
                imageSize: imageSize,
                padding: padding
            )?.intersection(imageBounds), !maskRect.isNull else {
                return currentImage
            }

            return maskColor
                .cropped(to: maskRect.integral)
                .composited(over: currentImage)
        }

        guard let cgImage = imageContext.createCGImage(maskedImage, from: imageBounds) else {
            throw ScreenFrameMaskerError.imageEncodingFailed
        }

        let bitmap = NSBitmapImageRep(cgImage: cgImage)
        guard let maskedData = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.86]) else {
            throw ScreenFrameMaskerError.imageEncodingFailed
        }

        return maskedData
    }

    static func pixelRect(
        for windowFrame: CGRect,
        screenFrame: CGRect,
        imageSize: CGSize,
        padding: CGFloat = 12
    ) -> CGRect? {
        guard screenFrame.width > 0, screenFrame.height > 0 else { return nil }
        guard imageSize.width > 0, imageSize.height > 0 else { return nil }

        let paddedFrame = windowFrame.insetBy(dx: -padding, dy: -padding)
        let visibleFrame = paddedFrame.intersection(screenFrame)
        guard !visibleFrame.isNull, !visibleFrame.isEmpty else { return nil }

        let scaleX = imageSize.width / screenFrame.width
        let scaleY = imageSize.height / screenFrame.height

        return CGRect(
            x: (visibleFrame.minX - screenFrame.minX) * scaleX,
            y: (visibleFrame.minY - screenFrame.minY) * scaleY,
            width: visibleFrame.width * scaleX,
            height: visibleFrame.height * scaleY
        )
    }
}
