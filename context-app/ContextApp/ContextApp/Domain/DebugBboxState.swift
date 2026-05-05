import Foundation

final class DebugBboxState {
    private(set) var current: DebugBoundingBox?

    func replace(with bbox: DebugBoundingBox?) {
        current = bbox
    }
}

