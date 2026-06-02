import Foundation

enum PopupState: Equatable {
    static let minimumSize = CGSize(width: 240, height: 320)

    case expanded(frame: CGRect)
    case collapsed(lastFrame: CGRect)

    func collapsed(lastFrame: CGRect) -> PopupState {
        .collapsed(lastFrame: lastFrame)
    }

    func expanded(at frame: CGRect) -> PopupState {
        precondition(frame.size.width >= Self.minimumSize.width, "Popup width is below the minimum size")
        precondition(frame.size.height >= Self.minimumSize.height, "Popup height is below the minimum size")
        return .expanded(frame: frame)
    }

    var lastExpandedFrame: CGRect {
        switch self {
        case .expanded(let frame): return frame
        case .collapsed(let lastFrame): return lastFrame
        }
    }

    static func == (lhs: PopupState, rhs: PopupState) -> Bool {
        switch (lhs, rhs) {
        case (.expanded(let l), .expanded(let r)):
            return Self.rectsEqual(l, r)
        case (.collapsed(let l), .collapsed(let r)):
            return Self.rectsEqual(l, r)
        default:
            return false
        }
    }

    private static func rectsEqual(_ a: CGRect, _ b: CGRect) -> Bool {
        a.origin.x == b.origin.x
            && a.origin.y == b.origin.y
            && a.size.width == b.size.width
            && a.size.height == b.size.height
    }
}
