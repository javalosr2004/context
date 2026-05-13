import SwiftUI

struct DebugBboxView: View {
    let size: CGSize

    init(size: CGSize = DebugBoundingBox.size) {
        self.size = size
    }

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(OverlayTheme.highlightGlow, lineWidth: 10)
                .blur(radius: 6)

            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(OverlayTheme.highlightStroke, lineWidth: 2)

            cornerHandles
        }
        .padding(6)
        .allowsHitTesting(false)
        .frame(width: size.width, height: size.height)
    }

    private var cornerHandles: some View {
        let handleLength: CGFloat = 22
        let handleWidth: CGFloat = 3

        return ZStack {
            handle
                .frame(width: handleLength, height: handleWidth)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            handle
                .frame(width: handleWidth, height: handleLength)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            handle
                .frame(width: handleLength, height: handleWidth)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            handle
                .frame(width: handleWidth, height: handleLength)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)

            handle
                .frame(width: handleLength, height: handleWidth)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            handle
                .frame(width: handleWidth, height: handleLength)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)

            handle
                .frame(width: handleLength, height: handleWidth)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
            handle
                .frame(width: handleWidth, height: handleLength)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
        }
        .padding(2)
    }

    private var handle: some View {
        Capsule()
            .fill(OverlayTheme.highlightStroke)
            .shadow(color: OverlayTheme.highlightGlow, radius: 5)
    }
}
