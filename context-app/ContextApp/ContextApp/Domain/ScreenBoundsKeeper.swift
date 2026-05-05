import Foundation

struct ScreenBoundsKeeper {
    func clamp(frame: CGRect, into screen: CGRect, minimumVisible: CGFloat) -> CGRect {
        precondition(minimumVisible >= 0, "minimumVisible must be non-negative")

        var result = frame
        result.origin.x = clampedOrigin(
            origin: result.origin.x,
            length: result.size.width,
            screenMin: screen.origin.x,
            screenMax: screen.origin.x + screen.size.width,
            minimumVisible: minimumVisible
        )
        result.origin.y = clampedOrigin(
            origin: result.origin.y,
            length: result.size.height,
            screenMin: screen.origin.y,
            screenMax: screen.origin.y + screen.size.height,
            minimumVisible: minimumVisible
        )
        return result
    }

    private func clampedOrigin(
        origin: CGFloat,
        length: CGFloat,
        screenMin: CGFloat,
        screenMax: CGFloat,
        minimumVisible: CGFloat
    ) -> CGFloat {
        guard length > 0 else { return origin }

        let visible = min(minimumVisible, length, screenMax - screenMin)
        let lowestOrigin = screenMin + visible - length
        let highestOrigin = screenMax - visible

        if origin < lowestOrigin {
            return lowestOrigin
        }
        if origin > highestOrigin {
            return highestOrigin
        }
        return origin
    }
}
