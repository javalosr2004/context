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
        guard let normalizedContent = normalized(content) else { return nil }

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
        append(role: .user, content: .text(text), now: now)
    }

    @discardableResult
    func appendTutorialText(_ text: String, now: () -> Date = Date.init) -> ChatMessage? {
        append(role: .tutorial, content: .text(text), now: now)
    }

    @discardableResult
    func appendTutorialPlan(_ plan: TutorialPlan, now: () -> Date = Date.init) -> ChatMessage? {
        append(role: .tutorial, content: .tutorialPlan(plan), now: now)
    }

    func removeAll() {
        messages.removeAll()
    }

    private func normalized(_ content: ChatMessageContent) -> ChatMessageContent? {
        switch content {
        case .text(let text):
            let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmedText.isEmpty else { return nil }
            return .text(trimmedText)
        case .tutorialPlan:
            return content
        }
    }
}
