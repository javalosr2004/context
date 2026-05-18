import CoreGraphics

enum EdgeTabAnchor {
    static func frame(in visibleFrame: CGRect, size: CGSize, inset: CGSize) -> CGRect {
        let originX = visibleFrame.maxX - size.width - inset.width
        let originY = visibleFrame.minY + inset.height
        return CGRect(origin: CGPoint(x: originX, y: originY), size: size)
    }
}

enum EdgeTabMetrics {
    static let size = CGSize(width: 8, height: 56)
    static let inset = CGSize(width: 8, height: 12)
    static let hoverSize = CGSize(width: 12, height: 64)
}
