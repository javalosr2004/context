"""Tests for SessionEventLog: frame persistence + LLM call sink."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from pathlib import Path

import pytest

from backend.llm_recording import LLMCallRecord
from backend.session_event_log import SessionEventLog
from backend.tutorial_session_events import (
    InstructionVerifiedEvent,
    ScreenSnapshot,
    UserConfirmationEvent,
    UserMessageEvent,
    UserScreenEvent,
)
from backend.tutorial_tools import TutorialToolCall


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000005000101a0fbdb650000000049454e44ae426082"
)


def _snapshot(data: bytes = PNG_BYTES, mime: str = "image/png") -> ScreenSnapshot:
    return ScreenSnapshot(mime_type=mime, data_base64=base64.b64encode(data).decode())


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_user_screen_event_persists_frame(tmp_path: Path) -> None:
    log = SessionEventLog("s1", root=tmp_path)
    event = UserScreenEvent(type="user_screen", request_id="r1", screen=_snapshot())
    log.write("client", event)

    events = _read_events(log.events_path)
    assert len(events) == 1
    screen = events[0]["event"]["screen"]
    assert "data_base64" not in screen
    assert screen["frame_hash"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert screen["frame_ref"] == f"frames/{screen['frame_hash']}.png"
    assert screen["byte_size"] == len(PNG_BYTES)
    assert (log.session_dir / screen["frame_ref"]).read_bytes() == PNG_BYTES


def test_user_confirmation_persists_attached_screen(tmp_path: Path) -> None:
    log = SessionEventLog("s2", root=tmp_path)
    event = UserConfirmationEvent(
        type="user_confirmation",
        step_id="step_001",
        action_index=0,
        confirmed=True,
        screen=_snapshot(),
    )
    log.write("client", event)
    line = _read_events(log.events_path)[0]
    assert "frame_hash" in line["event"]["screen"]
    assert "data_base64" not in line["event"]["screen"]


def test_user_confirmation_without_screen_passes_through(tmp_path: Path) -> None:
    log = SessionEventLog("s3", root=tmp_path)
    event = UserConfirmationEvent(
        type="user_confirmation",
        step_id="step_001",
        action_index=0,
        confirmed=False,
    )
    log.write("client", event)
    line = _read_events(log.events_path)[0]
    assert line["event"]["screen"] is None


def test_user_message_persists_all_uploaded_images(tmp_path: Path) -> None:
    log = SessionEventLog("s4", root=tmp_path)
    other = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    event = UserMessageEvent(
        type="user_message",
        text="hello",
        uploaded_images=[_snapshot(), _snapshot(other)],
    )
    log.write("client", event)
    line = _read_events(log.events_path)[0]
    images = line["event"]["uploaded_images"]
    assert len(images) == 2
    assert images[0]["frame_hash"] != images[1]["frame_hash"]
    for img in images:
        assert "data_base64" not in img


def test_duplicate_frames_are_deduplicated_on_disk(tmp_path: Path) -> None:
    log = SessionEventLog("s5", root=tmp_path)
    snap = _snapshot()
    log.write("client", UserScreenEvent(type="user_screen", request_id="r1", screen=snap))
    log.write("client", UserScreenEvent(type="user_screen", request_id="r2", screen=snap))
    files = list((log.session_dir / "frames").iterdir())
    assert len(files) == 1


def test_unknown_event_passes_through_unchanged(tmp_path: Path) -> None:
    log = SessionEventLog("s6", root=tmp_path)
    event = InstructionVerifiedEvent(
        step_id="step_001",
        ok=False,
        reason="wrong screen",
        verdict="blocked",
        screen_summary="modal dialog blocking flow",
    )
    log.write("server", event)
    line = _read_events(log.events_path)[0]
    assert line["event"]["verdict"] == "blocked"
    assert line["event"]["screen_summary"] == "modal dialog blocking flow"


def test_corrupt_base64_falls_back_to_inline(tmp_path: Path) -> None:
    log = SessionEventLog("s7", root=tmp_path)
    # Bypass model validation by writing dict directly.
    log.write(
        "client",
        {
            "type": "user_screen",
            "request_id": "r1",
            "screen": {"mime_type": "image/png", "data_base64": "@@@not-base64@@@"},
        },
    )
    line = _read_events(log.events_path)[0]
    # Unchanged on decode failure — never blocks logging.
    assert line["event"]["screen"]["data_base64"] == "@@@not-base64@@@"


def test_write_llm_call_persists_payload_and_emits_event(tmp_path: Path) -> None:
    log = SessionEventLog("s8", root=tmp_path)
    record = LLMCallRecord(
        call_id="abc123",
        agent="verifier",
        model="gemini-2.0-flash",
        method="complete_text",
        elapsed_ms=42.0,
        prompt_system="you classify screens",
        prompt_user="instruction: click Sign in",
        image_count=1,
        response_text='{"verdict":"on_track"}',
        tool_calls=[TutorialToolCall(name="tutorial_update_plan", arguments='{"steps":[]}')],
    )
    rel = log.write_llm_call(record)
    assert rel == "llm_calls/abc123.json"

    payload = json.loads((log.session_dir / rel).read_text())
    assert payload["agent"] == "verifier"
    assert payload["prompt_system"] == "you classify screens"
    assert payload["response_text"] == '{"verdict":"on_track"}'
    assert payload["tool_calls"][0]["name"] == "tutorial_update_plan"

    events = _read_events(log.events_path)
    assert len(events) == 1
    line = events[0]["event"]
    assert line["type"] == "llm_call"
    assert line["call_id"] == "abc123"
    assert line["agent"] == "verifier"
    assert line["payload_ref"] == rel
    assert line["prompt_system_chars"] == len("you classify screens")
    assert line["response_text_chars"] == len('{"verdict":"on_track"}')
    assert line["tool_calls"][0]["name"] == "tutorial_update_plan"


def test_write_llm_call_rejects_non_record(tmp_path: Path) -> None:
    log = SessionEventLog("s9", root=tmp_path)
    with pytest.raises(TypeError):
        log.write_llm_call({"call_id": "x"})


def test_concurrent_writes_do_not_interleave(tmp_path: Path) -> None:
    log = SessionEventLog("s10", root=tmp_path)

    def worker(idx: int) -> None:
        for _ in range(20):
            log.write_llm_call(
                LLMCallRecord(
                    call_id=f"{idx}-{_}",
                    agent="planner",
                    model="m",
                    method="complete_text",
                    elapsed_ms=1.0,
                    prompt_system="s" * 100,
                    prompt_user="u" * 100,
                    image_count=0,
                    response_text="r" * 100,
                )
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every line must be a complete JSON object — interleaving would corrupt parsing.
    lines = log.events_path.read_text().splitlines()
    assert len(lines) == 4 * 20
    for line in lines:
        json.loads(line)
