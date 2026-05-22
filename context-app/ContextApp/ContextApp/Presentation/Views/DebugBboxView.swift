import SwiftUI

struct DebugBboxView: View {
    let size: CGSize

    @State private var pulse: Bool = false

    private let ringDiameter: CGFloat = 40
    private let ringLineWidth: CGFloat = 3
    private let dotDiameter: CGFloat = 10

    init(size: CGSize = DebugBoundingBox.size) {
        self.size = size
    }

    var body: some View {
        ZStack {
            Circle()
                .stroke(OverlayTheme.highlightGlow, lineWidth: ringLineWidth + 6)
                .blur(radius: 6)
                .frame(width: ringDiameter, height: ringDiameter)
                .scaleEffect(pulse ? 1.25 : 0.95)
                .opacity(pulse ? 0.0 : 0.85)

            Circle()
                .stroke(OverlayTheme.highlightStroke, lineWidth: ringLineWidth)
                .frame(width: ringDiameter, height: ringDiameter)
                .scaleEffect(pulse ? 1.12 : 1.0)
                .opacity(pulse ? 0.6 : 1.0)

            Circle()
                .fill(OverlayTheme.highlightStroke)
                .frame(width: dotDiameter, height: dotDiameter)
        }
        .allowsHitTesting(false)
        .frame(width: size.width, height: size.height)
        .onAppear {
            withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) {
                pulse = true
            }
        }
    }
}
