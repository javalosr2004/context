from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse

from .event_bus import EventBus
from .storage import BundleValidationError, RecordingRow, Storage, storage_from_env
from .worker import EnrichmentWorker


logger = logging.getLogger(__name__)


def create_app(storage: Storage | None = None, describer=None) -> FastAPI:
    app = FastAPI(title="recording-enrichment", version="0.1.0")
    state_storage = storage or storage_from_env()
    bus = EventBus()
    worker: Optional[EnrichmentWorker] = None

    def on_worker_event(recording_id: str, kind: str, payload: dict) -> None:
        bus.publish(recording_id, kind, payload)

    @app.on_event("startup")
    async def _start_worker() -> None:
        nonlocal worker
        if os.environ.get("WORKER_ENABLED", "1") == "0":
            return
        chosen_describer = describer
        if chosen_describer is None and (
            os.environ.get("HAI_API_KEY") or os.environ.get("HOLO_API_KEY")
        ):
            from .holo_describe import HoloDescriber
            chosen_describer = HoloDescriber()
        worker = EnrichmentWorker(state_storage, chosen_describer, on_event=on_worker_event)
        worker.start()

    @app.on_event("shutdown")
    async def _stop_worker() -> None:
        if worker is not None:
            with contextlib.suppress(Exception):
                await worker.stop()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/recordings", status_code=202)
    async def upload_recording(bundle: UploadFile = File(...)) -> dict:
        zip_bytes = await bundle.read()
        logger.info(
            "upload_recording received | filename=%s content_type=%s bytes=%d",
            bundle.filename, bundle.content_type, len(zip_bytes),
        )
        try:
            row = state_storage.ingest_zip(zip_bytes)
        except BundleValidationError as e:
            logger.warning("upload_recording rejected | detail=%s", e)
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception:
            logger.exception("upload_recording crashed")
            raise
        logger.info(
            "upload_recording ok | recording_id=%s status=%s total_events=%d",
            row.id, row.status, row.total_events,
        )
        return {
            "recording_id": row.id,
            "status": row.status,
            "total_events": row.total_events,
        }

    @app.get("/recordings")
    def list_recordings() -> list[dict]:
        return [_row_to_dict(r) for r in state_storage.list_recordings()]

    @app.get("/recordings/{recording_id}")
    def get_recording(recording_id: str) -> dict:
        row = state_storage.get_recording(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        return _row_to_dict(row)

    @app.get("/recordings/{recording_id}/status")
    def get_status(recording_id: str) -> dict:
        row = state_storage.get_recording(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "status": row.status,
            "total": row.total_events,
            "completed": row.completed,
            "failed": row.failed,
        }

    @app.get("/recordings/{recording_id}/events/stream")
    async def stream_events(recording_id: str, request: Request) -> StreamingResponse:
        row = state_storage.get_recording(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        last_event_id_header = request.headers.get("last-event-id")
        last_event_id: Optional[int] = None
        if last_event_id_header is not None:
            try:
                last_event_id = int(last_event_id_header)
            except ValueError:
                last_event_id = None

        async def gen():
            try:
                # Push the current DB row as the first frame. Without this, a
                # client connecting while the recording is still "pending"
                # would receive nothing until the worker emits its first event
                # — which could be several seconds — and the UI would stay on
                # its initial guess. The synthetic frame has no sequence
                # number so it doesn't pollute Last-Event-ID resumption.
                snapshot_row = state_storage.get_recording(recording_id)
                if snapshot_row is not None:
                    snapshot = {
                        "status": snapshot_row.status,
                        "completed": snapshot_row.completed,
                        "failed": snapshot_row.failed,
                        "total": snapshot_row.total_events,
                        "snapshot": True,
                    }
                    yield f"event: progress\ndata: {json.dumps(snapshot)}\n\n"

                async for event in bus.subscribe(recording_id, last_event_id=last_event_id):
                    if await request.is_disconnected():
                        break
                    line = f"id: {event.sequence}\nevent: {event.kind}\ndata: {json.dumps(event.payload)}\n\n"
                    yield line
                    if event.kind == "done":
                        break
            except asyncio.CancelledError:
                return

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/recordings/{recording_id}/reenrich", status_code=202)
    def reenrich(recording_id: str) -> dict:
        try:
            ok = state_storage.reset_for_reenrichment(recording_id)
        except BundleValidationError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        logger.info("reenrich queued | recording_id=%s", recording_id)
        return {"recording_id": recording_id, "status": "pending"}

    @app.get("/recordings/{recording_id}/events")
    def get_events(recording_id: str) -> FileResponse:
        row = state_storage.get_recording(recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if row.status != "ready":
            raise HTTPException(status_code=409, detail=f"not ready (status={row.status})")
        path = state_storage.enriched_path(recording_id)
        if not path.exists():
            raise HTTPException(status_code=500, detail="enriched file missing")
        return FileResponse(path, media_type="application/x-ndjson")

    return app


def _row_to_dict(row: RecordingRow) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "goal": row.goal,
        "total": row.total_events,
        "completed": row.completed,
        "failed": row.failed,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


app = create_app()
