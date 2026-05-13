import AppKit
import SwiftUI

struct IconView: View {
    let onRestore: () -> Void
    let onContextMenu: () -> Void
    let onDrag: (CGSize) -> Void

    @State private var dragStartDate: Date?
    @State private var lastDragTranslation = CGSize.zero
    @State private var shouldRestoreOnRelease = true

    var body: some View {
        ZStack {
            Circle()
                .fill(.ultraThinMaterial)
                .overlay(
                    Circle()
                        .stroke(OverlayTheme.hairline, lineWidth: 1)
                )

            contextIcon
                .frame(width: 34, height: 38)
        }
        .frame(width: OverlayTheme.iconSize, height: OverlayTheme.iconSize)
        .contentShape(Circle())
        .shadow(color: .black.opacity(0.20), radius: 14, y: 6)
        .gesture(dragToMoveOrRestore)
        .simultaneousGesture(
            TapGesture()
                .modifiers(.control)
                .onEnded(onContextMenu)
        )
        .contextMenu {
            Menu("Overlay") {
                Button("Show target highlight", action: onContextMenu)
            }
        }
    }

    private var dragToMoveOrRestore: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if dragStartDate == nil {
                    dragStartDate = Date()
                    lastDragTranslation = .zero
                    shouldRestoreOnRelease = true
                }

                let delta = CGSize(
                    width: value.translation.width - lastDragTranslation.width,
                    height: value.translation.height - lastDragTranslation.height
                )
                lastDragTranslation = value.translation

                if abs(value.translation.width) > 3 || abs(value.translation.height) > 3 {
                    shouldRestoreOnRelease = false
                    onDrag(CGSize(width: delta.width, height: -delta.height))
                }
            }
            .onEnded { _ in
                if shouldRestoreOnRelease {
                    onRestore()
                }

                dragStartDate = nil
                lastDragTranslation = .zero
                shouldRestoreOnRelease = true
            }
    }

    private var contextIcon: some View {
        Group {
            if let image = NSImage(named: "ContextIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: "cursorarrow")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
    }
}
