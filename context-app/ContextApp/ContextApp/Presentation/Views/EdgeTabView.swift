import AppKit
import SwiftUI

struct EdgeTabView: View {
    let onClick: () -> Void
    let onContextMenu: () -> Void

    @State private var isHovering = false
    @State private var isPressed = false

    var body: some View {
        RoundedRectangle(cornerRadius: 4, style: .continuous)
            .fill(.ultraThinMaterial)
            .overlay(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 0.5)
            )
            .overlay(glyph.opacity(isHovering ? 1 : 0.7))
            .scaleEffect(x: isHovering ? 1.4 : 1.0, y: 1.0, anchor: .trailing)
            .animation(.easeOut(duration: 0.12), value: isHovering)
            .opacity(isPressed ? 0.7 : 1.0)
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
            .contextMenu {
                Button("Show Overlay", action: onClick)
                Divider()
                Button("Quit") { NSApplication.shared.terminate(nil) }
            }
    }

    private var glyph: some View {
        Group {
            if let image = NSImage(named: "ContextIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 6, height: 6)
            } else {
                Circle()
                    .fill(OverlayTheme.secondaryText)
                    .frame(width: 4, height: 4)
            }
        }
    }
}
