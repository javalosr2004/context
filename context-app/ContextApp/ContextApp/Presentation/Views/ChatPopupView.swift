import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct InstructionInput {
    let text: String
    let referenceImageData: Data?
}

struct ChatPopupView: View {
    let messageStore: ChatMessageStore
    let onInputInstruction: (InstructionInput) async -> String
    let onMinify: () -> Void

    @State private var draft = ""
    @State private var instructionDraft = ""
    @State private var isInstructionInputVisible = false
    @State private var isSendingInstruction = false
    @State private var messages: [ChatMessage]
    @State private var referenceImageData: Data?
    @State private var referenceImageName: String?

    init(
        messageStore: ChatMessageStore,
        onInputInstruction: @escaping (InstructionInput) async -> String,
        onMinify: @escaping () -> Void
    ) {
        self.messageStore = messageStore
        self.onInputInstruction = onInputInstruction
        self.onMinify = onMinify
        self._messages = State(initialValue: messageStore.messages)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            messageList
            instructionInput
            composer
        }
        .frame(width: 360, height: isInstructionInputVisible ? 560 : 440)
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
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                TextField("Message", text: $draft)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(submitDraft)

                Button("Send", action: submitDraft)
                    .keyboardShortcut(.return, modifiers: [])
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            Button("Input instruction") {
                isInstructionInputVisible.toggle()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12)
        .background(Color.black.opacity(0.04))
    }

    private var instructionInput: some View {
        Group {
            if isInstructionInputVisible {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Instruction", text: $instructionDraft)
                        .textFieldStyle(.roundedBorder)
                        .disabled(isSendingInstruction)

                    HStack(spacing: 8) {
                        Button("Upload reference image", action: chooseReferenceImage)
                            .disabled(isSendingInstruction)

                        Text(referenceImageName ?? "No image selected")
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .foregroundStyle(.secondary)
                    }

                    HStack {
                        Button("Send instruction", action: submitInstruction)
                            .disabled(isSendingInstruction || instructionDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                        if isSendingInstruction {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                }
                .padding(12)
                .background(Color.black.opacity(0.025))
            }
        }
    }

    private func submitDraft() {
        guard messageStore.append(draft) != nil else { return }
        messages = messageStore.messages
        draft = ""
    }

    private func chooseReferenceImage() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowedContentTypes = [.image]

        guard panel.runModal() == .OK, let url = panel.url else { return }

        do {
            referenceImageData = try Data(contentsOf: url)
            referenceImageName = url.lastPathComponent
        } catch {
            appendMessage("Could not load reference image: \(error.localizedDescription)")
        }
    }

    private func submitInstruction() {
        let trimmedInstruction = instructionDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedInstruction.isEmpty else { return }

        isSendingInstruction = true
        appendMessage("Instruction: \(trimmedInstruction)")

        let input = InstructionInput(text: trimmedInstruction, referenceImageData: referenceImageData)
        Task {
            let result = await onInputInstruction(input)
            await MainActor.run {
                appendMessage(result)
                instructionDraft = ""
                referenceImageData = nil
                referenceImageName = nil
                isSendingInstruction = false
            }
        }
    }

    private func appendMessage(_ text: String) {
        guard messageStore.append(text) != nil else { return }
        messages = messageStore.messages
    }
}
