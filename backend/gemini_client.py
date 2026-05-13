from __future__ import annotations

from collections.abc import Iterator

from google import genai
from google.genai import types

from backend.images import UploadedImage
from backend.llm import LLMRequest


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def complete_text(self, request: LLMRequest) -> str:
        parts = build_user_parts(request.user_text, request.images)
        response = self._client.models.generate_content(
            model=self._model,
            contents=[types.Content(role="user", parts=parts)],
            config=build_generate_content_config(
                system_prompt=request.system_prompt,
                enable_search_grounding=request.enable_search_grounding,
                response_mime_type=request.response_mime_type,
            ),
        )
        return response.text or ""

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        parts = build_user_parts(request.user_text, request.images)
        stream = self._client.models.generate_content_stream(
            model=self._model,
            contents=[types.Content(role="user", parts=parts)],
            config=build_generate_content_config(
                system_prompt=request.system_prompt,
                enable_search_grounding=request.enable_search_grounding,
                response_mime_type=request.response_mime_type,
            ),
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


def build_generate_content_config(
    system_prompt: str,
    enable_search_grounding: bool,
    response_mime_type: str | None = None,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[build_google_search_tool()] if enable_search_grounding else [],
        response_mime_type=response_mime_type,
    )


def build_google_search_tool() -> types.Tool:
    return types.Tool(google_search=types.GoogleSearch())
