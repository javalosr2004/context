import AppKit
import SwiftUI

struct EdgeTabView: View {
    let onClick: () -> Void

    @State private var isHovering = false
    @State private var isPressed = false

    var body: some View {
        RoundedRectangle(cornerRadius: EdgeTabMetrics.cornerRadius, style: .continuous)
            .fill(.ultraThinMaterial)
            .overlay(
                RoundedRectangle(cornerRadius: EdgeTabMetrics.cornerRadius, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 0.5)
            )
            .overlay(glyph)
            .shadow(color: .black.opacity(0.25), radius: 10, y: 4)
            .scaleEffect(x: isHovering ? 1.12 : 1.0, y: isHovering ? 1.04 : 1.0, anchor: .trailing)
            .animation(.easeOut(duration: 0.12), value: isHovering)
            .opacity(isPressed ? 0.75 : 1.0)
            .contentShape(Rectangle())
            .onHover { isHovering = $0 }
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in isPressed = true }
                    .onEnded { _ in
                        isPressed = false
                        onClick()
                    }
            )
    }

    private var glyph: some View {
        Group {
            if let image = NSImage(named: "ContextIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(width: EdgeTabMetrics.glyphSize, height: EdgeTabMetrics.glyphSize)
            } else {
                Image(systemName: "cursorarrow")
                    .font(.system(size: EdgeTabMetrics.glyphSize, weight: .semibold))
                    .foregroundStyle(OverlayTheme.primaryText)
            }
        }
        .opacity(isHovering ? 1.0 : 0.85)
    }
}
