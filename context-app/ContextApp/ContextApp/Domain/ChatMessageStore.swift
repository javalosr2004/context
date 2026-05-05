import Foundation

struct ChatMessage: Equatable, Identifiable {
    let id: UUID
    let text: String
    let createdAt: Date
}

final class ChatMessageStore {
    private(set) var messages: [ChatMessage] = []

    @discardableResult
    func append(_ text: String, now: () -> Date = Date.init) -> ChatMessage? {
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedText.isEmpty else { return nil }

        let message = ChatMessage(id: UUID(), text: trimmedText, createdAt: now())
        messages.append(message)
        return message
    }
}
