import SwiftUI

enum OverlayTheme {
    static let panelCornerRadius: CGFloat = 14
    static let controlCornerRadius: CGFloat = 10
    static let compactCornerRadius: CGFloat = 8
    static let smallButtonCornerRadius: CGFloat = 7
    static let iconSize: CGFloat = 52
    static let hairline = Color.black.opacity(0.08)
    static let separator = Color.black.opacity(0.08)
    static let quietFill = Color.black.opacity(0.045)
    static let strongerFill = Color.black.opacity(0.075)
    static let assistantBubble = Color.black.opacity(0.055)
    static let userBubble = Color.black.opacity(0.12)
    static let answerSurface = Color.white.opacity(0.55)
    static let askSurface = Color.white.opacity(0.32)
    static let invertedAccent = Color(red: 0.102, green: 0.102, blue: 0.110)
    static let invertedForeground = Color(red: 0.973, green: 0.965, blue: 0.957)
    static let primaryText = Color(red: 0.039, green: 0.039, blue: 0.047)
    static let secondaryText = Color.black.opacity(0.55)
    static let tertiaryText = Color.black.opacity(0.45)
    static let quaternaryText = Color.black.opacity(0.40)
    static let doneText = Color.black.opacity(0.42)
    static let highlightStroke = Color.black.opacity(0.88)
    static let highlightGlow = Color.black.opacity(0.22)
    static let focusDim = Color.black.opacity(0.48)
}
