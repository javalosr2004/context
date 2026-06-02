import AppKit
import CoreGraphics
import CoreImage
import Foundation

enum Cropper {
    static let targetSize: Int = 256
    static let contextSize: Int = 768
    static let jpegQuality: CGFloat = 0.7

    private static let imageContext = CIContext()

    /// Compute a rectangle of side `size` centered on `cursor`, clipped to `frameSize`.
    /// Pure logic — extracted for unit testing without touching CoreImage.
    static func centeredRect(
        around cursor: CGPoint,
        size: Int,
        in frameSize: CGSize
    ) -> CGRect {
        let half = CGFloat(size) / 2
        let x0 = max(0, min(frameSize.width, cursor.x - half))
        let y0 = max(0, min(frameSize.height, cursor.y - half))
        let x1 = max(0, min(frameSize.width, cursor.x + half))
        let y1 = max(0, min(frameSize.height, cursor.y + half))
        return CGRect(x: x0, y: y0, width: max(0, x1 - x0), height: max(0, y1 - y0))
    }

    /// Returns (target, context) JPEG data. nil components mean encode failure
    /// (e.g. zero-area crop at edge).
    static func crop(frame: CapturedFrame, around cursor: CGPoint) -> (target: Data?, context: Data?) {
        let target = encode(jpegData: frame.jpegData, frameSize: frame.pixelSize, rect: centeredRect(around: cursor, size: targetSize, in: frame.pixelSize))
        let context = encode(jpegData: frame.jpegData, frameSize: frame.pixelSize, rect: centeredRect(around: cursor, size: contextSize, in: frame.pixelSize))
        return (target, context)
    }

    private static func encode(jpegData: Data, frameSize: CGSize, rect: CGRect) -> Data? {
        guard rect.width > 0, rect.height > 0 else { return nil }
        guard let source = NSImage(data: jpegData)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        // CGImage origin is top-left in pixel coords; CapturedFrame pixelSize is in pixels.
        // Convert rect from frame coords (top-left origin) to CGImage coords directly.
        let sx = CGFloat(source.width) / frameSize.width
        let sy = CGFloat(source.height) / frameSize.height
        let pixelRect = CGRect(
            x: rect.origin.x * sx,
            y: rect.origin.y * sy,
            width: rect.size.width * sx,
            height: rect.size.height * sy
        ).integral
        guard let cropped = source.cropping(to: pixelRect) else { return nil }
        let rep = NSBitmapImageRep(cgImage: cropped)
        return rep.representation(using: .jpeg, properties: [.compressionFactor: jpegQuality])
    }
}
