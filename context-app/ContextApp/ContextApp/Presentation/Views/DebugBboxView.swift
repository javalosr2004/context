import SwiftUI

struct DebugBboxView: View {
    var body: some View {
        Rectangle()
            .stroke(Color.green, lineWidth: 4)
            .background(Color.clear)
            .frame(width: DebugBoundingBox.size.width, height: DebugBoundingBox.size.height)
    }
}

