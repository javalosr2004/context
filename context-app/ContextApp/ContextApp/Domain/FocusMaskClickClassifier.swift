import Foundation

enum FocusMaskClickTarget: Equatable {
    case ignoredControl
    case insideCutout
    case outsideCutout
}

struct FocusMaskClickClassifier {
    func target(
        for point: CGPoint,
        cutout: CGRect,
        isIgnoredControl: Bool
    ) -> FocusMaskClickTarget? {
        guard !cutout.isNull, !cutout.isEmpty else { return nil }
        guard !isIgnoredControl else { return .ignoredControl }

        return cutout.contains(point) ? .insideCutout : .outsideCutout
    }
}
