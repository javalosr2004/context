from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from backend.images import UploadedImage


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_text: str
    images: list[UploadedImage]
    enable_search_grounding: bool = False
    response_mime_type: str | None = None
    response_schema: dict[str, Any] | None = None
    temperature: float | None = None


class MultimodalLLM(Protocol):
    def complete_text(self, request: LLMRequest) -> str:
        """Return one complete text response from a multimodal model."""

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        """Stream text from a multimodal model for one request."""
