import SwiftUI

struct FocusMaskView: View {
    var body: some View {
        Rectangle()
            .fill(OverlayTheme.focusDim)
            .ignoresSafeArea()
    }
}
