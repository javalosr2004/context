from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from recording_enrichment.storage import BundleValidationError, Storage


def _build_zip(manifest: dict, events: list[dict], top: str = "recording-x/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{top}manifest.json", json.dumps(manifest))
        zf.writestr(f"{top}events.jsonl", "\n".join(json.dumps(e) for e in events))
        zf.writestr(f"{top}frames/abc.jpg", b"\x00")
    return buf.getvalue()


def _manifest(rec_id: str = "rec-1", schema_version: int = 1) -> dict:
    return {
        "recording_id": rec_id,
        "schema_version": schema_version,
        "started_at_ms": 1,
        "ended_at_ms": 2,
        "display": {"x": 0, "y": 0, "width": 100, "height": 50, "scale_factor": 2.0},
        "goal": {"text": "test goal", "entered_at_ms": 0},
        "app_version": "0.1.0",
        "aborted": False,
    }


def _event(event_id: str = "evt-1") -> dict:
    return {
        "id": event_id,
        "timestamp_ms": 100,
        "kind": "click",
        "cursor": {"x": 1, "y": 2},
        "button": "left",
        "frame_id": "abc",
        "target_crop_path": "crops/evt_target.jpg",
        "context_crop_path": "crops/evt_context.jpg",
    }


def test_ingest_zip_registers_recording_and_jobs(tmp_path: Path):
    s = Storage(tmp_path)
    zip_bytes = _build_zip(_manifest(), [_event("e1"), _event("e2")])
    row = s.ingest_zip(zip_bytes)
    assert row.id == "rec-1"
    assert row.status == "pending"
    assert row.total_events == 2

    fetched = s.get_recording("rec-1")
    assert fetched is not None and fetched.total_events == 2

    jobs = s.pending_jobs("rec-1")
    assert [j["sequence"] for j in jobs] == [0, 1]
    assert {j["event_id"] for j in jobs} == {"e1", "e2"}


def test_ingest_zip_rejects_unsupported_schema(tmp_path: Path):
    s = Storage(tmp_path)
    with pytest.raises(BundleValidationError):
        s.ingest_zip(_build_zip(_manifest(schema_version=99), [_event()]))


def test_ingest_zip_rejects_missing_manifest(tmp_path: Path):
    s = Storage(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("recording-x/events.jsonl", "")
    with pytest.raises(BundleValidationError):
        s.ingest_zip(buf.getvalue())


def test_ingest_zip_unpacks_files_to_bundle_dir(tmp_path: Path):
    s = Storage(tmp_path)
    s.ingest_zip(_build_zip(_manifest(), [_event()]))
    bundle = s.bundle_dir("rec-1")
    assert (bundle / "manifest.json").exists()
    assert (bundle / "events.jsonl").exists()
    assert (bundle / "frames/abc.jpg").exists()


def test_re_upload_creates_idempotent_state(tmp_path: Path):
    s = Storage(tmp_path)
    s.ingest_zip(_build_zip(_manifest(), [_event("e1"), _event("e2")]))
    # Re-ingest with different event count — old jobs should be replaced.
    s.ingest_zip(_build_zip(_manifest(), [_event("e3")]))
    jobs = s.pending_jobs("rec-1")
    assert len(jobs) == 1
    assert jobs[0]["event_id"] == "e3"


def test_next_pending_and_mark(tmp_path: Path):
    s = Storage(tmp_path)
    s.ingest_zip(_build_zip(_manifest("a"), [_event()]))
    s.ingest_zip(_build_zip(_manifest("b"), [_event()]))
    nxt = s.next_pending_recording()
    assert nxt in {"a", "b"}
    s.mark_recording(nxt, "ready")
    second = s.next_pending_recording()
    assert second != nxt
