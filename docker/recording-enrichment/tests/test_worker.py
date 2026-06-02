from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest

from recording_enrichment.holo_describe import Description
from recording_enrichment.storage import Storage
from recording_enrichment.worker import EnrichmentWorker, WorkerSettings


def _build_zip(rec_id: str, events: list[dict], crop_bytes: bytes = b"\x00\x01") -> bytes:
    manifest = {
        "recording_id": rec_id,
        "schema_version": 1,
        "started_at_ms": 1,
        "ended_at_ms": 2,
        "display": {"x": 0, "y": 0, "width": 1, "height": 1, "scale_factor": 1.0},
        "goal": {"text": "demo goal", "entered_at_ms": 0},
        "app_version": "0.0.1",
        "aborted": False,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{rec_id}/manifest.json", json.dumps(manifest))
        zf.writestr(f"{rec_id}/events.jsonl", "\n".join(json.dumps(e) for e in events))
        for ev in events:
            if ev.get("target_crop_path"):
                zf.writestr(f"{rec_id}/{ev['target_crop_path']}", crop_bytes)
            if ev.get("context_crop_path"):
                zf.writestr(f"{rec_id}/{ev['context_crop_path']}", crop_bytes)
    return buf.getvalue()


def _event(event_id: str, with_crops: bool = True) -> dict:
    base = {
        "id": event_id,
        "timestamp_ms": 0,
        "kind": "click",
        "cursor": {"x": 0, "y": 0},
        "button": "left",
        "frame_id": "f1",
    }
    if with_crops:
        base["target_crop_path"] = f"crops/{event_id}_target.jpg"
        base["context_crop_path"] = f"crops/{event_id}_context.jpg"
    return base


class StubDescriber:
    def __init__(self, *, fail_on: set[str] | None = None):
        self._fail_on = fail_on or set()
        self._calls: list[tuple[bytes, bytes, str]] = []
        self._model = "stub-1"

    def describe(self, target_jpeg: bytes, context_jpeg: bytes, goal: str) -> Description:
        self._calls.append((target_jpeg, context_jpeg, goal))
        if len(self._calls) <= 0:
            pass
        # The recipe: if any target byte == 0xFF, fail. Otherwise succeed.
        if target_jpeg in self._fail_on:
            raise RuntimeError("boom")
        return Description(target_phrase="the 'Reply' button", kind="button", visible_text="Reply")


@pytest.mark.asyncio
async def test_worker_enriches_recording_to_ready(tmp_path: Path):
    s = Storage(tmp_path)
    s.ingest_zip(_build_zip("rec-1", [_event("e1"), _event("e2")]))
    emitted: list[tuple[str, str, dict]] = []
    w = EnrichmentWorker(
        s,
        describer=StubDescriber(),
        settings=WorkerSettings(),
        on_event=lambda rid, kind, payload: emitted.append((rid, kind, payload)),
    )
    w.start()
    # Wait until the recording transitions to ready.
    for _ in range(50):
        row = s.get_recording("rec-1")
        if row and row.status == "ready":
            break
        await asyncio.sleep(0.05)
    await w.stop()
    row = s.get_recording("rec-1")
    assert row is not None
    assert row.status == "ready"
    assert row.completed == 2
    assert row.failed == 0
    enriched_lines = [json.loads(l) for l in s.enriched_path("rec-1").read_text().splitlines()]
    assert len(enriched_lines) == 2
    assert enriched_lines[0]["description"]["target_phrase"] == "the 'Reply' button"
    assert enriched_lines[0]["description_meta"]["prompt_version"] == "describe-v2"
    assert any(k == "done" for _, k, _ in emitted)
    assert any(k == "enriched" for _, k, _ in emitted)


@pytest.mark.asyncio
async def test_worker_continues_past_event_failure(tmp_path: Path):
    s = Storage(tmp_path)
    # Build with one crop missing → forces failure path on that event.
    s.ingest_zip(_build_zip("rec-x", [_event("e1", with_crops=False), _event("e2")]))
    w = EnrichmentWorker(s, describer=StubDescriber())
    w.start()
    for _ in range(50):
        row = s.get_recording("rec-x")
        if row and row.status == "ready":
            break
        await asyncio.sleep(0.05)
    await w.stop()
    row = s.get_recording("rec-x")
    assert row is not None and row.status == "ready"
    assert row.failed == 1
    assert row.completed == 1
    enriched_lines = [json.loads(l) for l in s.enriched_path("rec-x").read_text().splitlines()]
    # First event lacks crops → description is null.
    assert enriched_lines[0]["description"] is None
    assert enriched_lines[1]["description"] is not None


@pytest.mark.asyncio
async def test_worker_dev_mode_no_describer_marks_ready_immediately(tmp_path: Path):
    s = Storage(tmp_path)
    s.ingest_zip(_build_zip("rec-d", [_event("e1")]))
    w = EnrichmentWorker(s, describer=None)
    w.start()
    for _ in range(50):
        row = s.get_recording("rec-d")
        if row and row.status == "ready":
            break
        await asyncio.sleep(0.05)
    await w.stop()
    row = s.get_recording("rec-d")
    assert row is not None and row.status == "ready"
