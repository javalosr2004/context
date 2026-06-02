from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest

from recording_enrichment.holo_describe import Description
from recording_enrichment.holo_verify import VerifySettings, euclidean, verify_against_cursor
from recording_enrichment.storage import Storage
from recording_enrichment.worker import EnrichmentWorker


def test_euclidean_matches_geometry():
    assert euclidean((0, 0), (3, 4)) == 5


class StubLocator:
    def __init__(self, point):
        self.point = point
    def locate(self, frame_jpeg, target_phrase):
        return self.point


def test_verify_returns_none_when_locator_fails():
    v, d = verify_against_cursor(
        client=StubLocator(None),
        frame_jpeg=b"",
        target_phrase="x",
        cursor=(100, 100),
        max_distance_px=30,
    )
    assert v is None and d is None


def test_verify_true_when_within_threshold():
    v, d = verify_against_cursor(
        client=StubLocator((110, 105)),
        frame_jpeg=b"",
        target_phrase="x",
        cursor=(100, 100),
        max_distance_px=30,
    )
    assert v is True
    assert d == pytest.approx(11.1803, rel=1e-3)


def test_verify_false_when_far():
    v, d = verify_against_cursor(
        client=StubLocator((300, 300)),
        frame_jpeg=b"",
        target_phrase="x",
        cursor=(100, 100),
        max_distance_px=30,
    )
    assert v is False and d > 30


def _build_zip(rec_id: str, events: list[dict]) -> bytes:
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
                zf.writestr(f"{rec_id}/{ev['target_crop_path']}", b"\x00")
            if ev.get("context_crop_path"):
                zf.writestr(f"{rec_id}/{ev['context_crop_path']}", b"\x00")
            if ev.get("frame_id"):
                zf.writestr(f"{rec_id}/frames/{ev['frame_id']}.jpg", b"\x00")
    return buf.getvalue()


class StubDescriber:
    _model = "stub"
    def describe(self, target, context, goal):
        return Description(target_phrase="reply", kind="button", visible_text="Reply")


@pytest.mark.asyncio
async def test_worker_writes_verification_when_enabled(tmp_path: Path):
    s = Storage(tmp_path)
    event = {
        "id": "e1", "timestamp_ms": 0, "kind": "click",
        "cursor": {"x": 50, "y": 50},
        "button": "left", "frame_id": "f1",
        "target_crop_path": "crops/e1_target.jpg",
        "context_crop_path": "crops/e1_context.jpg",
    }
    s.ingest_zip(_build_zip("rv", [event]))
    settings = VerifySettings()
    settings.enabled = True
    settings.max_distance_px = 30
    w = EnrichmentWorker(
        s,
        describer=StubDescriber(),
        verifier=StubLocator((55, 50)),
        verify_settings=settings,
    )
    w.start()
    for _ in range(50):
        row = s.get_recording("rv")
        if row and row.status == "ready":
            break
        await asyncio.sleep(0.05)
    await w.stop()
    enriched = [json.loads(l) for l in s.enriched_path("rv").read_text().splitlines()]
    meta = enriched[0]["description_meta"]
    assert meta["verified"] is True
    assert meta["distance_px"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_worker_leaves_verified_null_when_disabled(tmp_path: Path):
    s = Storage(tmp_path)
    event = {
        "id": "e1", "timestamp_ms": 0, "kind": "click",
        "cursor": {"x": 50, "y": 50},
        "button": "left", "frame_id": "f1",
        "target_crop_path": "crops/e1_target.jpg",
        "context_crop_path": "crops/e1_context.jpg",
    }
    s.ingest_zip(_build_zip("rv2", [event]))
    w = EnrichmentWorker(s, describer=StubDescriber())
    w.start()
    for _ in range(50):
        row = s.get_recording("rv2")
        if row and row.status == "ready":
            break
        await asyncio.sleep(0.05)
    await w.stop()
    enriched = [json.loads(l) for l in s.enriched_path("rv2").read_text().splitlines()]
    meta = enriched[0]["description_meta"]
    assert meta["verified"] is None
    assert meta["distance_px"] is None
