import Foundation

enum PopupState: Equatable {
    static let minimumSize = CGSize(width: 240, height: 320)

    case expanded(frame: CGRect)
    case minified(iconOrigin: CGPoint)

    func minified(at iconOrigin: CGPoint) -> PopupState {
        .minified(iconOrigin: iconOrigin)
    }

    func expanded(at frame: CGRect) -> PopupState {
        precondition(frame.size.width >= Self.minimumSize.width, "Popup width is below the minimum size")
        precondition(frame.size.height >= Self.minimumSize.height, "Popup height is below the minimum size")
        return .expanded(frame: frame)
    }

    static func == (lhs: PopupState, rhs: PopupState) -> Bool {
        switch (lhs, rhs) {
        case (.expanded(let leftFrame), .expanded(let rightFrame)):
            return leftFrame.origin.x == rightFrame.origin.x
                && leftFrame.origin.y == rightFrame.origin.y
                && leftFrame.size.width == rightFrame.size.width
                && leftFrame.size.height == rightFrame.size.height
        case (.minified(let leftOrigin), .minified(let rightOrigin)):
            return leftOrigin.x == rightOrigin.x && leftOrigin.y == rightOrigin.y
        default:
            return false
        }
    }
}
