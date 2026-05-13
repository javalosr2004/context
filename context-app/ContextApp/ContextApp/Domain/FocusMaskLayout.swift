import Foundation

struct FocusMaskLayout {
    let cutoutPadding: CGFloat

    init(cutoutPadding: CGFloat = 10) {
        self.cutoutPadding = cutoutPadding
    }

    func dimmingRects(screenFrame: CGRect, targetFrame: CGRect) -> [CGRect] {
        guard screenFrame.width > 0, screenFrame.height > 0 else { return [] }

        let cutout = paddedCutout(screenFrame: screenFrame, targetFrame: targetFrame)
        guard !cutout.isNull, !cutout.isEmpty else {
            return [screenFrame]
        }

        return [
            topRect(screenFrame: screenFrame, cutout: cutout),
            bottomRect(screenFrame: screenFrame, cutout: cutout),
            leftRect(screenFrame: screenFrame, cutout: cutout),
            rightRect(screenFrame: screenFrame, cutout: cutout),
        ].filter { $0.width > 0 && $0.height > 0 }
    }

    func paddedCutout(screenFrame: CGRect, targetFrame: CGRect) -> CGRect {
        targetFrame
            .insetBy(dx: -cutoutPadding, dy: -cutoutPadding)
            .intersection(screenFrame)
    }

    private func topRect(screenFrame: CGRect, cutout: CGRect) -> CGRect {
        CGRect(
            x: screenFrame.minX,
            y: cutout.maxY,
            width: screenFrame.width,
            height: screenFrame.maxY - cutout.maxY
        )
    }

    private func bottomRect(screenFrame: CGRect, cutout: CGRect) -> CGRect {
        CGRect(
            x: screenFrame.minX,
            y: screenFrame.minY,
            width: screenFrame.width,
            height: cutout.minY - screenFrame.minY
        )
    }

    private func leftRect(screenFrame: CGRect, cutout: CGRect) -> CGRect {
        CGRect(
            x: screenFrame.minX,
            y: cutout.minY,
            width: cutout.minX - screenFrame.minX,
            height: cutout.height
        )
    }

    private func rightRect(screenFrame: CGRect, cutout: CGRect) -> CGRect {
        CGRect(
            x: cutout.maxX,
            y: cutout.minY,
            width: screenFrame.maxX - cutout.maxX,
            height: cutout.height
        )
    }
}
