from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from backend.images import UploadedImage


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_text: str
    images: list[UploadedImage]
    enable_search_grounding: bool = False


class MultimodalLLM(Protocol):
    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        """Stream text from a multimodal model for one request."""
