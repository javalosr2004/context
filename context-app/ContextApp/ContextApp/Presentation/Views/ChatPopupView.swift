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

private enum PeekStepKind {
    case done
    case now
    case next
}

private enum ActionChipKind {
    case done
    case current
    case upcoming
}

private struct TutorialPeekSteps {
    let done: TutorialStepDisplayItem?
    let now: TutorialStepDisplayItem?
    let next: TutorialStepDisplayItem?
}

private struct StatusChip: Identifiable, Equatable {
    let id: String
    let icon: String?
    let text: String
    let showsDot: Bool
}

private struct ChipEnterModifier: ViewModifier, Animatable {
    var progress: Double
    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }
    func body(content: Content) -> some View {
        // progress: 0 = hidden (small, offset, transparent), 1 = resting.
        let clamped = min(max(progress, 0), 1)
        let scale = 0.62 + 0.38 * clamped
        let xOffset = (1 - clamped) * -6 // slide in from leading edge
        let opacity = clamped
        return content
            .scaleEffect(scale, anchor: .leading)
            .offset(x: xOffset)
            .opacity(opacity)
    }
}

private struct ChipExitModifier: ViewModifier, Animatable {
    var progress: Double
    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }
    func body(content: Content) -> some View {
        // progress: 1 = resting, 0 = exited (collapses in place, no slide).
        let clamped = min(max(progress, 0), 1)
        let scale = 0.84 + 0.16 * clamped
        let opacity = clamped
        return content
            .scaleEffect(scale, anchor: .center)
            .opacity(opacity)
    }
}

private struct StepChipFlash: Equatable {
    let id: UUID
    let text: String
    let icon: String
}

private struct SkeletonShimmer: View {
    @State private var phase: CGFloat = -1

    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            Rectangle()
                .fill(Color.white.opacity(0.10))
                .overlay(
                    LinearGradient(
                        colors: [
                            Color.white.opacity(0.00),
                            Color.white.opacity(0.22),
                            Color.white.opacity(0.00)
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                    .frame(width: width * 0.6)
                    .offset(x: phase * width)
                )
                .clipped()
                .onAppear {
                    withAnimation(.linear(duration: 1.2).repeatForever(autoreverses: false)) {
                        phase = 1.4
                    }
                }
        }
    }
}

private struct PopupBlurBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.blendingMode = .behindWindow
        view.material = .hudWindow
        view.state = .active
        view.isEmphasized = true
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {
        view.blendingMode = .behindWindow
        view.material = .hudWindow
        view.state = .active
        view.isEmphasized = true
    }
}

struct ChatPopupView: View {
    private static let maximumChatResponseHeight: CGFloat = 500

    @ObservedObject var sessionController: TutorialSessionController
    @ObservedObject var recordingController: RecordingController
    let onTutorialStepSelected: (TutorialStep) async -> String
    let onInputInstruction: (InstructionInput) async -> String
    let onMinify: () -> Void
    let onShowRecordings: () -> Void
    let onToggleChatHistory: () -> Void

    @State private var activeStepID: String?
    @State private var expandedStepID: String?
    @State private var draft = ""
    @State private var isDraftPlanPreviewVisible = false
    @State private var stepJSONPreview: StepJSONPreview?
    @State private var instructionDraft = ""
    @State private var isInstructionInputVisible = false
    @AppStorage("eval_mode_enabled") private var evalModeEnabled: Bool = false
    @State private var isSendingInstruction = false
    @State private var jpegQuality = 70
    @State private var loadingWordIndex = 0
    @State private var maxImageWidth = 1280
    @State private var referenceImageData: Data?
    @State private var referenceImageName: String?
    @State private var nowPulse: Bool = false
    @State private var stepChipFlash: StepChipFlash?
    @State private var lastSeenTotalSteps: Int?
    @FocusState private var isMessageFieldFocused: Bool

    private static let launcherSuggestions: [String] = [
        "Explain what's on my screen",
        "Walk me through setting up Git",
        "Help me deploy this to Vercel"
    ]

    private static let launcherSuggestionIcons: [String] = [
        "camera.viewfinder",
        "book",
        "gearshape"
    ]

    private static let loadingRowID = "tutorial-plan-loading-row"
    private static let loadingWords = ["preparing", "sending", "planning"]

    init(
        sessionController: TutorialSessionController,
        recordingController: RecordingController,
        onTutorialStepSelected: @escaping (TutorialStep) async -> String,
        onInputInstruction: @escaping (InstructionInput) async -> String,
        onMinify: @escaping () -> Void,
        onShowRecordings: @escaping () -> Void,
        onToggleChatHistory: @escaping () -> Void
    ) {
        self.sessionController = sessionController
        self.recordingController = recordingController
        self.onTutorialStepSelected = onTutorialStepSelected
        self.onInputInstruction = onInputInstruction
        self.onMinify = onMinify
        self.onShowRecordings = onShowRecordings
        self.onToggleChatHistory = onToggleChatHistory
    }

