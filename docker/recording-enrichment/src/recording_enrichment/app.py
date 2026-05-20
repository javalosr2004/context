from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from .storage import BundleValidationError, RecordingRow, Storage, storage_from_env


def create_app(storage: Storage | None = None) -> FastAPI:
    app = FastAPI(title="recording-enrichment", version="0.1.0")
    state_storage = storage or storage_from_env()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/recordings", status_code=202)
    async def upload_recording(bundle: UploadFile = File(...)) -> dict:
        zip_bytes = await bundle.read()
        try:
            row = state_storage.ingest_zip(zip_bytes)
        except BundleValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
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
