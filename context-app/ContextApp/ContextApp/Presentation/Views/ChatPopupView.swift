import AppKit
import Dispatch
import SwiftUI
import UniformTypeIdentifiers

struct InstructionInput {
    let text: String
    let referenceImageData: Data?
    let imageEncodingConfig: ScreenFrameEncodingConfig
    let submittedAtUptimeNanoseconds: UInt64
}

struct ChatPopupView: View {
    let messageStore: ChatMessageStore
    let onInputInstruction: (InstructionInput) async -> String
    let onMinify: () -> Void

    @State private var draft = ""
    @State private var instructionDraft = ""
    @State private var isInstructionInputVisible = false
    @State private var isSendingInstruction = false
    @State private var jpegQuality = 70
    @State private var maxImageWidth = 1280
    @State private var messages: [ChatMessage]
    @State private var referenceImageData: Data?
    @State private var referenceImageName: String?
    @FocusState private var isMessageFieldFocused: Bool

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
        .frame(width: 360, height: isInstructionInputVisible ? 620 : 440)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.18), radius: 24, y: 12)
    }

    private var header: some View {
        HStack(spacing: 10) {
            contextIcon(size: 24)

            VStack(alignment: .leading, spacing: 1) {
                Text("Context")
                    .font(.system(size: 13, weight: .semibold))

                Text(statusText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button(action: onMinify) {
                Image(systemName: "minus")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("Minify")
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(OverlayTheme.quietFill)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(OverlayTheme.separator)
                .frame(height: 1)
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if messages.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Ready when you are.")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(.primary)

                            Text("Send a note or provide a screen instruction.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.top, 4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    ForEach(messages) { message in
                        messageRow(message)
                    }
                }
                .padding(14)
            }
            .scrollContentBackground(.hidden)
            .onChange(of: messages.count) { _ in
                guard let last = messages.last else { return }
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    private var composer: some View {
        VStack(spacing: 10) {
            HStack(spacing: 8) {
                TextField("Message", text: $draft)
                    .textFieldStyle(.plain)
                    .focused($isMessageFieldFocused)
                    .onSubmit(submitDraft)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background(OverlayTheme.strongerFill)
                    .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.controlCornerRadius, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: OverlayTheme.controlCornerRadius, style: .continuous)
                            .stroke(isMessageFieldFocused ? Color.accentColor.opacity(0.45) : OverlayTheme.hairline, lineWidth: 1)
                    )

                Button(action: submitDraft) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 13, weight: .bold))
                        .frame(width: 30, height: 30)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .background(canSubmitDraft ? Color.accentColor.opacity(0.92) : OverlayTheme.strongerFill)
                .foregroundStyle(canSubmitDraft ? Color.white : Color.secondary)
                .clipShape(Circle())
                .help("Send")
                .keyboardShortcut(.return, modifiers: [])
                .disabled(!canSubmitDraft)
            }

            Button {
                isInstructionInputVisible.toggle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: isInstructionInputVisible ? "chevron.down" : "chevron.right")
                        .font(.system(size: 10, weight: .semibold))

                    Text("Screen instruction")
                        .font(.caption)

                    Spacer()
                }
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
        .padding(14)
        .background(.regularMaterial)
        .overlay(alignment: .top) {
            Rectangle()
                .fill(OverlayTheme.separator)
                .frame(height: 1)
        }
    }

    private var instructionInput: some View {
        Group {
            if isInstructionInputVisible {
                VStack(alignment: .leading, spacing: 10) {
                    TextField("Instruction", text: $instructionDraft)
                        .textFieldStyle(.plain)
                        .disabled(isSendingInstruction)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(OverlayTheme.strongerFill)
                        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.controlCornerRadius, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: OverlayTheme.controlCornerRadius, style: .continuous)
                                .stroke(OverlayTheme.hairline, lineWidth: 1)
                        )

                    HStack(spacing: 8) {
                        Button(action: chooseReferenceImage) {
                            Label("Reference", systemImage: "photo")
                                .font(.caption)
                        }
                        .buttonStyle(.borderless)
                        .disabled(isSendingInstruction)

                        Text(referenceImageName ?? "No image selected")
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .foregroundStyle(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 7) {
                        Stepper("JPEG quality: \(jpegQuality)", value: $jpegQuality, in: 10...100, step: 5)
                            .disabled(isSendingInstruction)

                        Stepper("Max width: \(maxImageWidth) px", value: $maxImageWidth, in: 320...4096, step: 160)
                            .disabled(isSendingInstruction)
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    HStack(spacing: 8) {
                        Button(action: submitInstruction) {
                            Label("Send instruction", systemImage: "scope")
                                .font(.caption.weight(.medium))
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(isSendingInstruction || !canSubmitInstruction)

                        if isSendingInstruction {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(OverlayTheme.quietFill)
                .overlay(alignment: .bottom) {
                    Rectangle()
                        .fill(OverlayTheme.separator)
                        .frame(height: 1)
                }
            }
        }
    }

    private var statusText: String {
        isSendingInstruction ? "Reading screen" : "Ready"
    }

    private var canSubmitDraft: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var canSubmitInstruction: Bool {
        !instructionDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func messageRow(_ message: ChatMessage) -> some View {
        let style = messageStyle(for: message.text)

        return HStack {
            if style.isUserAuthored {
                Spacer(minLength: 28)
            }

            Text(style.displayText)
                .font(.system(size: 13))
                .lineSpacing(2)
                .foregroundStyle(.primary)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(style.fill)
                .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                        .stroke(OverlayTheme.hairline, lineWidth: 1)
                )
                .id(message.id)

            if !style.isUserAuthored {
                Spacer(minLength: 28)
            }
        }
        .frame(maxWidth: .infinity, alignment: style.isUserAuthored ? .trailing : .leading)
    }

    private func messageStyle(for text: String) -> MessageStyle {
        let instructionPrefix = "Instruction: "
        if text.hasPrefix(instructionPrefix) {
            return MessageStyle(
                displayText: String(text.dropFirst(instructionPrefix.count)),
                fill: OverlayTheme.userBubble,
                isUserAuthored: true
            )
        }

        return MessageStyle(
            displayText: text,
            fill: OverlayTheme.assistantBubble,
            isUserAuthored: false
        )
    }

    private func contextIcon(size: CGFloat) -> some View {
        Group {
            if let image = NSImage(named: "ContextIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: "sparkle.magnifyingglass")
                    .font(.system(size: size * 0.62, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.24, style: .continuous))
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

        let input = InstructionInput(
            text: trimmedInstruction,
            referenceImageData: referenceImageData,
            imageEncodingConfig: ScreenFrameEncodingConfig(
                jpegCompressionQuality: CGFloat(jpegQuality) / 100,
                maxPixelWidth: maxImageWidth
            ),
            submittedAtUptimeNanoseconds: DispatchTime.now().uptimeNanoseconds
        )
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

private struct MessageStyle {
    let displayText: String
    let fill: Color
    let isUserAuthored: Bool
}
