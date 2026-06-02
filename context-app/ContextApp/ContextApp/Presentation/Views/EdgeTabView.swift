import AppKit
import SwiftUI

struct EdgeTabView: View {
    let onClick: () -> Void

    @State private var isHovering = false
    @State private var isPressed = false

    private var shape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: EdgeTabMetrics.cornerRadius,
            bottomLeadingRadius: EdgeTabMetrics.cornerRadius,
            bottomTrailingRadius: 0,
            topTrailingRadius: 0,
            style: .continuous
        )
    }

    var body: some View {
        shape
            .fill(.regularMaterial)
            .overlay(shape.fill(Color.black.opacity(0.06)))
            .overlay(shape.stroke(Color(nsColor: .separatorColor), lineWidth: 0.5))
            .overlay(glyph)
            .shadow(color: .black.opacity(0.18), radius: 8, y: 2)
            .opacity(isHovering ? 1.0 : 0.55)
            .scaleEffect(isPressed ? 0.96 : 1.0, anchor: .trailing)
            .animation(.easeOut(duration: 0.18), value: isHovering)
            .animation(.easeOut(duration: 0.10), value: isPressed)
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
                    .font(.system(size: EdgeTabMetrics.glyphSize, weight: .regular))
                    .foregroundStyle(OverlayTheme.primaryText)
            }
        }
        .offset(x: 1.5)
    }
}
