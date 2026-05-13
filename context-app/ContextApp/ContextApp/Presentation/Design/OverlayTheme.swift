import SwiftUI

enum OverlayTheme {
    static let panelCornerRadius: CGFloat = 14
    static let controlCornerRadius: CGFloat = 10
    static let compactCornerRadius: CGFloat = 8
    static let iconSize: CGFloat = 52
    static let hairline = Color.primary.opacity(0.10)
    static let separator = Color.primary.opacity(0.08)
    static let quietFill = Color.primary.opacity(0.045)
    static let strongerFill = Color.primary.opacity(0.075)
    static let assistantBubble = Color.primary.opacity(0.055)
    static let userBubble = Color.accentColor.opacity(0.12)
    static let highlightStroke = Color.accentColor.opacity(0.88)
    static let highlightGlow = Color.accentColor.opacity(0.22)
}

