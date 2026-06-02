import Foundation

enum ChatMessageRole: Equatable {
    case user
    case tutorial
}

/// One instruction streamed from the planner ahead of the merged plan.
/// `index` is the step's position in the streaming tail and doubles as a
/// stable identity for row animation.
struct PlanPreviewStep: Equatable, Identifiable {
    let index: Int
    let instruction: String
    let confidence: Double
    var id: Int { index }
}

/// A plan still being streamed. Replaced wholesale by the authoritative
/// `.tutorialPlan` once `plan_ready`/`plan_updated` arrives.
struct PlanPreview: Equatable {
    var steps: [PlanPreviewStep]
}

enum ChatMessageContent: Equatable {
    case text(String)
    case tutorialPlan(TutorialPlan)
    case tutorialPlanPreview(PlanPreview)
}

struct ChatMessage: Equatable, Identifiable {
    let id: UUID
    let role: ChatMessageRole
    let content: ChatMessageContent
    let createdAt: Date
}

final class ChatMessageStore {
    private(set) var messages: [ChatMessage] = []

    @discardableResult
    func append(
        role: ChatMessageRole,
        content: ChatMessageContent,
        now: () -> Date = Date.init
    ) -> ChatMessage? {
        guard let normalizedContent = normalized(content, role: role) else { return nil }

        let message = ChatMessage(
            id: UUID(),
            role: role,
            content: normalizedContent,
            createdAt: now()
        )
        messages.append(message)
        return message
    }

    @discardableResult
    func appendUserText(_ text: String, now: () -> Date = Date.init) -> ChatMessage? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return append(role: .user, content: .text(trimmed), now: now)
    }

    @discardableResult
    func appendTutorialText(_ text: String, now: () -> Date = Date.init) -> ChatMessage? {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return append(role: .tutorial, content: .text(text), now: now)
    }

    @discardableResult
    func appendTutorialTextDelta(_ text: String, now: () -> Date = Date.init) -> ChatMessage? {
        guard
            let lastIndex = messages.indices.last,
            messages[lastIndex].role == .tutorial,
            case .text(let existingText) = messages[lastIndex].content
        else {
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return nil
            }
            return appendTutorialText(text, now: now)
        }

        guard !text.isEmpty else { return nil }

        let existingMessage = messages[lastIndex]
        let updatedMessage = ChatMessage(
            id: existingMessage.id,
            role: existingMessage.role,
            content: .text(existingText + text),
            createdAt: existingMessage.createdAt
        )
        messages[lastIndex] = updatedMessage
        return updatedMessage
    }

    @discardableResult
    func replaceLastTutorialText(_ text: String) -> ChatMessage? {
        guard let normalizedContent = normalized(.text(text), role: .tutorial) else {
            return nil
        }
        guard
            let lastIndex = messages.indices.last,
            messages[lastIndex].role == .tutorial,
            case .text = messages[lastIndex].content
        else {
            return appendTutorialText(text)
        }

        let existingMessage = messages[lastIndex]
        let updatedMessage = ChatMessage(
            id: existingMessage.id,
            role: existingMessage.role,
            content: normalizedContent,
            createdAt: existingMessage.createdAt
        )
        messages[lastIndex] = updatedMessage
        return updatedMessage
    }

    @discardableResult
    func appendTutorialPlan(_ plan: TutorialPlan, now: () -> Date = Date.init) -> ChatMessage? {
        append(role: .tutorial, content: .tutorialPlan(plan), now: now)
    }

    @discardableResult
    func replaceLatestTutorialPlan(_ plan: TutorialPlan, now: () -> Date = Date.init) -> ChatMessage? {
        let matchingIndex = messages.lastIndex { message in
            if case .tutorialPlan = message.content { return true }
            return false
        }

        guard let index = matchingIndex else {
            return appendTutorialPlan(plan, now: now)
        }

        let existing = messages[index]
        let updated = ChatMessage(
            id: existing.id,
            role: .tutorial,
            content: .tutorialPlan(plan),
            createdAt: existing.createdAt
        )
        messages[index] = updated
        return updated
    }

    /// Append (or update by index) a streamed preview step, coalescing into
    /// the trailing preview message so the plan card grows in place.
    @discardableResult
    func appendPlanPreviewStep(
        index: Int,
        instruction: String,
        confidence: Double,
        now: () -> Date = Date.init
    ) -> ChatMessage? {
        let trimmed = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let step = PlanPreviewStep(index: index, instruction: trimmed, confidence: confidence)

        guard
            let lastIndex = messages.indices.last,
            messages[lastIndex].role == .tutorial,
            case .tutorialPlanPreview(var preview) = messages[lastIndex].content
        else {
            return append(
                role: .tutorial,
                content: .tutorialPlanPreview(PlanPreview(steps: [step])),
                now: now
            )
        }

        if let existing = preview.steps.firstIndex(where: { $0.index == step.index }) {
            preview.steps[existing] = step
        } else {
            preview.steps.append(step)
            preview.steps.sort { $0.index < $1.index }
        }
        let existing = messages[lastIndex]
        let updated = ChatMessage(
            id: existing.id,
            role: .tutorial,
            content: .tutorialPlanPreview(preview),
            createdAt: existing.createdAt
        )
        messages[lastIndex] = updated
        return updated
    }

    /// Drop any streamed preview messages. Called when the authoritative
    /// plan lands, a new plan starts streaming, or the session resets.
    @discardableResult
    func clearPlanPreview() -> Bool {
        let before = messages.count
        messages.removeAll { message in
            if case .tutorialPlanPreview = message.content { return true }
            return false
        }
        return messages.count != before
    }

    func removeAll() {
        messages.removeAll()
    }

    private func normalized(_ content: ChatMessageContent, role: ChatMessageRole) -> ChatMessageContent? {
        switch content {
        case .text(let text):
            let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmedText.isEmpty else {
                return nil
            }
            if role == .user {
                return .text(trimmedText)
            }
            return .text(text)
        case .tutorialPlan, .tutorialPlanPreview:
            return content
        }
    }
}
