import AppKit
import SwiftUI

private struct ChatHistoryBlurBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.blendingMode = .behindWindow
        view.material = .hudWindow
        view.state = .active
        view.isEmphasized = true
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {}
}

struct ChatHistoryView: View {
    @ObservedObject var sessionController: TutorialSessionController
    let onClose: () -> Void

    private static let bottomAnchorID = "chat-history-bottom-anchor"

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().background(OverlayTheme.separator)
            messageList
        }
        .background(background.ignoresSafeArea())
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous)
                .stroke(Color.white.opacity(0.24), lineWidth: 0.5)
        )
        .shadow(color: .black.opacity(0.20), radius: 28, y: 10)
    }

    private var background: some View {
        ZStack {
            ChatHistoryBlurBackground()

            LinearGradient(
                colors: [
                    Color(red: 0.34, green: 0.27, blue: 0.40).opacity(0.16),
                    Color(red: 0.58, green: 0.40, blue: 0.49).opacity(0.14),
                    Color(red: 0.86, green: 0.63, blue: 0.50).opacity(0.10)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
        .allowsHitTesting(false)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Color.clear.frame(width: 70, height: 28).accessibilityHidden(true)

            Text("Chat history")
                .font(.system(size: 12, weight: .semibold))
                .tracking(0.5)
                .textCase(.uppercase)
                .foregroundStyle(OverlayTheme.tertiaryText)

            Spacer()

            Text("\(sessionController.messages.count) message\(sessionController.messages.count == 1 ? "" : "s")")
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(OverlayTheme.quaternaryText)
        }
        .padding(.horizontal, 12)
        .frame(height: 36)
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if sessionController.messages.isEmpty {
                        emptyState
                    } else {
                        ForEach(sessionController.messages) { message in
                            row(for: message)
                                .id(message.id)
                        }
                    }
                    Color.clear.frame(height: 1).id(Self.bottomAnchorID)
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollContentBackground(.hidden)
            .onAppear { scrollToBottom(proxy) }
            .onChange(of: sessionController.messages.count) { _ in
                scrollToBottom(proxy)
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        DispatchQueue.main.async {
            withAnimation(.easeOut(duration: 0.18)) {
                proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("No messages yet")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(OverlayTheme.primaryText)
            Text("Ask Context something from the main popup to start a conversation.")
                .font(.system(size: 12))
                .foregroundStyle(OverlayTheme.tertiaryText)
        }
        .padding(.top, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func row(for message: ChatMessage) -> some View {
        switch message.content {
        case .text(let text):
            textRow(text, role: message.role)
        case .tutorialPlan(let plan):
            planRow(plan)
        }
    }

    private func textRow(_ text: String, role: ChatMessageRole) -> some View {
        HStack {
            if role == .user { Spacer(minLength: 28) }

            Group {
                if role == .tutorial {
                    MarkdownTextView(text: text)
                } else {
                    Text(text)
                }
            }
            .font(.system(size: 13))
            .lineSpacing(2)
            .foregroundStyle(OverlayTheme.primaryText)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .frame(maxWidth: role == .user ? 320 : .infinity, alignment: .leading)
            .background(role == .user ? OverlayTheme.userBubble : OverlayTheme.assistantBubble)
            .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 1)
            )

            if role == .tutorial { Spacer(minLength: 28) }
        }
        .frame(maxWidth: .infinity, alignment: role == .user ? .trailing : .leading)
    }

    private func planRow(_ plan: TutorialPlan) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Image(systemName: "book")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(OverlayTheme.tertiaryText)
                    Text("Tutorial plan")
                        .font(.system(size: 10.5, weight: .medium))
                        .tracking(0.5)
                        .textCase(.uppercase)
                        .foregroundStyle(OverlayTheme.tertiaryText)
                    Spacer(minLength: 0)
                    Text("\(plan.steps.count) step\(plan.steps.count == 1 ? "" : "s")")
                        .font(.system(size: 10.5, weight: .medium, design: .monospaced))
                        .foregroundStyle(OverlayTheme.quaternaryText)
                }

                Text(plan.summary.isEmpty ? "Plan generated." : plan.summary)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(OverlayTheme.primaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(OverlayTheme.assistantBubble)
            .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 1)
            )

            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
