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

private struct StepJSONPreview: Identifiable {
    let id = UUID()
    let stepID: String
    let json: String
}

struct ChatPopupView: View {
    @ObservedObject var sessionController: TutorialSessionController
    let onTutorialStepSelected: (TutorialStep) async -> String
    let onInputInstruction: (InstructionInput) async -> String
    let onMinify: () -> Void

    @State private var activeStepID: String?
    @State private var expandedStepID: String?
    @State private var draft = ""
    @State private var isDraftPlanPreviewVisible = false
    @State private var stepJSONPreview: StepJSONPreview?
    @State private var instructionDraft = ""
    @State private var isInstructionInputVisible = false
    @State private var isSendingInstruction = false
    @State private var jpegQuality = 70
    @State private var loadingWordIndex = 0
    @State private var maxImageWidth = 1280
    @State private var referenceImageData: Data?
    @State private var referenceImageName: String?
    @State private var rejectionNote = ""
    @State private var selectedConfirmationStepID: String?
    @FocusState private var isMessageFieldFocused: Bool

    private static let loadingRowID = "tutorial-plan-loading-row"
    private static let loadingWords = ["preparing", "sending", "planning"]

    init(
        sessionController: TutorialSessionController,
        onTutorialStepSelected: @escaping (TutorialStep) async -> String,
        onInputInstruction: @escaping (InstructionInput) async -> String,
        onMinify: @escaping () -> Void
    ) {
        self.sessionController = sessionController
        self.onTutorialStepSelected = onTutorialStepSelected
        self.onInputInstruction = onInputInstruction
        self.onMinify = onMinify
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            messageList
            continuePromptControls
            confirmationControls
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
        .onReceive(Timer.publish(every: 0.8, on: .main, in: .common).autoconnect()) { _ in
            guard sessionController.status.isBusy else { return }
            loadingWordIndex = (loadingWordIndex + 1) % Self.loadingWords.count
        }
        .sheet(item: $stepJSONPreview) { preview in
            StepJSONPreviewSheet(preview: preview)
        }
        .sheet(isPresented: $isDraftPlanPreviewVisible) {
            if let plan = sessionController.draftPlan {
                DraftPlanPreviewSheet(plan: plan)
            }
        }
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

            if sessionController.draftPlan != nil {
                Button {
                    isDraftPlanPreviewVisible = true
                } label: {
                    Image(systemName: "book")
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 28, height: 28)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Show draft plan")
            }

            Button(action: startNewChat) {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("New chat")

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
                    if sessionController.messages.isEmpty && !sessionController.status.isBusy {
                        emptyState
                    }

                    ForEach(sessionController.messages) { message in
                        messageRow(message)
                    }

                    if sessionController.status.isBusy {
                        loadingRow
                            .id(Self.loadingRowID)
                    }
                }
                .padding(14)
            }
            .scrollContentBackground(.hidden)
            .onChange(of: sessionController.messages.count) { _ in
                scrollToBottom(proxy)
            }
            .onChange(of: sessionController.status.isBusy) { _ in
                scrollToBottom(proxy)
            }
        }
    }

    private var emptyState: some View {
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

    private var loadingRow: some View {
        HStack {
            HStack(spacing: 8) {
                ProgressView()
                    .controlSize(.small)

                Text(loadingText)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(OverlayTheme.assistantBubble)
            .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 1)
            )

            Spacer(minLength: 28)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var loadingText: String {
        switch sessionController.status {
        case .preparingScreen, .sending, .planning:
            return sessionController.status.label
        case .ready, .awaitingConfirmation, .completed, .failed:
            return Self.loadingWords[loadingWordIndex]
        }
    }

    private var composer: some View {
        VStack(spacing: 10) {
            HStack(spacing: 8) {
                TextField(composerPlaceholder, text: $draft)
                    .textFieldStyle(.plain)
                    .focused($isMessageFieldFocused)
                    .disabled(sessionController.status.isBusy)
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

    private var continuePromptControls: some View {
        Group {
            if let stepID = sessionController.pendingContinuePromptStepID {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Continue to next step?")
                        .font(.system(size: 13, weight: .medium))

                    Text("Clicked outside the highlight. Continue, or re-check the screen.")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    HStack(spacing: 8) {
                        Button {
                            submitContinuePrompt(stepID: stepID, confirmed: true)
                        } label: {
                            Label("Continue", systemImage: "arrow.right")
                                .font(.caption.weight(.medium))
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)

                        Button {
                            submitContinuePrompt(stepID: stepID, confirmed: false)
                        } label: {
                            Label("Re-check screen", systemImage: "arrow.clockwise")
                                .font(.caption.weight(.medium))
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)

                        Button {
                            sessionController.dismissContinuePrompt()
                        } label: {
                            Text("Dismiss")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .controlSize(.small)
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

    private var confirmationControls: some View {
        Group {
            if let selectedConfirmationStepID {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Does the highlight look right?")
                        .font(.system(size: 13, weight: .medium))

                    TextField("Optional note for Not right", text: $rejectionNote)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(OverlayTheme.strongerFill)
                        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.controlCornerRadius, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: OverlayTheme.controlCornerRadius, style: .continuous)
                                .stroke(OverlayTheme.hairline, lineWidth: 1)
                        )

                    HStack(spacing: 8) {
                        Button {
                            submitConfirmation(stepID: selectedConfirmationStepID, confirmed: true)
                        } label: {
                            Label("Looks right", systemImage: "checkmark")
                                .font(.caption.weight(.medium))
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)

                        Button {
                            submitConfirmation(stepID: selectedConfirmationStepID, confirmed: false)
                        } label: {
                            Label("Not right", systemImage: "xmark")
                                .font(.caption.weight(.medium))
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
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
        if isSendingInstruction {
            return "Reading screen"
        }

        return sessionController.status.label
    }

    private var composerPlaceholder: String {
        "Message"
    }

    private var canSubmitDraft: Bool {
        !sessionController.status.isBusy && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var canSubmitInstruction: Bool {
        !instructionDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    @ViewBuilder
    private func messageRow(_ message: ChatMessage) -> some View {
        switch message.content {
        case .text(let text):
            textMessageRow(text, role: message.role)
                .id(message.id)
        case .tutorialPlan(let plan):
            tutorialPlanRow(plan)
                .id(message.id)
        }
    }

    private func textMessageRow(_ text: String, role: ChatMessageRole) -> some View {
        HStack {
            if role == .user {
                Spacer(minLength: 28)
            }

            chatText(text, role: role)
                .font(.system(size: 13))
                .lineSpacing(2)
                .foregroundStyle(.primary)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .frame(maxWidth: role == .user ? 270 : .infinity, alignment: .leading)
                .background(role == .user ? OverlayTheme.userBubble : OverlayTheme.assistantBubble)
                .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                        .stroke(OverlayTheme.hairline, lineWidth: 1)
                )

            if role == .tutorial {
                Spacer(minLength: 28)
            }
        }
        .frame(maxWidth: .infinity, alignment: role == .user ? .trailing : .leading)
    }

    @ViewBuilder
    private func chatText(_ text: String, role: ChatMessageRole) -> some View {
        if role == .tutorial {
            MarkdownTextView(text: text)
        } else {
            Text(text)
        }
    }

    private func tutorialPlanRow(_ plan: TutorialPlan) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 10) {
                Text(plan.summary)
                    .font(.system(size: 13, weight: .medium))
                    .lineSpacing(2)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                VStack(spacing: 8) {
                    ForEach(plan.steps, id: \.stepId) { step in
                        tutorialStepButton(step)
                    }
                }
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

    private func tutorialStepButton(_ step: TutorialStep) -> some View {
        let isActive = activeStepID == step.stepId
        let isExpanded = expandedStepID == step.stepId
        let isHighlighted = isActive || isExpanded

        return VStack(alignment: .leading, spacing: 0) {
            Button {
                toggleStepExpansion(step)
            } label: {
                HStack(alignment: .center, spacing: 9) {
                    Image(systemName: iconName(for: step.action))
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Color.accentColor)
                        .frame(width: 20, height: 20)

                    Text(step.instruction)
                        .font(.system(size: 13))
                        .lineSpacing(2)
                        .foregroundStyle(.primary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .multilineTextAlignment(.leading)
                        .lineLimit(isExpanded ? nil : 2)

                    if isActive {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: "chevron.down")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.secondary)
                            .rotationEffect(.degrees(isExpanded ? 180 : 0))
                            .animation(.easeInOut(duration: 0.15), value: isExpanded)
                    }
                }
                .padding(.horizontal, 9)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .contextMenu {
                Button {
                    showStepJSONPreview(for: step)
                } label: {
                    Label("Show step JSON", systemImage: "curlybraces")
                }
            }
            .disabled(!canToggleStep(step))
            .help(isExpanded ? "Collapse" : "Show on screen")

            if isExpanded {
                stepDropdown(step)
            }
        }
        .background(OverlayTheme.strongerFill)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                .stroke(isHighlighted ? Color.accentColor.opacity(0.45) : OverlayTheme.hairline, lineWidth: 1)
        )
    }

    @ViewBuilder
    private func stepDropdown(_ step: TutorialStep) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Rectangle()
                .fill(OverlayTheme.separator)
                .frame(height: 1)

            if let target = stepTargetDescription(for: step), !target.isEmpty {
                Label(target, systemImage: "scope")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }

            if let typeText = stepCopyableText(for: step), !typeText.isEmpty {
                HStack(spacing: 8) {
                    Text(typeText)
                        .font(.system(size: 12, design: .monospaced))
                        .lineLimit(2)
                        .truncationMode(.tail)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(OverlayTheme.quietFill)
                        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))

                    Button {
                        copyTypeTextToPasteboard(typeText)
                    } label: {
                        Image(systemName: "doc.on.clipboard")
                            .font(.system(size: 12, weight: .medium))
                            .frame(width: 28, height: 28)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .help("Copy to clipboard")
                }
            }

            HStack(spacing: 8) {
                Button {
                    submitInlineConfirm(stepID: step.stepId, confirmed: true)
                } label: {
                    Label("Done", systemImage: "checkmark")
                        .font(.caption.weight(.medium))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(activeStepID == step.stepId)

                Button {
                    submitInlineConfirm(stepID: step.stepId, confirmed: false)
                } label: {
                    Label("Not right", systemImage: "xmark")
                        .font(.caption.weight(.medium))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(activeStepID == step.stepId)

                Spacer()
            }
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 8)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    private func canToggleStep(_ step: TutorialStep) -> Bool {
        if expandedStepID == step.stepId { return true }
        return !sessionController.status.isBusy && activeStepID == nil
    }

    private func stepCopyableText(for step: TutorialStep) -> String? {
        if case .type(let action) = step.action { return action.text }
        return nil
    }

    private func stepTargetDescription(for step: TutorialStep) -> String? {
        switch step.action {
        case .click(let a): return a.target.description
        case .doubleClick(let a): return a.target.description
        case .rightClick(let a): return a.target.description
        case .hover(let a): return a.target.description
        case .drag(let a): return a.target.description
        case .type(let a): return a.target?.description
        case .scroll(let a): return a.target?.description
        case .pressKey(let a): return "Key: \(a.key)"
        case .wait, .confirm: return nil
        }
    }

    private func toggleStepExpansion(_ step: TutorialStep) {
        if expandedStepID == step.stepId {
            expandedStepID = nil
            return
        }
        expandedStepID = step.stepId
        guard canSelectTutorialStep(step), activeStepID == nil else { return }
        selectTutorialStep(step)
    }

    private func submitInlineConfirm(stepID: String, confirmed: Bool) {
        selectedConfirmationStepID = nil
        expandedStepID = nil
        Task {
            await sessionController.confirmStep(stepID: stepID, confirmed: confirmed, note: nil)
        }
    }

    private func copyTypeTextToPasteboard(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private func canSelectTutorialStep(_ step: TutorialStep) -> Bool {
        !sessionController.status.isBusy
    }

    private func iconName(for action: TutorialAction) -> String {
        switch action {
        case .click, .doubleClick, .rightClick:
            return "cursorarrow.click"
        case .hover:
            return "cursorarrow"
        case .type:
            return "keyboard"
        case .pressKey:
            return "command"
        case .scroll(let action):
            switch action.direction {
            case .up:
                return "arrow.up"
            case .down:
                return "arrow.down"
            case .left:
                return "arrow.left"
            case .right:
                return "arrow.right"
            }
        case .drag:
            return "hand.point.up.left"
        case .wait:
            return "clock"
        case .confirm:
            return "checkmark.circle"
        }
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
        let trimmedDraft = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedDraft.isEmpty, !sessionController.status.isBusy else { return }

        draft = ""
        loadingWordIndex = 0

        Task {
            await sessionController.sendComposerText(trimmedDraft)
        }
    }

    private func startNewChat() {
        activeStepID = nil
        draft = ""
        instructionDraft = ""
        isSendingInstruction = false
        referenceImageData = nil
        referenceImageName = nil
        rejectionNote = ""
        selectedConfirmationStepID = nil
        stepJSONPreview = nil
        loadingWordIndex = 0
        sessionController.startNewChat()
    }

    private func selectTutorialStep(_ step: TutorialStep) {
        guard activeStepID == nil, canSelectTutorialStep(step) else { return }
        activeStepID = step.stepId
        selectedConfirmationStepID = nil

        Task {
            await sessionController.markStepStarted(stepID: step.stepId)
            let result = await onTutorialStepSelected(step)
            await MainActor.run {
                sessionController.appendTutorialText(result)
                activeStepID = nil
                selectedConfirmationStepID = step.stepId
            }
        }
    }

    private func submitContinuePrompt(stepID: String, confirmed: Bool) {
        Task {
            await sessionController.confirmStep(stepID: stepID, confirmed: confirmed, note: nil)
        }
    }

    private func submitConfirmation(stepID: String, confirmed: Bool) {
        let note = rejectionNote.trimmingCharacters(in: .whitespacesAndNewlines)
        selectedConfirmationStepID = nil
        rejectionNote = ""

        Task {
            await sessionController.confirmStep(
                stepID: stepID,
                confirmed: confirmed,
                note: note.isEmpty ? nil : note
            )
        }
    }

    private func showStepJSONPreview(for step: TutorialStep) {
        stepJSONPreview = StepJSONPreview(
            stepID: step.stepId,
            json: TutorialStepJSONFormatter.displayString(for: step)
        )
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
            sessionController.appendTutorialText("Could not load reference image: \(error.localizedDescription)")
        }
    }

    private func submitInstruction() {
        let trimmedInstruction = instructionDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedInstruction.isEmpty else { return }

        isSendingInstruction = true
        sessionController.appendUserText(trimmedInstruction)

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
                sessionController.appendTutorialText(result)
                instructionDraft = ""
                referenceImageData = nil
                referenceImageName = nil
                isSendingInstruction = false
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if sessionController.status.isBusy {
            proxy.scrollTo(Self.loadingRowID, anchor: .bottom)
            return
        }

        guard let last = sessionController.messages.last else { return }
        proxy.scrollTo(last.id, anchor: .bottom)
    }
}

private struct StepJSONPreviewSheet: View {
    let preview: StepJSONPreview
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Step JSON")
                        .font(.system(size: 14, weight: .semibold))

                    Text(preview.stepID)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()
            }

            ScrollView {
                Text(preview.json)
                    .font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
            .frame(width: 420, height: 260)
            .background(OverlayTheme.strongerFill)
            .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 1)
            )

            HStack {
                Spacer()

                Button {
                    copyJSONToPasteboard()
                } label: {
                    Label("Copy", systemImage: "doc.on.doc")
                }

                Button("Done") {
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 452)
    }

    private func copyJSONToPasteboard() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(preview.json, forType: .string)
    }
}

private struct DraftPlanPreviewSheet: View {
    let plan: DraftPlan
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Draft plan")
                    .font(.system(size: 14, weight: .semibold))

                Text(plan.goal)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(plan.steps.enumerated()), id: \.offset) { index, step in
                        HStack(alignment: .top, spacing: 8) {
                            Text("\(index + 1).")
                                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .frame(width: 24, alignment: .trailing)

                            VStack(alignment: .leading, spacing: 2) {
                                Text(step.instruction)
                                    .font(.system(size: 13))
                                    .foregroundStyle(.primary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .multilineTextAlignment(.leading)

                                Text(step.kind)
                                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                                    .foregroundStyle(.secondary)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(OverlayTheme.quietFill)
                                    .clipShape(Capsule())
                            }
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(OverlayTheme.strongerFill)
                        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
                    }
                }
                .padding(2)
            }
            .frame(width: 420, height: 320)

            HStack {
                Spacer()

                Button("Dismiss") {
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 452)
    }
}
