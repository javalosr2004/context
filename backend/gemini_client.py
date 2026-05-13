from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from google import genai
from google.genai import types

from backend.images import UploadedImage


@dataclass(frozen=True)
class GeminiStreamRequest:
    conversation_id: str
    text: str
    images: list[UploadedImage]


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def stream_response(self, request: GeminiStreamRequest) -> Iterator[str]:
        parts = build_user_parts(request.text, request.images)
        stream = self._client.models.generate_content_stream(
            model=self._model,
            contents=[types.Content(role="user", parts=parts)],
        )

        for chunk in stream:
            if chunk.text:
                yield chunk.text


def build_user_parts(text: str, images: list[UploadedImage]) -> list[types.Part]:
    parts = [types.Part(text=text)]
    parts.extend(build_image_part(image) for image in images)
    return parts


def build_image_part(image: UploadedImage) -> types.Part:
    return types.Part(
        inline_data=types.Blob(
            mime_type=image.mime_type,
            data=image.data,
        )
    )
