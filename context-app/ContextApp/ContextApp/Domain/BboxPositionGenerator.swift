import Foundation

struct DebugBoundingBox: Equatable {
    static let size = CGSize(width: 500, height: 500)

    let origin: CGPoint

    static func == (lhs: DebugBoundingBox, rhs: DebugBoundingBox) -> Bool {
        lhs.origin.x == rhs.origin.x && lhs.origin.y == rhs.origin.y
    }
}

struct BboxPositionGenerator {
    func position<R: RandomNumberGenerator>(
        screen: CGSize,
        bbox: CGSize = DebugBoundingBox.size,
        rng: inout R
    ) -> CGPoint {
        precondition(screen.width >= bbox.width, "Screen width must fit bbox")
        precondition(screen.height >= bbox.height, "Screen height must fit bbox")

        let maxX = screen.width - bbox.width
        let maxY = screen.height - bbox.height

        return CGPoint(
            x: CGFloat.random(in: 0...maxX, using: &rng),
            y: CGFloat.random(in: 0...maxY, using: &rng)
        )
    }
}
