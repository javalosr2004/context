"""Async worker that drains pending recordings through the Holo describer."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .holo_describe import Describer, Description, PROMPT_VERSION
from .holo_verify import GroundingClient, VerifySettings, verify_against_cursor
from .schemas import EventIn
from .storage import Storage


logger = logging.getLogger(__name__)


class WorkerSettings:
    def __init__(self) -> None:
        self.max_concurrency = int(os.environ.get("HOLO_MAX_CONCURRENCY", "1"))
        self.idle_sleep_s = float(os.environ.get("WORKER_IDLE_SLEEP_S", "1.0"))


class EnrichmentWorker:
    def __init__(
        self,
        storage: Storage,
        describer: Optional[Describer] = None,
        *,
        settings: Optional[WorkerSettings] = None,
        on_event: Optional[callable] = None,  # type: ignore[type-arg]
        verifier: Optional[GroundingClient] = None,
        verify_settings: Optional[VerifySettings] = None,
    ):
        self._storage = storage
        self._describer = describer
        self._settings = settings or WorkerSettings()
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._sem = asyncio.Semaphore(self._settings.max_concurrency)
        self._on_event = on_event  # called as (recording_id, "enriched"|"progress"|"done", payload)
        self._verifier = verifier
        self._verify_settings = verify_settings or VerifySettings()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="enrichment-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        logger.info(
            "worker_started max_concurrency=%s describer=%s",
            self._settings.max_concurrency,
            type(self._describer).__name__ if self._describer is not None else "None",
        )
        try:
            while not self._stop.is_set():
                recording_id = self._storage.next_pending_recording()
                if recording_id is None:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self._settings.idle_sleep_s)
                    except asyncio.TimeoutError:
                        pass
                    continue
                logger.info("worker_picked_up recording_id=%s", recording_id)
                try:
                    await self._enrich_recording(recording_id)
                except Exception:
                    logger.exception("worker_recording_failed recording_id=%s", recording_id)
                    self._storage.mark_recording(recording_id, "failed")
                    self._emit(recording_id, "done", {"status": "failed"})
        finally:
            logger.info("worker_stopped")

    async def _enrich_recording(self, recording_id: str) -> None:
        if self._describer is None:
            # No describer wired (dev mode). Mark ready immediately with empty enriched file.
            enriched = self._storage.enriched_path(recording_id)
            enriched.write_text("")
            self._storage.mark_recording(recording_id, "ready")
            self._emit(recording_id, "done", {"status": "ready"})
            return

        self._storage.mark_recording(recording_id, "enriching")
        self._emit_progress(recording_id)
        bundle = self._storage.bundle_dir(recording_id)
        events_path = bundle / "events.jsonl"
        partial = bundle / "events.enriched.jsonl.partial"
        final = self._storage.enriched_path(recording_id)
        manifest = json.loads((bundle / "manifest.json").read_text())
        goal = manifest["goal"]["text"]

        jobs = {j["event_id"]: j for j in self._storage.pending_jobs(recording_id)}

        partial.write_text("")
        with open(partial, "a", encoding="utf-8") as enriched_f:
            for line in events_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                event = EventIn.model_validate_json(line)
                job = jobs.get(event.id)
                async with self._sem:
                    enriched = await self._enrich_event(
                        recording_id=recording_id,
                        event=event,
                        bundle=bundle,
                        goal=goal,
                        job_id=job["id"] if job else None,
                    )
                enriched_f.write(json.dumps(enriched) + "\n")
                enriched_f.flush()

        partial.replace(final)
        self._storage.mark_recording(recording_id, "ready")
        self._emit(recording_id, "done", {"status": "ready"})

    async def _enrich_event(
        self,
        *,
        recording_id: str,
        event: EventIn,
        bundle: Path,
        goal: str,
        job_id: Optional[str],
    ) -> dict:
        target = _read_optional(bundle, event.target_crop_path)
        context = _read_optional(bundle, event.context_crop_path)
        base = event.model_dump(by_alias=False, mode="json")

        description: Optional[Description] = None
        error: Optional[str] = None
        started = int(time.time() * 1000)
        if target and context and self._describer is not None:
            try:
                description = await asyncio.to_thread(self._describer.describe, target, context, goal)
            except Exception as e:  # broad: per-event failure must not poison recording
                error = f"{type(e).__name__}: {e}"
                # Retry once with the same prompt as a small reliability cushion.
                try:
                    description = await asyncio.to_thread(self._describer.describe, target, context, goal)
                    error = None
                except Exception as e2:
                    error = f"{type(e2).__name__}: {e2}"
        else:
            error = "missing_crops_or_describer"

        if description is not None:
            verified: Optional[bool] = None
            distance_px: Optional[float] = None
            if self._verify_settings.enabled and self._verifier is not None and event.frame_id:
                frame_path = bundle / "frames" / f"{event.frame_id}.jpg"
                if frame_path.exists():
                    verified, distance_px = await asyncio.to_thread(
                        verify_against_cursor,
                        client=self._verifier,
                        frame_jpeg=frame_path.read_bytes(),
                        target_phrase=description.target_phrase,
                        cursor=(event.cursor.x, event.cursor.y),
                        max_distance_px=self._verify_settings.max_distance_px,
                    )
            base["description"] = description.model_dump()
            base["description_meta"] = {
                "model": getattr(self._describer, "_model", "unknown"),
                "prompt_version": PROMPT_VERSION,
                "generated_at_ms": int(time.time() * 1000),
                "verified": verified,
                "distance_px": distance_px,
            }
            if job_id:
                self._storage.update_job(job_id, status="done", verified=verified, distance_px=distance_px)
            self._storage.bump_counts(recording_id, completed_delta=1)
            self._emit_progress(recording_id)
            self._emit(
                recording_id,
                "enriched",
                {
                    "event_id": event.id,
                    "target_phrase": description.target_phrase,
                    "kind": description.kind,
                    "verified": verified,
                    "distance_px": distance_px,
                },
            )
        else:
            base["description"] = None
            base["description_meta"] = {
                "model": None,
                "prompt_version": PROMPT_VERSION,
                "generated_at_ms": int(time.time() * 1000),
                "verified": None,
                "distance_px": None,
                "error": error,
            }
            if job_id:
                self._storage.update_job(job_id, status="failed", error=error)
            self._storage.bump_counts(recording_id, failed_delta=1)
            self._emit_progress(recording_id)
        return base

    def _emit(self, recording_id: str, kind: str, payload: dict) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(recording_id, kind, payload)
        except Exception:
            logger.exception("on_event handler failed")

    def _emit_progress(self, recording_id: str) -> None:
        """Push the current DB row as a 'progress' frame so SSE clients see
        every status transition and the moving completed/failed counters."""
        row = self._storage.get_recording(recording_id)
        if row is None:
            return
        self._emit(
            recording_id,
            "progress",
            {
                "status": row.status,
                "completed": row.completed,
                "failed": row.failed,
                "total": row.total_events,
            },
        )


def _read_optional(bundle: Path, rel: Optional[str]) -> Optional[bytes]:
    if not rel:
        return None
    p = bundle / rel
    if not p.exists():
        return None
    return p.read_bytes()
