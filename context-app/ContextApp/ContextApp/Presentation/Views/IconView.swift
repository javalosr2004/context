import SwiftUI

struct IconView: View {
    let onRestore: () -> Void
    let onContextMenu: () -> Void

    var body: some View {
        Button(action: onRestore) {
            Image(systemName: "message.fill")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 52, height: 52)
                .background(Color.accentColor)
                .clipShape(Circle())
                .shadow(radius: 8, y: 2)
        }
        .buttonStyle(.plain)
        .simultaneousGesture(
            TapGesture()
                .modifiers(.control)
                .onEnded(onContextMenu)
        )
        .contextMenu {
            Menu("Debug") {
                Button("Test green bbox", action: onContextMenu)
            }
        }
    }
}
