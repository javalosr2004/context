from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from backend.images import UploadedImage
from backend.tutorial_tools import TutorialToolCall


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_text: str
    images: list[UploadedImage]
    enable_search_grounding: bool = False
    response_mime_type: str | None = None
    response_schema: dict[str, Any] | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class LLMTextDelta:
    text: str


@dataclass(frozen=True)
class LLMToolCallEvent:
    tool_call: TutorialToolCall


@dataclass(frozen=True)
class LLMWebSearchStarted:
    """The model invoked a native web_search tool. ``query`` may be empty
    if the provider hasn't surfaced it yet — the started event fires on
    output_item.added, which can precede the query being known."""
    query: str = ""


@dataclass(frozen=True)
class LLMWebSearchCompleted:
    """The model's native web_search tool finished. ``elapsed_ms`` is
    measured from the matching ``LLMWebSearchStarted`` event."""
    query: str = ""
    elapsed_ms: float = 0.0


LLMStreamEvent = (
    LLMTextDelta | LLMToolCallEvent | LLMWebSearchStarted | LLMWebSearchCompleted
)


class MultimodalLLM(Protocol):
    def complete_text(self, request: LLMRequest) -> str:
        """Return one complete text response from a multimodal model."""

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        """Stream text from a multimodal model for one request."""

    def stream_tutorial_tool_calls(
        self,
        request: LLMRequest,
    ) -> Iterator[TutorialToolCall]:
        """Stream typed tutorial tool calls from a multimodal model."""

    def stream_tutorial_events(
        self,
        request: LLMRequest,
    ) -> Iterator[LLMStreamEvent]:
        """Stream provider-native tutorial events, including text when available."""
