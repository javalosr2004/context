from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Conversation:
    id: str


class ConversationRepository(Protocol):
    def get_conversation(self, conversation_id: str) -> Conversation:
        """Return the current conversation context for a request."""


class InMemoryConversationRepository:
    def get_conversation(self, conversation_id: str) -> Conversation:
        # Placeholder for: conversation = getConversation(conversation_id)
        return Conversation(id=conversation_id)
