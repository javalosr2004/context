"""SQLite + filesystem storage for recording bundles.

Schema is intentionally narrow. Read the SQL definitions below before adding
columns — every column adds a migration we have to maintain.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .schemas import EventIn, ManifestIn, SUPPORTED_SCHEMA_VERSIONS


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recordings (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  goal TEXT NOT NULL,
  total_events INTEGER NOT NULL,
  completed INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS enrichment_jobs (
  id TEXT PRIMARY KEY,
  recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  event_id TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  distance_px REAL,
  verified INTEGER,
  sequence INTEGER NOT NULL,
  started_at INTEGER,
  finished_at INTEGER
);

CREATE INDEX IF NOT EXISTS ix_jobs_recording_seq
  ON enrichment_jobs(recording_id, sequence);
"""


@dataclass
class RecordingRow:
    id: str
    status: str
    goal: str
    total_events: int
    completed: int
    failed: int
    created_at: int
    updated_at: int


class BundleValidationError(Exception):
    pass


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.bundles_dir = self.data_dir / "bundles"
        self.db_path = self.data_dir / "recordings.db"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.executescript(SCHEMA_SQL)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        cx = sqlite3.connect(self.db_path, isolation_level=None, timeout=10.0)
        cx.execute("PRAGMA foreign_keys = ON")
        cx.execute("PRAGMA journal_mode = WAL")
        cx.row_factory = sqlite3.Row
        try:
            yield cx
        finally:
            cx.close()

    # ---- Bundle ingestion ------------------------------------------------

    def ingest_zip(self, zip_bytes: bytes) -> RecordingRow:
        """Unpack a bundle zip, validate manifest+events, register rows.

        Raises BundleValidationError on any structural problem. On success the
        recording is in `pending` and one `enrichment_jobs` row exists per event.
        """
        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            top = _common_prefix(names)
            try:
                manifest_data = zf.read(f"{top}manifest.json")
                events_data = zf.read(f"{top}events.jsonl")
            except KeyError as e:
                raise BundleValidationError(f"missing required file: {e}") from e
            try:
                manifest = ManifestIn.model_validate_json(manifest_data)
            except Exception as e:
                raise BundleValidationError(f"manifest invalid: {e}") from e
            if manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
                raise BundleValidationError(
                    f"unsupported schema_version={manifest.schema_version}"
                )

            events = list(_parse_events(events_data))

            dest = self.bundles_dir / manifest.recording_id
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            for n in names:
                if not n.startswith(top) or n.endswith("/"):
                    continue
                rel = n[len(top):]
                if not rel:
                    continue
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(n) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        now = int(time.time() * 1000)
        with self._conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO recordings
                   (id, status, goal, total_events, completed, failed, created_at, updated_at)
                   VALUES (?, 'pending', ?, ?, 0, 0, ?, ?)""",
                (manifest.recording_id, manifest.goal.text, len(events), now, now),
            )
            cx.execute(
                "DELETE FROM enrichment_jobs WHERE recording_id = ?",
                (manifest.recording_id,),
            )
            cx.executemany(
                """INSERT INTO enrichment_jobs
                   (id, recording_id, event_id, status, sequence)
                   VALUES (?, ?, ?, 'pending', ?)""",
                [
                    (f"{manifest.recording_id}:{i}", manifest.recording_id, ev.id, i)
                    for i, ev in enumerate(events)
                ],
            )
        return self.get_recording(manifest.recording_id)  # type: ignore[return-value]

    # ---- Queries ---------------------------------------------------------

    def get_recording(self, recording_id: str) -> Optional[RecordingRow]:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        if row is None:
            return None
        return RecordingRow(**dict(row))

    def list_recordings(self) -> list[RecordingRow]:
        with self._conn() as cx:
            rows = cx.execute(
                "SELECT * FROM recordings ORDER BY created_at DESC"
            ).fetchall()
        return [RecordingRow(**dict(r)) for r in rows]

    def bundle_dir(self, recording_id: str) -> Path:
        return self.bundles_dir / recording_id

    def events_path(self, recording_id: str) -> Path:
        return self.bundle_dir(recording_id) / "events.jsonl"

    def enriched_path(self, recording_id: str) -> Path:
        return self.bundle_dir(recording_id) / "events.enriched.jsonl"

    # ---- Worker-facing -------------------------------------------------

    def next_pending_recording(self) -> Optional[str]:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT id FROM recordings WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def mark_recording(self, recording_id: str, status: str) -> None:
        now = int(time.time() * 1000)
        with self._conn() as cx:
            cx.execute(
                "UPDATE recordings SET status=?, updated_at=? WHERE id=?",
                (status, now, recording_id),
            )

    def pending_jobs(self, recording_id: str) -> list[sqlite3.Row]:
        with self._conn() as cx:
            return cx.execute(
                "SELECT * FROM enrichment_jobs WHERE recording_id = ? ORDER BY sequence ASC",
                (recording_id,),
            ).fetchall()

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        error: Optional[str] = None,
        distance_px: Optional[float] = None,
        verified: Optional[bool] = None,
    ) -> None:
        now = int(time.time() * 1000)
        with self._conn() as cx:
            cx.execute(
                """UPDATE enrichment_jobs
                   SET status=?, error=?, distance_px=?, verified=?,
                       finished_at=CASE WHEN ?='done' OR ?='failed' THEN ? ELSE finished_at END
                   WHERE id=?""",
                (
                    status,
                    error,
                    distance_px,
                    None if verified is None else (1 if verified else 0),
                    status, status, now,
                    job_id,
                ),
            )

    def bump_counts(self, recording_id: str, completed_delta: int = 0, failed_delta: int = 0) -> None:
        now = int(time.time() * 1000)
        with self._conn() as cx:
            cx.execute(
                "UPDATE recordings SET completed = completed + ?, failed = failed + ?, updated_at = ? WHERE id = ?",
                (completed_delta, failed_delta, now, recording_id),
            )


def _common_prefix(names: Iterable[str]) -> str:
    seen = list(names)
    if not seen:
        return ""
    first = seen[0]
    if "/" not in first:
        return ""
    candidate = first.split("/", 1)[0] + "/"
    if all(n.startswith(candidate) for n in seen):
        return candidate
    return ""


def _parse_events(blob: bytes) -> Iterator[EventIn]:
    for i, line in enumerate(blob.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            yield EventIn.model_validate_json(line)
        except Exception as e:
            raise BundleValidationError(f"events.jsonl line {i + 1} invalid: {e}") from e


def storage_from_env() -> Storage:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    return Storage(data_dir)
