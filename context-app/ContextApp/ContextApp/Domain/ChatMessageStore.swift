import Foundation

enum ChatMessageRole: Equatable {
    case user
    case tutorial
}

enum ChatMessageContent: Equatable {
    case text(String)
    case tutorialPlan(TutorialPlan)
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
        case .tutorialPlan:
            return content
        }
    }
}
