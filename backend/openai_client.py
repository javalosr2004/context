from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from backend.images import UploadedImage
from backend.llm import LLMRequest


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "medium",
        verbosity: str = "medium",
    ) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._verbosity = verbosity

    def complete_text(self, request: LLMRequest) -> str:
        response = self._client.responses.create(
            model=self._model,
            input=build_input(request),
            **build_response_params(
                reasoning_effort=self._reasoning_effort,
                verbosity=self._verbosity,
                enable_search_grounding=request.enable_search_grounding,
                response_mime_type=request.response_mime_type,
                response_schema=request.response_schema,
            ),
        )
        return response.output_text or ""

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        stream = self._client.responses.create(
            model=self._model,
            input=build_input(request),
            stream=True,
            **build_response_params(
                reasoning_effort=self._reasoning_effort,
                verbosity=self._verbosity,
                enable_search_grounding=request.enable_search_grounding,
                response_mime_type=request.response_mime_type,
                response_schema=request.response_schema,
            ),
        )

        for event in stream:
            delta = getattr(event, "delta", None)
            if delta and getattr(event, "type", "") == "response.output_text.delta":
                yield delta


def build_input(request: LLMRequest) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": request.system_prompt},
        {"role": "user", "content": build_user_content(request.user_text, request.images)},
    ]


def build_user_content(text: str, images: list[UploadedImage]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
    content.extend(build_image_content(image) for image in images)
    return content


def build_image_content(image: UploadedImage) -> dict[str, Any]:
    encoded = base64.b64encode(image.data).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{image.mime_type};base64,{encoded}",
    }


def build_response_params(
    reasoning_effort: str,
    verbosity: str,
    enable_search_grounding: bool,
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": build_text_format(response_mime_type, response_schema), "verbosity": verbosity},
    }
    if enable_search_grounding:
        params["tools"] = [{"type": "web_search"}]
    return params


def build_text_format(
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    if response_mime_type == "application/json" and response_schema is not None:
        return {
            "type": "json_schema",
            "name": "response",
            "schema": response_schema,
            "strict": True,
        }
    if response_mime_type == "application/json":
        return {"type": "json_object"}
    return {"type": "text"}
