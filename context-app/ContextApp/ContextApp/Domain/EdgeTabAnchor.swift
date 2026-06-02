import CoreGraphics

enum EdgeTabAnchor {
    static func frame(in visibleFrame: CGRect, size: CGSize, inset: CGSize) -> CGRect {
        let originX = visibleFrame.maxX - size.width - inset.width
        let originY = visibleFrame.midY - size.height / 2
        return CGRect(origin: CGPoint(x: originX, y: originY), size: size)
    }
}

enum EdgeTabMetrics {
    static let size = CGSize(width: 22, height: 56)
    static let inset = CGSize(width: 0, height: 0)
    static let cornerRadius: CGFloat = 8
    static let glyphSize: CGFloat = 14
}
