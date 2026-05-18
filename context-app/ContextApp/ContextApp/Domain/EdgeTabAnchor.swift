import CoreGraphics

enum EdgeTabAnchor {
    static func frame(in visibleFrame: CGRect, size: CGSize, inset: CGSize) -> CGRect {
        let originX = visibleFrame.maxX - size.width - inset.width
        let originY = visibleFrame.minY + inset.height
        return CGRect(origin: CGPoint(x: originX, y: originY), size: size)
    }
}

enum EdgeTabMetrics {
    static let size = CGSize(width: 28, height: 72)
    static let inset = CGSize(width: 6, height: 16)
    static let cornerRadius: CGFloat = 10
    static let glyphSize: CGFloat = 18
}
