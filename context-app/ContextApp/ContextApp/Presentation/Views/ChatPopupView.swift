import SwiftUI

struct ChatPopupView: View {
    let messageStore: ChatMessageStore
    let onMinify: () -> Void

    @State private var draft = ""
    @State private var messages: [ChatMessage]

    init(messageStore: ChatMessageStore, onMinify: @escaping () -> Void) {
        self.messageStore = messageStore
        self.onMinify = onMinify
        self._messages = State(initialValue: messageStore.messages)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            messageList
            composer
        }
        .frame(width: 360, height: 440)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.primary.opacity(0.12), lineWidth: 1)
        )
    }

    private var header: some View {
        HStack {
            Text("Context")
                .font(.headline)
            Spacer()
            Button(action: onMinify) {
                Image(systemName: "minus")
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            .help("Minify")
        }
        .padding(.horizontal, 12)
        .frame(height: 44)
        .background(Color.black.opacity(0.06))
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if messages.isEmpty {
                        Text("Ready.")
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    ForEach(messages) { message in
                        Text(message.text)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background(Color.accentColor.opacity(0.14))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                            .id(message.id)
                    }
                }
                .padding(12)
            }
            .onChange(of: messages.count) { _ in
                guard let last = messages.last else { return }
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    private var composer: some View {
        HStack(spacing: 8) {
            TextField("Message", text: $draft)
                .textFieldStyle(.roundedBorder)
                .onSubmit(submitDraft)

            Button("Send", action: submitDraft)
                .keyboardShortcut(.return, modifiers: [])
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(12)
        .background(Color.black.opacity(0.04))
    }

    private func submitDraft() {
        guard messageStore.append(draft) != nil else { return }
        messages = messageStore.messages
        draft = ""
    }
}
