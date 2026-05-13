from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from google import genai
from google.genai import types

from backend.images import UploadedImage


TUTORIAL_CREATOR_SYSTEM_PROMPT = (
    "Your task is to be an agentic tutorial creator. You will create verbose "
    "tutorials that describe what action to perform - click, hover, scroll. "
    "When useful, look for tutorials, official documentation, or other helpful "
    "current information with Google Search. Prefer concrete, step-by-step "
    "instructions over generic advice. If the screen or user intent is unclear, "
    "state the uncertainty and ask for confirmation before continuing."
)


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
            config=build_generate_content_config(),
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


def build_generate_content_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=TUTORIAL_CREATOR_SYSTEM_PROMPT,
        tools=[build_google_search_tool()],
    )


def build_google_search_tool() -> types.Tool:
    return types.Tool(google_search=types.GoogleSearch())
