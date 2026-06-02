from __future__ import annotations

import base64
import logging
import time
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from backend.images import UploadedImage
from backend.llm import (
    LLMRequest,
    LLMStreamEvent,
    LLMTextDelta,
    LLMToolCallArgsDelta,
    LLMToolCallEvent,
    LLMWebSearchCompleted,
    LLMWebSearchStarted,
)
from backend.tutorial_tools import (
    UPDATE_PLAN_TOOL_NAME,
    TutorialToolCall,
    openai_tutorial_tool_definitions,
)


logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str | None = "medium",
        verbosity: str | None = "medium",
        base_url: str | None = None,
    ) -> None:
        client_options: dict[str, str] = {"api_key": api_key}
        if base_url is not None:
            client_options["base_url"] = base_url
        self._client = OpenAI(**client_options)
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

    def stream_tutorial_tool_calls(self, request: LLMRequest) -> Iterator[TutorialToolCall]:
        for event in self.stream_tutorial_events(request):
            if isinstance(event, LLMToolCallEvent):
                yield event.tool_call

    def stream_tutorial_events(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        tools = openai_tutorial_tool_definitions()
        tool_names = [tool.get("name") or tool.get("type") for tool in tools]
        if request.enable_search_grounding:
            tool_names.append("web_search")
        logger.info(
            "[llm] stream start",
            extra={
                "model": self._model,
                "tool_count": len(tool_names),
                "tool_names": tool_names,
                "enable_search_grounding": request.enable_search_grounding,
            },
        )
        started_at = time.perf_counter()
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
                tools=tools,
            ),
        )

        first_event_logged = False
        text_delta_count = 0
        tool_call_count = 0
        tool_args_delta_count = 0
        web_search_count = 0
        other_count = 0
        # Function-call argument deltas arrive without the tool name; only
        # the output_item.added event carries it. Map item_id -> name so we
        # can attribute streamed args to the right tool.
        function_call_names: dict[str, str] = {}
        # When the planner runs web_search the API streams Started before
        # Completed; we stamp elapsed_ms here because it's the only place
        # both timestamps are visible. Track the last Started across all
        # in-flight searches — OpenAI emits at most one in flight per
        # response, so a single timestamp suffices.
        last_search_started_at: float | None = None
        for event in stream:
            if not first_event_logged:
                logger.info(
                    "[llm] stream first_event",
                    extra={
                        "model": self._model,
                        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                )
                first_event_logged = True
            event_type = getattr(event, "type", "")
            if event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if getattr(item, "type", "") == "function_call":
                    item_id = getattr(item, "id", "") or ""
                    if item_id:
                        function_call_names[item_id] = getattr(item, "name", "") or ""
            elif event_type == "response.function_call_arguments.delta":
                delta = getattr(event, "delta", None)
                item_id = getattr(event, "item_id", "") or ""
                if delta and function_call_names.get(item_id) == UPDATE_PLAN_TOOL_NAME:
                    tool_args_delta_count += 1
                    yield LLMToolCallArgsDelta(
                        name=UPDATE_PLAN_TOOL_NAME, delta=delta, call_id=item_id
                    )
                continue
            stream_event = stream_event_from_response_event(event)
            if stream_event is None:
                other_count += 1
                continue
            if isinstance(stream_event, LLMTextDelta):
                text_delta_count += 1
            elif isinstance(stream_event, LLMToolCallEvent):
                tool_call_count += 1
            elif isinstance(stream_event, LLMWebSearchStarted):
                web_search_count += 1
                last_search_started_at = time.perf_counter()
            elif isinstance(stream_event, LLMWebSearchCompleted):
                if last_search_started_at is not None:
                    elapsed_ms = (
                        time.perf_counter() - last_search_started_at
                    ) * 1000.0
                    stream_event = LLMWebSearchCompleted(
                        query=stream_event.query, elapsed_ms=elapsed_ms
                    )
                    last_search_started_at = None
            yield stream_event

        logger.info(
            "[llm] stream end",
            extra={
                "model": self._model,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "text_delta_count": text_delta_count,
                "tool_call_count": tool_call_count,
                "tool_args_delta_count": tool_args_delta_count,
                "web_search_count": web_search_count,
                "other_event_count": other_count,
            },
        )


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
        # Force full-resolution vision tokens. Default "auto" downsamples
        # large screenshots, which costs us UI-label legibility.
        "detail": "high",
    }


