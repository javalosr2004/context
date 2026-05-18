"""MultimodalLLM implementation for HCompany's Holo via chat.completions.

The Holo gateway at ``api.hcompany.ai`` exposes only the OpenAI-compatible
``/v1/chat/completions`` route. Routing it through :class:`OpenAIClient`
(which targets the Responses API) 404s. This client mirrors what
:class:`HoloLocalizer` already does for visual grounding: chat.completions
plus ``extra_body.structured_outputs`` for JSON-schema constrained output.

Tool-calling is handled the same way the Gemini client handles it — we ask
the model to return a JSON list of tool calls under
:func:`tutorial_tool_response_schema` and parse it locally — rather than
relying on chat.completions native ``tools`` (which Holo may or may not
honor reliably for our strict union schemas).
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from backend.images import UploadedImage
from backend.llm import (
    LLMRequest,
    LLMStreamEvent,
    LLMToolCallEvent,
)
from backend.tutorial_tools import (
    TutorialToolCall,
    parse_tutorial_tool_call_list,
    tutorial_tool_response_schema,
)


logger = logging.getLogger(__name__)


class HoloChatClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        client: OpenAI | None = None,
    ) -> None:
        self._model = model
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)

    def complete_text(self, request: LLMRequest) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=build_messages(request),
            temperature=request.temperature if request.temperature is not None else 0.0,
            extra_body=build_extra_body(
                response_mime_type=request.response_mime_type,
                response_schema=request.response_schema,
            ),
        )
        return response.choices[0].message.content or ""

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=build_messages(request),
            temperature=request.temperature if request.temperature is not None else 0.0,
            stream=True,
            extra_body=build_extra_body(
                response_mime_type=request.response_mime_type,
                response_schema=request.response_schema,
            ),
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                yield content

    def stream_tutorial_tool_calls(
        self, request: LLMRequest
    ) -> Iterator[TutorialToolCall]:
        for event in self.stream_tutorial_events(request):
            if isinstance(event, LLMToolCallEvent):
                yield event.tool_call

    def stream_tutorial_events(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        response_text = self.complete_text(
            LLMRequest(
                system_prompt=request.system_prompt,
                user_text=request.user_text,
                images=request.images,
                enable_search_grounding=request.enable_search_grounding,
                response_mime_type="application/json",
                response_schema=tutorial_tool_response_schema(),
                temperature=request.temperature,
            )
        )
        for tool_call in parse_tutorial_tool_call_list(response_text):
            yield LLMToolCallEvent(tool_call=tool_call)


def build_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": request.system_prompt},
        {"role": "user", "content": build_user_content(request.user_text, request.images)},
    ]


def build_user_content(text: str, images: list[UploadedImage]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for image in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_uri(image)},
            }
        )
    content.append({"type": "text", "text": text})
    return content


def data_uri(image: UploadedImage) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"


def build_extra_body(
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if response_mime_type == "application/json" and response_schema is not None:
        extra["structured_outputs"] = {"json": response_schema}
    elif response_mime_type == "application/json":
        # Fall back to JSON-mode hint when no schema is provided.
        extra["response_format"] = {"type": "json_object"}
    return extra


__all__ = [
    "HoloChatClient",
    "build_messages",
    "build_user_content",
    "build_extra_body",
    "data_uri",
]
