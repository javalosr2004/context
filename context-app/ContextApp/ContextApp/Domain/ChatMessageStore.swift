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
    func appendTutorialPlan(_ plan: TutorialPlan, now: () -> Date = Date.init) -> ChatMessage? {
        append(role: .tutorial, content: .tutorialPlan(plan), now: now)
    }

    @discardableResult
    func appendTutorialTextDelta(_ text: String, now: () -> Date = Date.init) -> ChatMessage? {
        if let last = messages.last,
           last.role == .tutorial,
           case .text(let existing) = last.content {
            let combined = existing + text
            let updated = ChatMessage(
                id: last.id,
                role: last.role,
                content: .text(combined),
                createdAt: last.createdAt
            )
            messages[messages.count - 1] = updated
            return updated
        }

        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let message = ChatMessage(
            id: UUID(),
            role: .tutorial,
            content: .text(text),
            createdAt: now()
        )
        messages.append(message)
        return message
    }

    @discardableResult
    func replaceLastTutorialText(_ text: String) -> ChatMessage? {
        guard let last = messages.last,
              last.role == .tutorial,
              case .text = last.content
        else { return nil }

        let updated = ChatMessage(
            id: last.id,
            role: last.role,
            content: .text(text),
            createdAt: last.createdAt
        )
        messages[messages.count - 1] = updated
        return updated
    }

    func removeAll() {
        messages.removeAll()
    }

    private func normalized(_ content: ChatMessageContent, role: ChatMessageRole) -> ChatMessageContent? {
        switch content {
        case .text(let text):
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return role == .user ? .text(text.trimmingCharacters(in: .whitespacesAndNewlines)) : .text(text)
        case .tutorialPlan:
            return content
        }
    }
}
