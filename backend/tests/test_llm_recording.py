"""Tests for RecordingLLM: transparent capture of every LLM round-trip."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.llm import (
    LLMRequest,
    LLMStreamEvent,
    LLMTextDelta,
    LLMToolCallEvent,
)
from backend.llm_recording import LLMCallRecord, RecordingLLM
from backend.tutorial_tools import TutorialToolCall


def _req(system: str = "sys", user: str = "user") -> LLMRequest:
    return LLMRequest(system_prompt=system, user_text=user, images=[])


class _FakeLLM:
    model_name = "fake-1"

    def __init__(
        self,
        text: str = "",
        tool_calls: list[TutorialToolCall] | None = None,
        raise_in: str | None = None,
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls or []
        self.raise_in = raise_in

    def complete_text(self, request: LLMRequest) -> str:
        if self.raise_in == "complete_text":
            raise RuntimeError("boom")
        return self.text

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        if self.raise_in == "stream_text":
            raise RuntimeError("boom")
        for chunk in self.text.split("|"):
            yield chunk

    def stream_tutorial_tool_calls(
        self, request: LLMRequest
    ) -> Iterator[TutorialToolCall]:
        for call in self.tool_calls:
            yield call

    def stream_tutorial_events(
        self, request: LLMRequest
    ) -> Iterator[LLMStreamEvent]:
        for chunk in self.text.split("|"):
            if chunk:
                yield LLMTextDelta(text=chunk)
        for call in self.tool_calls:
            yield LLMToolCallEvent(tool_call=call)


def test_complete_text_records_prompt_and_response() -> None:
    captured: list[LLMCallRecord] = []
    rec = RecordingLLM(
        _FakeLLM(text="hello world"), agent="verifier", sink=captured.append
    )
    out = rec.complete_text(_req(system="S", user="U"))
    assert out == "hello world"
    assert len(captured) == 1
    r = captured[0]
    assert r.agent == "verifier"
    assert r.model == "fake-1"
    assert r.method == "complete_text"
    assert r.prompt_system == "S"
    assert r.prompt_user == "U"
    assert r.response_text == "hello world"
    assert r.ok is True
    assert r.elapsed_ms >= 0


def test_complete_text_records_exception_and_reraises() -> None:
    captured: list[LLMCallRecord] = []
    rec = RecordingLLM(
        _FakeLLM(raise_in="complete_text"),
        agent="planner",
        sink=captured.append,
    )
    with pytest.raises(RuntimeError, match="boom"):
        rec.complete_text(_req())
    assert captured and captured[0].ok is False
    assert "boom" in (captured[0].error or "")


def test_stream_text_accumulates_chunks() -> None:
    captured: list[LLMCallRecord] = []
    rec = RecordingLLM(
        _FakeLLM(text="a|b|c"), agent="planner", sink=captured.append
    )
    out = list(rec.stream_text(_req()))
    assert out == ["a", "b", "c"]
    assert captured[0].response_text == "abc"
    assert captured[0].method == "stream_text"


def test_stream_tutorial_tool_calls_captures_each_call() -> None:
    captured: list[LLMCallRecord] = []
    calls = [
        TutorialToolCall(name="tutorial_update_plan", arguments="{}"),
        TutorialToolCall(name="tutorial_request_screen", arguments="{}"),
    ]
    rec = RecordingLLM(
        _FakeLLM(tool_calls=calls), agent="planner", sink=captured.append
    )
    yielded = list(rec.stream_tutorial_tool_calls(_req()))
    assert yielded == calls
    assert [c.name for c in captured[0].tool_calls] == [
        "tutorial_update_plan",
        "tutorial_request_screen",
    ]


def test_stream_tutorial_events_captures_text_and_tool_calls() -> None:
    captured: list[LLMCallRecord] = []
    rec = RecordingLLM(
        _FakeLLM(
            text="hello|world",
            tool_calls=[TutorialToolCall(name="tutorial_update_plan", arguments="{}")],
        ),
        agent="planner",
        sink=captured.append,
    )
    events = list(rec.stream_tutorial_events(_req()))
    assert any(isinstance(e, LLMTextDelta) for e in events)
    assert any(isinstance(e, LLMToolCallEvent) for e in events)
    assert captured[0].response_text == "helloworld"
    assert captured[0].tool_calls[0].name == "tutorial_update_plan"


def test_sink_failure_does_not_break_caller() -> None:
    def bad_sink(_r: LLMCallRecord) -> None:
        raise RuntimeError("sink broken")

    rec = RecordingLLM(_FakeLLM(text="ok"), agent="planner", sink=bad_sink)
    # Must not raise — eval logging is best-effort.
    assert rec.complete_text(_req()) == "ok"


def test_image_count_is_recorded_not_image_bytes() -> None:
    from backend.images import UploadedImage

    captured: list[LLMCallRecord] = []
    rec = RecordingLLM(_FakeLLM(text="ok"), agent="verifier", sink=captured.append)
    req = LLMRequest(
        system_prompt="s",
        user_text="u",
        images=[
            UploadedImage(data=b"a" * 1024, mime_type="image/png", filename="a.png"),
            UploadedImage(data=b"b" * 1024, mime_type="image/png", filename="b.png"),
        ],
    )
    rec.complete_text(req)
    r = captured[0]
    assert r.image_count == 2
    # Make sure raw bytes never landed in the record.
    assert "aaaa" not in r.prompt_user