    var body: some View {
        VStack(spacing: 0) {
            handoffChrome

            if isTutorialFinished {
                finishedTutorialView
            } else if latestPlan == nil {
                statusChipRow

                if sessionController.status.isBusy {
                    tutorialMeta
                }

                if let prompt = sessionController.pendingCompletionPrompt {
                    completionPromptCard(prompt)
                }

                if !sessionController.status.isBusy
                    && sessionController.pendingCompletionPrompt == nil {
                    launcherView
                }
            } else {
                statusChipRow

                tutorialMeta

                if let prompt = sessionController.pendingCompletionPrompt {
                    completionPromptCard(prompt)
                }

                peekStack
                    .opacity(sessionController.pendingCompletionPrompt != nil ? 0.35 : 1)
                    .allowsHitTesting(sessionController.pendingCompletionPrompt == nil)
            }

            if let hint = sessionController.awaitingHintResponse {
                verificationHintCard(hint)
            }

            if let batch = sessionController.pendingQuestionBatch {
                questionCard(batch)
            }

            askBar
        }
        .frame(width: 340)
        .background(overlayBackground.ignoresSafeArea())
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.panelCornerRadius, style: .continuous)
                .stroke(Color.white.opacity(0.24), lineWidth: 0.5)
        )
        .shadow(color: .black.opacity(0.16), radius: 2, y: 1)
        .shadow(color: .black.opacity(0.20), radius: 34, y: 12)
        .shadow(color: .black.opacity(0.14), radius: 70, y: 24)
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

    private var overlayBackground: some View {
        ZStack {
            PopupBlurBackground()

            LinearGradient(
                colors: [
                    Color(red: 0.86, green: 0.63, blue: 0.50).opacity(0.12),
                    Color(red: 0.58, green: 0.40, blue: 0.49).opacity(0.15),
                    Color(red: 0.34, green: 0.27, blue: 0.40).opacity(0.18)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            RadialGradient(
                colors: [
                    Color.white.opacity(0.12),
                    Color.white.opacity(0.00)
                ],
                center: .topLeading,
                startRadius: 0,
                endRadius: 260
            )

            RadialGradient(
                colors: [
                    Color(red: 0.96, green: 0.72, blue: 0.60).opacity(0.12),
                    Color.clear
                ],
                center: .topTrailing,
                startRadius: 10,
                endRadius: 220
            )
        }
        .saturation(1.18)
        .allowsHitTesting(false)
    }

    private var handoffChrome: some View {
        HStack(spacing: 6) {
            nativeWindowControlSpacer

            Spacer()

            Button(action: { recordingController.toggleRecording() }) {
                Image(systemName: recordingController.isRecording ? "stop.circle.fill" : "record.circle")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(recordingController.isRecording ? Color.red : OverlayTheme.secondaryText)
                    .frame(width: 24, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .background(OverlayTheme.quietFill)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .help(recordingController.isRecording ? "Stop recording" : "Record a workflow")

            Button(action: onShowRecordings) {
                Image(systemName: "list.bullet.rectangle")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(OverlayTheme.secondaryText)
                    .frame(width: 24, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .background(OverlayTheme.quietFill)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .help("Show recordings")

            Button(action: onToggleChatHistory) {
                Image(systemName: "bubble.left.and.bubble.right")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(OverlayTheme.secondaryText)
                    .frame(width: 24, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .background(OverlayTheme.quietFill)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .help("Toggle chat history")

            Button(action: startNewChat) {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(OverlayTheme.secondaryText)
                    .frame(width: 24, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .background(OverlayTheme.quietFill)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .help("New chat")
        }
        .padding(.horizontal, 12)
        .frame(height: 36)
    }

    private var nativeWindowControlSpacer: some View {
        Color.clear
            .frame(width: 70, height: 36)
            .accessibilityHidden(true)
    }

    private var tutorialMeta: some View {
        VStack(spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                if latestPlan == nil {
                    SkeletonShimmer()
                        .frame(width: 140, height: 11)
                        .clipShape(Capsule())
                } else {
                    Text(tutorialName)
                        .font(.system(size: 11, weight: .medium))
                        .tracking(0.44)
                        .textCase(.uppercase)
                        .foregroundStyle(OverlayTheme.tertiaryText)
                        .lineLimit(1)
                }

                Spacer()

                if !metaRightText.isEmpty {
                    stepProgressPill(text: metaRightText)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 2)
            .padding(.bottom, 10)

            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.white.opacity(0.16))

                    Capsule()
                        .fill(Color.white.opacity(0.76))
                        .frame(width: max(0, geometry.size.width * tutorialProgress))
                }
            }
            .frame(height: 2)
            .padding(.horizontal, 14)
        }
    }

    private var launcherView: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text("What should we figure out?")
                    .font(.system(size: 20, weight: .semibold))
                    .tracking(-0.3)
                    .foregroundStyle(OverlayTheme.primaryText)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                Text("Ask anything about what's on your screen, or pick a tutorial below.")
                    .font(.system(size: 12.5))
                    .foregroundStyle(OverlayTheme.tertiaryText)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 18)
            .padding(.top, 16)
            .padding(.bottom, 8)

            VStack(alignment: .leading, spacing: 0) {
                Text("Try asking")
                    .font(.system(size: 10.5, weight: .medium))
                    .tracking(0.63)
                    .textCase(.uppercase)
                    .foregroundStyle(OverlayTheme.tertiaryText)
                    .padding(.horizontal, 6)
                    .padding(.top, 6)
                    .padding(.bottom, 8)

                VStack(spacing: 2) {
                    ForEach(Array(Self.launcherSuggestions.enumerated()), id: \.offset) { idx, prompt in
                        launcherSuggestionRow(prompt: prompt, icon: Self.launcherSuggestionIcons[idx])
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 10)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func launcherSuggestionRow(prompt: String, icon: String) -> some View {
        Button {
            submitSuggestion(prompt)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(OverlayTheme.tertiaryText)
                    .frame(width: 22, height: 22)
                    .background(OverlayTheme.quietFill)
                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))

                Text(prompt)
                    .font(.system(size: 13))
                    .foregroundStyle(OverlayTheme.primaryText)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Image(systemName: "chevron.right")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(OverlayTheme.quaternaryText)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(OverlayTheme.quietFill.opacity(0))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .disabled(sessionController.status.isBusy)
    }

    private func submitSuggestion(_ prompt: String) {
        guard !sessionController.status.isBusy else { return }
        draft = prompt
        submitDraft()
    }

    private var peekStack: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let doneStep = peekSteps.done {
                peekStepRow(kind: .done, title: doneStep.title, step: doneStep.step)
            }

            if let nowStep = peekSteps.now {
                peekStepRow(kind: .now, title: nowStep.title, step: nowStep.step)
            } else {
                emptyPeekRow
            }

            if let nextStep = peekSteps.next {
                peekStepRow(kind: .next, title: nextStep.title, step: nextStep.step)
            }
        }
        .padding(.top, 12)
        .padding(.horizontal, 10)
        .padding(.bottom, 8)
        .animation(.easeInOut(duration: 0.18), value: sessionController.currentStepID)
    }


    private func peekStepRow(kind: PeekStepKind, title: String, step: TutorialStep) -> some View {
        Button {
            handlePeekStepTap(kind: kind, step: step)
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 12) {
                    stepMarker(kind: kind)
                        .padding(.top, kind == .now ? 4 : 0)

                    VStack(alignment: .leading, spacing: kind == .now ? 4 : 0) {
                        if kind == .now {
                            Text("Now")
                                .font(.system(size: 10.5, weight: .medium))
                                .tracking(0.63)
                                .textCase(.uppercase)
                                .foregroundStyle(OverlayTheme.tertiaryText)
                        }

                        Text(title)
                            .font(.system(size: kind == .now ? 17 : 13, weight: kind == .now ? .semibold : .regular))
                            .tracking(kind == .now ? -0.17 : 0)
                            .strikethrough(kind == .done, color: Color.white.opacity(0.34))
                            .foregroundStyle(stepTextColor(kind))
                            .lineLimit(3)
                            .multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if kind == .now && activeStepID == step.stepId {
                        ProgressView()
                            .controlSize(.small)
                            .scaleEffect(0.72)
                    }
                }

                if kind == .now && step.actions.count > 1 {
                    actionChipStrip(for: step)
                        .padding(.leading, 30)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(kind == .now ? Color.white.opacity(0.12) : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(kind == .now ? OverlayTheme.hairline : Color.clear, lineWidth: 0.5)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .allowsHitTesting(kind != .done && canToggleStep(step))
        .contextMenu {
            Button {
                showStepJSONPreview(for: step)
            } label: {
                Label("Show step JSON", systemImage: "curlybraces")
            }
        }
        .help(kind == .now ? "Show on screen" : "")
    }

    private var emptyPeekRow: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Ready when you are")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(OverlayTheme.primaryText)

            Text("Ask Context to plan a tutorial from your screen.")
                .font(.system(size: 13))
                .foregroundStyle(OverlayTheme.quaternaryText)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func actionChipStrip(for step: TutorialStep) -> some View {
        let activeIndex = sessionController.awaitingActionIndex
            ?? sessionController.currentActionIndex
            ?? 0
        return VStack(spacing: 4) {
            ForEach(Array(step.actions.enumerated()), id: \.offset) { idx, action in
                actionCard(action: action, kind: chipKind(index: idx, active: activeIndex))
            }
        }
    }

    private func chipKind(index: Int, active: Int) -> ActionChipKind {
        if index < active { return .done }
        if index == active { return .current }
        return .upcoming
    }

    private func actionCard(action: TutorialAction, kind: ActionChipKind) -> some View {
        let titleWeight: Font.Weight = kind == .current ? .semibold : .regular
        let foreground: Color
        let background: Color
        let borderColor: Color
        let borderStyle: StrokeStyle

        switch kind {
        case .done:
            foreground = OverlayTheme.doneText
            background = Color.white.opacity(0.04)
            borderColor = OverlayTheme.hairline
            borderStyle = StrokeStyle(lineWidth: 0.5)
        case .current:
            foreground = OverlayTheme.invertedForeground
            background = Color.white.opacity(0.92)
            borderColor = Color.clear
            borderStyle = StrokeStyle(lineWidth: 0)
        case .upcoming:
            foreground = OverlayTheme.quaternaryText
            background = Color.white.opacity(0.05)
            borderColor = Color.white.opacity(0.22)
            borderStyle = StrokeStyle(lineWidth: 1, dash: [3, 2])
        }

        return HStack(alignment: .center, spacing: 9) {
            Image(systemName: iconName(for: action))
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(foreground.opacity(kind == .current ? 0.85 : 1))
                .frame(width: 18, height: 18)

            Text(actionChipLabel(for: action))
                .font(.system(size: 12, weight: titleWeight))
                .strikethrough(kind == .done, color: foreground.opacity(0.5))
                .foregroundStyle(foreground)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let copyText = typeActionText(for: action) {
                Button {
                    copyTypeTextToPasteboard(copyText)
                } label: {
                    Image(systemName: "doc.on.clipboard")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(foreground.opacity(0.75))
                        .frame(width: 20, height: 20)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Copy \"\(copyText)\"")
                .accessibilityLabel("Copy text to clipboard")
            }

            if kind == .done {
                Image(systemName: "checkmark")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(foreground.opacity(0.7))
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(borderColor, style: borderStyle)
        )
    }

    private func typeActionText(for action: TutorialAction) -> String? {
        if case .type(let a) = action, !a.text.isEmpty { return a.text }
        return nil
    }

    private func actionChipLabel(for action: TutorialAction) -> String {
        switch action {
        case .click(let a): return "Click \(shortTargetLabel(a.target))"
        case .doubleClick(let a): return "Double-click \(shortTargetLabel(a.target))"
        case .rightClick(let a): return "Right-click \(shortTargetLabel(a.target))"
        case .hover(let a): return "Hover \(shortTargetLabel(a.target))"
        case .drag(let a): return "Drag \(shortTargetLabel(a.target))"
        case .type(let a):
            let trimmed = a.text.replacingOccurrences(of: "\n", with: " ")
            return "Type \"\(truncate(trimmed, max: 36))\""
        case .pressKey(let a): return "Press \(a.key)"
        case .scroll(let a): return "Scroll \(a.direction.rawValue)"
        case .wait(let a): return "Wait \(a.durationMs)ms"
        case .confirm: return "Confirm"
        case .userChoice(let a): return truncate(a.prompt, max: 48)
        }
    }

    private func shortTargetLabel(_ target: ActionTarget) -> String {
        let raw = target.label
            ?? target.description
            ?? target.role
            ?? target.kind.rawValue
        return truncate(raw, max: 32)
    }

    private func truncate(_ text: String, max: Int) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count <= max { return trimmed }
        return String(trimmed.prefix(max - 1)) + "…"
    }

    @ViewBuilder
    private func stepMarker(kind: PeekStepKind) -> some View {
        switch kind {
        case .done:
            Image(systemName: "checkmark")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(OverlayTheme.quaternaryText)
                .frame(width: 18, height: 18)
        case .now:
            ZStack {
                Circle()
                    .fill(Color(red: 0.176, green: 0.788, blue: 0.251).opacity(0.22))
                    .frame(width: 18, height: 18)
                    .scaleEffect(nowPulse ? 1.15 : 0.92)
                    .opacity(nowPulse ? 0.0 : 0.9)

                Circle()
                    .fill(Color(red: 0.176, green: 0.788, blue: 0.251))
                    .frame(width: 8, height: 8)
            }
            .animation(.easeInOut(duration: 1.6).repeatForever(autoreverses: false), value: nowPulse)
            .onAppear { nowPulse = true }
        case .next:
            Image(systemName: "arrow.right")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(OverlayTheme.quaternaryText)
                .frame(width: 18, height: 18)
                .overlay(Circle().stroke(Color.white.opacity(0.34), style: StrokeStyle(lineWidth: 1, dash: [3, 2])))
        }
    }

    private func stepTextColor(_ kind: PeekStepKind) -> Color {
        switch kind {
        case .done:
            return OverlayTheme.doneText
        case .now:
            return OverlayTheme.primaryText
        case .next:
            return OverlayTheme.quaternaryText
        }
    }

    private var askBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "sparkle")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(OverlayTheme.tertiaryText)

            TextField("Ask Context anything", text: $draft)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(OverlayTheme.primaryText)
                .tint(OverlayTheme.primaryText)
                .focused($isMessageFieldFocused)
                .disabled(sessionController.status.isBusy)
                .onSubmit(submitDraft)

            if isMessageFieldFocused {
                keyboardHint("esc")

                Button(action: submitDraft) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(OverlayTheme.invertedForeground)
                        .frame(width: 22, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .background(canSubmitDraft ? Color.white.opacity(0.85) : Color.white.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                .disabled(!canSubmitDraft)
                .help("Send")
            }

            if evalModeEnabled, currentStepForAdvance != nil {
                evalAnnotationButton(systemName: "checkmark", help: "Mark step correct") {
                    Task { await sessionController.sendStepAnnotation(verdict: .correct) }
                }
                evalAnnotationButton(systemName: "xmark", help: "Mark step off-track") {
                    Task { await sessionController.sendStepAnnotation(verdict: .offTrack) }
                }
            }

            Button(action: advanceCurrentStep) {
                Image(systemName: "arrow.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(canAdvanceCurrentStep ? OverlayTheme.invertedForeground : OverlayTheme.tertiaryText)
                    .frame(width: 24, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .background(canAdvanceCurrentStep ? Color.white.opacity(0.85) : Color.white.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .disabled(!canAdvanceCurrentStep)
            .help("Next step")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(OverlayTheme.askSurface)
        .overlay(alignment: .top) {
            Rectangle()
                .fill(OverlayTheme.separator)
                .frame(height: 0.5)
        }
    }

    private func evalAnnotationButton(
        systemName: String,
        help: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(OverlayTheme.primaryText)
                .frame(width: 22, height: 22)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(Color.white.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
        .help(help)
    }

    private func keyboardHint(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10.5, weight: .regular, design: .monospaced))
            .foregroundStyle(OverlayTheme.tertiaryText)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.white.opacity(0.10))
            .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .stroke(OverlayTheme.hairline, lineWidth: 0.5)
            )
    }

    private func questionCard(_ batch: PendingQuestionBatch) -> some View {
        QuestionCardView(
            batch: batch,
            onSubmit: { answers in
                Task { await sessionController.submitQuestionAnswers(answers) }
            }
        )
        .padding(.horizontal, 12)
        .padding(.top, 10)
        .padding(.bottom, 4)
    }

    @ViewBuilder
    private func completionPromptCard(_ prompt: PendingCompletionPrompt) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "checkmark.seal")
                    .font(.system(size: 11, weight: .medium))
                Text(prompt.source == .llm ? "Looks done?" : "No more steps")
                    .font(.system(size: 10.5, weight: .medium))
                    .tracking(0.42)
                    .textCase(.uppercase)
            }
            .foregroundStyle(OverlayTheme.tertiaryText)

            Text(prompt.reason)
                .font(.system(size: 13.5))
                .foregroundStyle(OverlayTheme.primaryText)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 6) {
                Button("Finish tutorial") {
                    Task { await sessionController.confirmCompletion() }
                }
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(OverlayTheme.invertedForeground)
                .padding(.horizontal, 11)
                .padding(.vertical, 5)
                .background(OverlayTheme.invertedAccent)
                .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.smallButtonCornerRadius, style: .continuous))

                Button("Keep going") {
                    Task { await sessionController.rejectCompletion() }
                }
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(OverlayTheme.secondaryText)
                .padding(.horizontal, 11)
                .padding(.vertical, 5)
            }
            .padding(.top, 2)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(OverlayTheme.answerSurface)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 0.5)
        )
        .padding(.horizontal, 12)
        .padding(.top, 10)
        .padding(.bottom, 4)
    }

    /// Soft, non-modal toast for verifier hints. Tap "Something looks off"
    /// to acknowledge (forces a replan); tap X to dismiss (overrides the
    /// verifier and keeps the current step); no interaction auto-dismisses
    /// after `hintAutoDismissSeconds` — behavior on timeout is verdict-
    /// dependent on the backend, see backend/tutorial_session.handle_user_hint_response.
    private func verificationHintCard(_ hint: PendingVerificationHint) -> some View {
        let title: String = {
            switch hint.verdict {
            case .unsure:
                return "Not sure this matches"
            case .diverged, .blocked:
                return "Looks like we're off track"
            case .onTrack, .pending:
                // onTrack and pending should never surface as a hint:
                // onTrack proceeds silently; pending is consumed by the
                // backend retry loop. Render defensively rather than
                // crash if the contract drifts.
                return "Heads up"
            }
        }()

        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: hint.autoReplanning ? "arrow.triangle.2.circlepath" : "questionmark.circle")
                    .font(.system(size: 11, weight: .medium))
                Text(title)
                    .font(.system(size: 10.5, weight: .medium))
                    .tracking(0.42)
                    .textCase(.uppercase)
                Spacer(minLength: 0)
                Button {
                    Task { await sessionController.respondToHint(action: .dismiss) }
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(OverlayTheme.tertiaryText)
                }
                .buttonStyle(.plain)
            }
            .foregroundStyle(OverlayTheme.tertiaryText)

            if !hint.reason.isEmpty {
                Text(hint.reason)
                    .font(.system(size: 13))
                    .foregroundStyle(OverlayTheme.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Button {
                Task { await sessionController.respondToHint(action: .acknowledgeOff) }
            } label: {
                Text(hint.autoReplanning ? "Confirm something's off" : "Something looks off")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(OverlayTheme.invertedForeground)
                    .padding(.horizontal, 11)
                    .padding(.vertical, 5)
                    .background(OverlayTheme.invertedAccent)
                    .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.smallButtonCornerRadius, style: .continuous))
            }
            .buttonStyle(.plain)
            .padding(.top, 2)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(OverlayTheme.answerSurface)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 0.5)
        )
        .padding(.horizontal, 12)
        .padding(.top, 10)
        .padding(.bottom, 4)
        .task(id: hint.stepID) {
            // Auto-dismiss after a few seconds. .task(id:) is cancelled
            // when the hint goes away (acknowledge/dismiss clear the slot)
            // or when a new hint replaces it, so this won't fire late.
            try? await Task.sleep(nanoseconds: 6_000_000_000)
            await sessionController.respondToHint(action: .timeout)
        }
    }

    private var typingDots: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(OverlayTheme.primaryText.opacity(0.30))
                    .frame(width: 5, height: 5)
                    .opacity(loadingWordIndex == index ? 0.70 : 0.25)
            }
        }
    }

    private var finishedTutorialView: some View {
        VStack(spacing: 0) {
            Image(systemName: "checkmark")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(OverlayTheme.invertedForeground)
                .frame(width: 44, height: 44)
                .background(OverlayTheme.invertedAccent)
                .clipShape(Circle())
                .padding(.bottom, 14)

            Text("All done")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(OverlayTheme.primaryText)

            Text("\(latestPlan?.steps.count ?? 0) steps · \(tutorialName)")
                .font(.system(size: 12, weight: .medium))
                .tracking(0.48)
                .textCase(.uppercase)
                .foregroundStyle(OverlayTheme.tertiaryText)
                .padding(.top, 4)

            Button("Start new tutorial", action: startNewChat)
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(OverlayTheme.invertedForeground)
                .padding(.horizontal, 11)
                .padding(.vertical, 5)
                .background(OverlayTheme.invertedAccent)
                .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.smallButtonCornerRadius, style: .continuous))
                .padding(.top, 18)
        }
        .padding(.top, 28)
        .padding(.horizontal, 24)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity)
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
        .frame(maxHeight: Self.maximumChatResponseHeight)
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
        case .preparingScreen, .sending, .verifying:
            return sessionController.status.label
        case .planning(let label):
            if !sessionController.webSources.isEmpty {
                return "\(label) · \(sessionController.webSources.count) source\(sessionController.webSources.count == 1 ? "" : "s")"
            }
            return label
        case .ready, .awaitingConfirmation, .awaitingCompletion, .completed, .failed:
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

                    Text("Ask or correct")
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
                    TextField("Tell Context what changed...", text: $instructionDraft)
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

    private var statusChips: [StatusChip] {
        var chips: [StatusChip] = []

        if sessionController.status.isBusy {
            chips.append(StatusChip(
                id: "status",
                icon: nil,
                text: sessionController.status.label,
                showsDot: true
            ))
        } else if case .awaitingConfirmation = sessionController.status {
            chips.append(StatusChip(
                id: "status",
                icon: "questionmark.circle",
                text: "Awaiting confirmation",
                showsDot: false
            ))
        }

        if !sessionController.webSources.isEmpty {
            let count = sessionController.webSources.count
            chips.append(StatusChip(
                id: "sources",
                icon: "link",
                text: "\(count) source\(count == 1 ? "" : "s")",
                showsDot: false
            ))
        }

        if let flash = stepChipFlash {
            chips.append(StatusChip(
                id: "step",
                icon: flash.icon,
                text: flash.text,
                showsDot: false
            ))
        }

        return chips
    }

    @ViewBuilder
    private var statusChipRow: some View {
        let chips = statusChips
        let chipIDs = chips.map { $0.id }
        Group {
            if !chips.isEmpty {
                HStack(spacing: 6) {
                    ForEach(Array(chips.enumerated()), id: \.element.id) { index, chip in
                        statusChipView(chip)
                            .transition(chipTransition(forIndex: index, totalIncoming: chips.count))
                            .zIndex(Double(chips.count - index))
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 14)
                .padding(.top, 4)
                .padding(.bottom, 2)
            }
        }
        .animation(.spring(response: 0.42, dampingFraction: 0.82, blendDuration: 0.15), value: chipIDs)
        .onChange(of: planDiffSignature) { _ in handlePlanDiffChange() }
        .onChange(of: sessionController.stepProgress?.totalSteps ?? 0) { newTotal in
            if newTotal > 0 { lastSeenTotalSteps = newTotal }
        }
    }

    private func chipTransition(forIndex index: Int, totalIncoming: Int) -> AnyTransition {
        // Stagger only when the row is populating fresh (≥2 chips arriving together).
        let delay = totalIncoming >= 2 ? Double(index) * 0.04 : 0
        let insertion = AnyTransition.modifier(
            active: ChipEnterModifier(progress: 0),
            identity: ChipEnterModifier(progress: 1)
        )
        .animation(.spring(response: 0.40, dampingFraction: 0.78).delay(delay))

        let removal = AnyTransition.modifier(
            active: ChipExitModifier(progress: 0),
            identity: ChipExitModifier(progress: 1)
        )
        .animation(.spring(response: 0.28, dampingFraction: 0.95))

        return .asymmetric(insertion: insertion, removal: removal)
    }

    private var planDiffSignature: String {
        guard let diff = sessionController.lastPlanDiff else { return "" }
        return "\(diff.frozenPrefixLen)|\(diff.newTailLen)|\(diff.refinedCurrent)|\(diff.totalSteps)"
    }

    private func handlePlanDiffChange() {
        guard let diff = sessionController.lastPlanDiff else { return }
        let prior = lastSeenTotalSteps ?? diff.totalSteps
        let delta = diff.totalSteps - prior
        lastSeenTotalSteps = diff.totalSteps

        let flash: StepChipFlash
        if delta > 0 {
            flash = StepChipFlash(
                id: UUID(),
                text: "+\(delta) step\(delta == 1 ? "" : "s")",
                icon: "plus.circle"
            )
        } else if delta < 0 {
            flash = StepChipFlash(
                id: UUID(),
                text: "\(delta) step\(delta == -1 ? "" : "s")",
                icon: "minus.circle"
            )
        } else if diff.refinedCurrent {
            flash = StepChipFlash(id: UUID(), text: "Refined", icon: "wand.and.stars")
        } else {
            return
        }

        stepChipFlash = flash
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_200_000_000)
            if stepChipFlash?.id == flash.id {
                stepChipFlash = nil
            }
        }
    }

    private func stepProgressPill(text: String) -> some View {
        HStack(spacing: 5) {
            Image(systemName: "list.number")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(OverlayTheme.tertiaryText)
            Text(text)
                .font(.system(size: 10.5, weight: .medium, design: .monospaced))
                .foregroundStyle(OverlayTheme.secondaryText)
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
                .contentTransition(.numericText())
                .animation(.spring(response: 0.32, dampingFraction: 0.9), value: text)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(OverlayTheme.quietFill)
        .clipShape(Capsule(style: .continuous))
        .overlay(
            Capsule(style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 0.5)
        )
    }

    private func statusChipView(_ chip: StatusChip) -> some View {
        HStack(spacing: 5) {
            if chip.showsDot {
                Circle()
                    .fill(OverlayTheme.secondaryText)
                    .frame(width: 5, height: 5)
                    .opacity(nowPulse ? 1.0 : 0.35)
                    .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: nowPulse)
                    .onAppear { nowPulse = true }
            } else if let icon = chip.icon {
                Image(systemName: icon)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(OverlayTheme.tertiaryText)
            }

            Text(chip.text)
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(OverlayTheme.secondaryText)
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
                .contentTransition(.numericText())
                .animation(.spring(response: 0.32, dampingFraction: 0.9), value: chip.text)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(OverlayTheme.quietFill)
        .clipShape(Capsule(style: .continuous))
        .overlay(
            Capsule(style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 0.5)
        )
    }

    private var statusText: String {
        if isSendingInstruction {
            return "Reading screen"
        }

        if let progress = sessionController.stepProgress, progress.totalSteps > 0 {
            let stepFraction = "Step \(progress.stepIndex + 1)/\(progress.totalSteps)"
            switch sessionController.status {
            case .ready, .awaitingConfirmation:
                return stepFraction
            default:
                return "\(sessionController.status.label) · \(stepFraction)"
            }
        }

        return sessionController.status.label
    }

    private var latestPlan: TutorialPlan? {
        sessionController.messages.reversed().compactMap { message in
            if case .tutorialPlan(let plan) = message.content { return plan }
            return nil
        }.first
    }

    private var tutorialName: String {
        let rawName = latestPlan?.goal ?? latestPlan?.summary ?? "Context Tutorial"
        let trimmedName = rawName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty else { return "Context Tutorial" }
        return trimmedName
    }

    private var currentStepIndex: Int? {
        guard let plan = latestPlan, !plan.steps.isEmpty else { return nil }
        guard let currentStepID = sessionController.currentStepID else { return plan.steps.startIndex }
        return plan.steps.firstIndex { $0.stepId == currentStepID } ?? plan.steps.startIndex
    }

    private var tutorialProgress: CGFloat {
        guard let plan = latestPlan, !plan.steps.isEmpty, let currentStepIndex else { return 0 }
        let completedCount = min(plan.steps.count, currentStepIndex + (isTutorialFinished ? 1 : 0))
        return CGFloat(max(1, completedCount)) / CGFloat(plan.steps.count)
    }

    private var metaRightText: String {
        guard let plan = latestPlan, !plan.steps.isEmpty, let currentStepIndex else {
            return ""
        }
        return "\(currentStepIndex + 1) of \(plan.steps.count)"
    }

    private var isTutorialFinished: Bool {
        sessionController.status == .completed
    }

    private var peekSteps: TutorialPeekSteps {
        guard let plan = latestPlan, !plan.steps.isEmpty, let currentStepIndex else {
            return TutorialPeekSteps(done: nil, now: nil, next: nil)
        }

        let items = TutorialPlanDisplay.make(from: plan, currentStepID: sessionController.currentStepID).itemsByStepID()
        let doneStep = currentStepIndex > plan.steps.startIndex
            ? displayItem(for: plan.steps[currentStepIndex - 1], index: currentStepIndex - 1, items: items)
            : nil
        let nowStep = displayItem(for: plan.steps[currentStepIndex], index: currentStepIndex, items: items)
        let nextIndex = plan.steps.index(after: currentStepIndex)
        let nextStep = nextIndex < plan.steps.endIndex
            ? displayItem(for: plan.steps[nextIndex], index: nextIndex, items: items)
            : nil

        return TutorialPeekSteps(done: doneStep, now: nowStep, next: nextStep)
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

    private var canAdvanceCurrentStep: Bool {
        currentStepForAdvance != nil && !sessionController.status.isBusy
    }

    private var currentStepForAdvance: TutorialStep? {
        guard let plan = latestPlan, !plan.steps.isEmpty else { return nil }
        if let currentStepID = sessionController.currentStepID {
            return plan.steps.first { $0.stepId == currentStepID }
        }
        guard let currentStepIndex else { return nil }
        return plan.steps[currentStepIndex]
    }

    private func displayItem(
        for step: TutorialStep,
        index: Int,
        items: [String: TutorialStepDisplayItem]
    ) -> TutorialStepDisplayItem {
        items[step.stepId] ?? TutorialStepDisplayItem(
            step: step,
            stepNumber: index + 1,
            title: step.instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    private func handlePeekStepTap(kind: PeekStepKind, step: TutorialStep) {
        guard kind == .now else { return }
        toggleStepExpansion(step)
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
        case .tutorialPlanPreview(let preview):
            tutorialPlanPreviewRow(preview)
                .id(message.id)
        }
    }

    private func tutorialPlanPreviewRow(_ preview: PlanPreview) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Building tutorial…")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.primary)
                    Spacer(minLength: 0)
                }

                ForEach(preview.steps) { step in
                    HStack(alignment: .firstTextBaseline, spacing: 9) {
                        Text("\(step.index + 1)")
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: 16, alignment: .trailing)
                        Text(step.instruction)
                            .font(.system(size: 13))
                            .foregroundStyle(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
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
            .animation(.easeOut(duration: 0.18), value: preview.steps.count)

            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
        let display = TutorialPlanDisplay.make(from: plan, currentStepID: sessionController.currentStepID)

        return HStack {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(display.goal.isEmpty ? plan.summary : display.goal)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(2)

                    Text(display.progressText)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if let currentStep = display.currentStep {
                    tutorialCurrentStepCard(currentStep)
                }

                if !display.upcomingSteps.isEmpty {
                    upcomingStepList(display.upcomingSteps)
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

    private func tutorialCurrentStepCard(_ item: TutorialStepDisplayItem) -> some View {
        let step = item.step
        let isActive = activeStepID == step.stepId
        let isExpanded = expandedStepID == step.stepId
        let isHighlighted = isActive || isExpanded

        return VStack(alignment: .leading, spacing: 0) {
            Button {
                toggleStepExpansion(step)
            } label: {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 9) {
                        Image(systemName: iconName(for: step.actions.first))
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Color.accentColor)
                            .frame(width: 22, height: 22)

                        Text(item.title)
                            .font(.system(size: 16, weight: .semibold))
                            .lineSpacing(2)
                            .foregroundStyle(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .multilineTextAlignment(.leading)

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

                    if step.confidence < 0.7 {
                        Label("Low confidence target", systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 11)
                .padding(.vertical, 10)
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

            stepNextButtonRow(for: step)
        }
        .background(OverlayTheme.strongerFill)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                .stroke(isHighlighted ? Color.accentColor.opacity(0.45) : OverlayTheme.hairline, lineWidth: 1)
        )
    }

    @ViewBuilder
    private func stepNextButtonRow(for step: TutorialStep) -> some View {
        let enabled = canAdvanceCurrentStep && currentStepForAdvance?.stepId == step.stepId
        HStack {
            Spacer()
            Button(action: advanceCurrentStep) {
                Text("Next")
                    .font(.system(size: 13, weight: .semibold))
                    .padding(.horizontal, 18)
                    .padding(.vertical, 7)
                    .foregroundStyle(enabled ? Color.white : Color.white.opacity(0.5))
                    .background(enabled ? Color.accentColor : Color.accentColor.opacity(0.35))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(!enabled)
            .help("Advance to the next step")
            .keyboardShortcut(.return, modifiers: [])
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 9)
    }

    private func upcomingStepList(_ steps: [TutorialStepDisplayItem]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Next")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 5) {
                ForEach(steps) { item in
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text("\(item.stepNumber).")
                            .font(.caption)
                            .foregroundStyle(.secondary.opacity(0.8))
                            .frame(width: 18, alignment: .trailing)

                        Text(item.title)
                            .font(.system(size: 12))
                            .lineLimit(2)
                            .foregroundStyle(.secondary.opacity(0.78))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

            Text("Use the arrow at the bottom to continue.")
                .font(.caption)
                .foregroundStyle(.secondary)
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
        for action in step.actions {
            if case .type(let typeAction) = action { return typeAction.text }
        }
        return nil
    }

    private func stepTargetDescription(for step: TutorialStep) -> String? {
        guard let action = step.actions.first else { return nil }
        switch action {
        case .click(let a): return a.target.description
        case .doubleClick(let a): return a.target.description
        case .rightClick(let a): return a.target.description
        case .hover(let a): return a.target.description
        case .drag(let a): return a.target.description
        case .type(let a): return a.target?.description
        case .scroll(let a): return a.target?.description
        case .pressKey(let a): return "Key: \(a.key)"
        case .userChoice(let a): return a.prompt
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

    private func copyTypeTextToPasteboard(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private func canSelectTutorialStep(_ step: TutorialStep) -> Bool {
        !sessionController.status.isBusy
    }

    private func iconName(for action: TutorialAction?) -> String {
        guard let action else { return "circle" }
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
        case .userChoice:
            return "hand.tap"
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
        stepJSONPreview = nil
        loadingWordIndex = 0
        sessionController.startNewChat()
    }

    private func selectTutorialStep(_ step: TutorialStep) {
        guard activeStepID == nil, canSelectTutorialStep(step) else { return }
        activeStepID = step.stepId

        Task {
            let actionIndex = sessionController.awaitingActionIndex ?? sessionController.currentActionIndex ?? 0
            await sessionController.markStepStarted(stepID: step.stepId, actionIndex: actionIndex)
            _ = await onTutorialStepSelected(step)
            await MainActor.run {
                activeStepID = nil
            }
        }
    }

    private func advanceCurrentStep() {
        guard let step = currentStepForAdvance, canAdvanceCurrentStep else { return }
        let actionIndex = sessionController.awaitingActionIndex ?? sessionController.currentActionIndex ?? 0
        expandedStepID = nil
        Task {
            await sessionController.confirmStep(
                stepID: step.stepId,
                actionIndex: actionIndex,
                confirmed: true,
                note: nil
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

        let response = SystemDialogPresenter.runSynchronously { panel.runModal() }
        guard response == .OK, let url = panel.url else { return }

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

private extension TutorialPlanDisplay {
    func itemsByStepID() -> [String: TutorialStepDisplayItem] {
        var items: [String: TutorialStepDisplayItem] = [:]
        if let currentStep {
            items[currentStep.step.stepId] = currentStep
        }
        for upcomingStep in upcomingSteps {
            items[upcomingStep.step.stepId] = upcomingStep
        }
        return items
    }
}

private extension String {
    func caseInsensitiveEquals(_ other: String) -> Bool {
        compare(other, options: [.caseInsensitive, .diacriticInsensitive]) == .orderedSame
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

// MARK: - Clarifying question card

/// Renders a turn-0 ``PendingQuestionBatch`` from the planner: 1-4
/// questions in a vertical stack, each with either a chip-list of
/// suggested options plus an "Other..." text field, or a single
/// free-text field. The Send button only enables once every question
/// has a non-empty answer.
private struct QuestionCardView: View {
    let batch: PendingQuestionBatch
    let onSubmit: ([String: String]) -> Void

    @State private var selectedOption: [String: String] = [:]
    @State private var customText: [String: String] = [:]
    @State private var isCustom: [String: Bool] = [:]

    private var answers: [String: String] {
        var result: [String: String] = [:]
        for question in batch.questions {
            let value = currentAnswer(for: question)
            if !value.isEmpty {
                result[question.questionID] = value
            }
        }
        return result
    }

    private var canSubmit: Bool {
        answers.count == batch.questions.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header

            VStack(alignment: .leading, spacing: 14) {
                ForEach(batch.questions) { question in
                    questionBlock(question)
                }
            }

            HStack {
                Spacer()
                Button(action: submit) {
                    Text(batch.questions.count == 1 ? "Send answer" : "Send answers")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(canSubmit ? OverlayTheme.invertedForeground : OverlayTheme.tertiaryText)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(canSubmit ? OverlayTheme.invertedAccent : OverlayTheme.strongerFill)
                        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.smallButtonCornerRadius, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(!canSubmit)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(OverlayTheme.answerSurface)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 0.5)
        )
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "questionmark.circle")
                    .font(.system(size: 11, weight: .medium))
                Text("Quick question\(batch.questions.count == 1 ? "" : "s")")
                    .font(.system(size: 10.5, weight: .medium))
                    .tracking(0.42)
                    .textCase(.uppercase)
            }
            .foregroundStyle(OverlayTheme.tertiaryText)

            Text(batch.reason)
                .font(.system(size: 12))
                .foregroundStyle(OverlayTheme.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func questionBlock(_ question: TutorialAssistantQuestion) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(question.prompt)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(OverlayTheme.primaryText)
                .fixedSize(horizontal: false, vertical: true)

            switch question.responseMode {
            case .options:
                optionsField(question)
            case .freeText:
                freeTextField(question)
            }
        }
    }

    private func optionsField(_ question: TutorialAssistantQuestion) -> some View {
        let chosen = selectedOption[question.questionID]
        let isOther = isCustom[question.questionID] ?? false

        return VStack(alignment: .leading, spacing: 6) {
            FlowLayout(spacing: 6) {
                ForEach(question.options, id: \.self) { option in
                    optionChip(
                        title: option,
                        isSelected: !isOther && chosen == option,
                        action: {
                            selectedOption[question.questionID] = option
                            isCustom[question.questionID] = false
                        }
                    )
                }
                if question.allowsCustomAnswer {
                    optionChip(
                        title: "Other…",
                        isSelected: isOther,
                        action: {
                            isCustom[question.questionID] = true
                            selectedOption[question.questionID] = nil
                        }
                    )
                }
            }

            if isOther {
                customTextField(for: question, placeholder: "Type your answer")
            }
        }
    }

    private func freeTextField(_ question: TutorialAssistantQuestion) -> some View {
        customTextField(for: question, placeholder: "Type your answer")
    }

    private func customTextField(for question: TutorialAssistantQuestion, placeholder: String) -> some View {
        TextField(
            placeholder,
            text: Binding(
                get: { customText[question.questionID] ?? "" },
                set: { customText[question.questionID] = $0 }
            )
        )
        .textFieldStyle(.plain)
        .font(.system(size: 12.5))
        .foregroundStyle(OverlayTheme.primaryText)
        .tint(OverlayTheme.primaryText)
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(OverlayTheme.strongerFill)
        .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: OverlayTheme.compactCornerRadius, style: .continuous)
                .stroke(OverlayTheme.hairline, lineWidth: 0.5)
        )
        .onSubmit {
            if canSubmit { submit() }
        }
    }

    private func optionChip(title: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(isSelected ? OverlayTheme.invertedForeground : OverlayTheme.primaryText)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(isSelected ? OverlayTheme.invertedAccent : OverlayTheme.strongerFill)
                .clipShape(RoundedRectangle(cornerRadius: OverlayTheme.smallButtonCornerRadius, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: OverlayTheme.smallButtonCornerRadius, style: .continuous)
                        .stroke(isSelected ? Color.clear : OverlayTheme.hairline, lineWidth: 0.5)
                )
        }
        .buttonStyle(.plain)
    }

    private func currentAnswer(for question: TutorialAssistantQuestion) -> String {
        switch question.responseMode {
        case .freeText:
            return (customText[question.questionID] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        case .options:
            if isCustom[question.questionID] ?? false {
                return (customText[question.questionID] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            }
            return (selectedOption[question.questionID] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }

    private func submit() {
        guard canSubmit else { return }
        onSubmit(answers)
    }
}

/// Minimal flow layout for wrapping option chips. Native ``Layout``
/// keeps this lightweight; we don't depend on a third-party package.
private struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        let rows = layoutRows(subviews: subviews, maxWidth: maxWidth)
        let height = rows.reduce(CGFloat(0)) { partial, row in
            partial + row.height + (partial == 0 ? 0 : spacing)
        }
        return CGSize(width: maxWidth.isFinite ? maxWidth : rows.map(\.width).max() ?? 0, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let maxWidth = bounds.width
        let rows = layoutRows(subviews: subviews, maxWidth: maxWidth)
        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            for item in row.items {
                let size = subviews[item.index].sizeThatFits(.unspecified)
                subviews[item.index].place(
                    at: CGPoint(x: x, y: y),
                    proposal: ProposedViewSize(size)
                )
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var items: [(index: Int, width: CGFloat)] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func layoutRows(subviews: Subviews, maxWidth: CGFloat) -> [Row] {
        var rows: [Row] = []
        var current = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let projected = current.width + (current.items.isEmpty ? 0 : spacing) + size.width
            if !current.items.isEmpty && projected > maxWidth {
                rows.append(current)
                current = Row()
            }
            current.items.append((index, size.width))
            current.width += (current.items.count == 1 ? 0 : spacing) + size.width
            current.height = max(current.height, size.height)
        }
        if !current.items.isEmpty { rows.append(current) }
        return rows
    }
}
