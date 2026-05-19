"""Transparent LLM wrapper that captures every round-trip for evals.

Wrap a ``MultimodalLLM`` with ``RecordingLLM(inner, agent=..., sink=...)``
and the recorder is called once per logical call with an
``LLMCallRecord``. The sink is responsible for persistence (typically a
``SessionEventLog`` method that writes a sidecar JSON file plus an
``LLMCallEvent`` line).

Streaming methods accumulate text / tool calls as they are yielded and
fire the recorder when the stream is exhausted (or raises). The wrapper
preserves the original generator semantics — callers see no behavioral
difference.

Images are not inlined into the record: only ``image_count`` is kept.
Frame bytes already live in the session ``frames/`` dir keyed by hash.

Failure isolation: the recorder itself is wrapped in a try/except so a
broken sink can never take down a live tutorial. Same posture as the
event log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from backend.llm import (
    LLMRequest,
    LLMStreamEvent,
    LLMTextDelta,
    LLMToolCallEvent,
    MultimodalLLM,
)
from backend.tutorial_tools import TutorialToolCall


logger = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    call_id: str
    agent: str
    model: str
    method: str  # "complete_text" | "stream_text" | "stream_tutorial_tool_calls" | "stream_tutorial_events"
    elapsed_ms: float
    prompt_system: str
    prompt_user: str
    image_count: int
    response_text: str = ""
    tool_calls: list[TutorialToolCall] = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


LLMCallSink = Callable[[LLMCallRecord], None]


class RecordingLLM:
    """Transparent recorder around any ``MultimodalLLM``.

    Construct one wrapper per agent-role (``planner``, ``verifier``, ...)
    so the resulting records carry that label without the call site
    needing to know.
    """

    def __init__(
        self,
        inner: MultimodalLLM,
        *,
        agent: str,
        sink: LLMCallSink,
        model: str = "",
    ) -> None:
        self._inner = inner
        self._agent = agent
        self._sink = sink
        self._model = model or _infer_model_name(inner)

    # --- non-streaming ---

    def complete_text(self, request: LLMRequest) -> str:
        record = self._new_record("complete_text", request)
        started = time.perf_counter()
        try:
            out = self._inner.complete_text(request)
        except Exception as error:  # noqa: BLE001 — surface upstream, record locally
            record.elapsed_ms = _elapsed_ms(started)
            record.ok = False
            record.error = f"{type(error).__name__}: {error}"
            self._emit(record)
            raise
        record.elapsed_ms = _elapsed_ms(started)
        record.response_text = out
        self._emit(record)
        return out

    # --- streaming ---

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        record = self._new_record("stream_text", request)
        started = time.perf_counter()
        parts: list[str] = []
        try:
            for token in self._inner.stream_text(request):
                parts.append(token)
                yield token
        except Exception as error:  # noqa: BLE001
            record.elapsed_ms = _elapsed_ms(started)
            record.ok = False
            record.error = f"{type(error).__name__}: {error}"
            record.response_text = "".join(parts)
            self._emit(record)
            raise
        record.elapsed_ms = _elapsed_ms(started)
        record.response_text = "".join(parts)
        self._emit(record)

    def stream_tutorial_tool_calls(
        self, request: LLMRequest
    ) -> Iterator[TutorialToolCall]:
        record = self._new_record("stream_tutorial_tool_calls", request)
        started = time.perf_counter()
        try:
            for call in self._inner.stream_tutorial_tool_calls(request):
                record.tool_calls.append(call)
                yield call
        except Exception as error:  # noqa: BLE001
            record.elapsed_ms = _elapsed_ms(started)
            record.ok = False
            record.error = f"{type(error).__name__}: {error}"
            self._emit(record)
            raise
        record.elapsed_ms = _elapsed_ms(started)
        self._emit(record)

    def stream_tutorial_events(
        self, request: LLMRequest
    ) -> Iterator[LLMStreamEvent]:
        record = self._new_record("stream_tutorial_events", request)
        started = time.perf_counter()
        parts: list[str] = []
        try:
            for event in self._inner.stream_tutorial_events(request):
                if isinstance(event, LLMTextDelta):
                    parts.append(event.text)
                elif isinstance(event, LLMToolCallEvent):
                    record.tool_calls.append(event.tool_call)
                yield event
        except Exception as error:  # noqa: BLE001
            record.elapsed_ms = _elapsed_ms(started)
            record.ok = False
            record.error = f"{type(error).__name__}: {error}"
            record.response_text = "".join(parts)
            self._emit(record)
            raise
        record.elapsed_ms = _elapsed_ms(started)
        record.response_text = "".join(parts)
        self._emit(record)

    # --- internals ---

    def _new_record(self, method: str, request: LLMRequest) -> LLMCallRecord:
        return LLMCallRecord(
            call_id=uuid4().hex,
            agent=self._agent,
            model=self._model,
            method=method,
            elapsed_ms=0.0,
            prompt_system=request.system_prompt,
            prompt_user=request.user_text,
            image_count=len(request.images),
        )

    def _emit(self, record: LLMCallRecord) -> None:
        try:
            self._sink(record)
        except Exception:  # noqa: BLE001 — never break the LLM caller
            logger.exception(
                "[llm_recording] sink failed",
                extra={"agent": record.agent, "call_id": record.call_id},
            )


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


def _infer_model_name(inner: MultimodalLLM) -> str:
    """Best-effort model identifier. Providers expose ``model_name`` or
    ``model``; fall back to the class name so the record never carries
    an empty model field."""
    for attr in ("model_name", "model", "_model_name", "_model"):
        value = getattr(inner, attr, None)
        if isinstance(value, str) and value:
            return value
    return type(inner).__name__


def null_sink(_record: LLMCallRecord) -> None:
    """Default no-op sink used when no event log is wired."""
    return None