def build_response_params(
    reasoning_effort: str | None,
    verbosity: str | None,
    enable_search_grounding: bool,
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text: dict[str, Any] = {
        "format": build_text_format(response_mime_type, response_schema),
    }
    if verbosity is not None:
        text["verbosity"] = verbosity
    params: dict[str, Any] = {"text": text}
    if reasoning_effort is not None:
        params["reasoning"] = {"effort": reasoning_effort}
    if tools:
        params["tools"] = tools.copy()
    if enable_search_grounding:
        params["tools"] = [*params.get("tools", []), {"type": "web_search"}]
    return params


def tool_call_from_response_event(event: object) -> TutorialToolCall | None:
    if getattr(event, "type", "") != "response.output_item.done":
        return None

    item = getattr(event, "item", None)
    if getattr(item, "type", "") != "function_call":
        return None

    name = getattr(item, "name", "")
    arguments = getattr(item, "arguments", "")
    if not name:
        return None
    return TutorialToolCall(name=name, arguments=arguments)


def stream_event_from_response_event(event: object) -> LLMStreamEvent | None:
    if getattr(event, "type", "") == "response.output_text.delta":
        delta = getattr(event, "delta", None)
        if delta:
            return LLMTextDelta(text=delta)

    tool_call = tool_call_from_response_event(event)
    if tool_call is not None:
        return LLMToolCallEvent(tool_call=tool_call)

    web_search = web_search_event_from_response_event(event)
    if web_search is not None:
        return web_search

    return None


def web_search_event_from_response_event(
    event: object,
) -> LLMWebSearchStarted | LLMWebSearchCompleted | None:
    """Detect lifecycle events for OpenAI's native web_search tool.

    The Responses API surfaces a web_search_call as a regular output item:
      - ``response.output_item.added`` fires when the model starts a
        search. The item carries ``type='web_search_call'`` and an
        ``action`` whose ``query`` may already be populated.
      - ``response.output_item.done`` fires when the search finishes.
        The final item shape carries ``action.query`` and a status.

    We map these to Started/Completed. The Completed event's
    ``elapsed_ms`` field is filled in by the streaming loop, which is
    the only place we know when the matching Started actually fired.
    """
    event_type = getattr(event, "type", "")
    if event_type not in {
        "response.output_item.added",
        "response.output_item.done",
    }:
        return None
    item = getattr(event, "item", None)
    if getattr(item, "type", "") != "web_search_call":
        return None
    query = _web_search_query_from_item(item)
    if event_type == "response.output_item.added":
        return LLMWebSearchStarted(query=query)
    return LLMWebSearchCompleted(query=query)


def _web_search_query_from_item(item: object) -> str:
    action = getattr(item, "action", None)
    if action is None:
        return ""
    query = getattr(action, "query", None)
    if isinstance(query, str):
        return query
    if isinstance(action, dict):
        value = action.get("query")
        if isinstance(value, str):
            return value
    return ""


def build_text_format(
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    if response_mime_type == "application/json" and response_schema is not None:
        return {
            "type": "json_schema",
            "name": "response",
            "schema": build_strict_json_schema(response_schema),
            "strict": True,
        }
    if response_mime_type == "application/json":
        return {"type": "json_object"}
    return {"type": "text"}


def build_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return add_strict_object_constraints(schema)


def add_strict_object_constraints(value: Any) -> Any:
    if isinstance(value, dict):
        strict_value: dict[str, Any] = {}
        for key, child in value.items():
            if key == "discriminator":
                continue
            if key == "oneOf":
                strict_value["anyOf"] = add_strict_object_constraints(child)
                continue
            strict_value[key] = add_strict_object_constraints(child)

        properties = strict_value.get("properties")
        if isinstance(properties, dict):
            strict_value["required"] = list(properties.keys())
            strict_value["additionalProperties"] = False
        elif strict_value.get("type") == "object":
            strict_value["additionalProperties"] = False
        return strict_value

    if isinstance(value, list):
        return [add_strict_object_constraints(item) for item in value]

    return value
