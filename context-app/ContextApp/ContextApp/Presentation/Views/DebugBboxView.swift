import SwiftUI

struct DebugBboxView: View {
    let size: CGSize

    init(size: CGSize = DebugBoundingBox.size) {
        self.size = size
    }

    var body: some View {
        Rectangle()
            .stroke(Color.green, lineWidth: 4)
            .background(Color.clear)
            .frame(width: size.width, height: size.height)
    }
}
