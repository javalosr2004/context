"""Append-only JSONL log of every event flowing through a session.

Layout on disk:

    {root}/{session_id}/events.jsonl   # one event per line, both directions
    {root}/{session_id}/frames/        # screenshots referenced by hash

Default root is ``~/.context/sessions``; override with ``CONTEXT_SESSIONS_DIR``.

Both server-emitted events (``ServerSessionEvent``) and decoded client events
(``ClientSessionEvent``) are written through the same sink so the file is the
authoritative chronological record. Each line is wrapped with a ``direction``
discriminator so an extractor can replay either side.

Inline ``ScreenSnapshot`` payloads are extracted at write time: the raw bytes
land in ``frames/<sha256>.<ext>`` and the JSONL line carries a stable
``{frame_hash, frame_ref, byte_size}`` reference instead. This keeps the
JSONL small enough to grep and gives every screen a content-addressed handle
that ``UserStepAnnotationEvent.frame_hash`` and the eval extractor can join
against.

The sink is intentionally fire-and-forget at the I/O layer: a write failure
logs but does not block the session. We never want eval logging to take down
a live tutorial.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def default_log_root() -> Path:
    override = os.environ.get("CONTEXT_SESSIONS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".context" / "sessions"


_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def _ext_for_mime(mime_type: str) -> str:
    return _MIME_TO_EXT.get(mime_type, ".bin")


_SCREEN_BEARING_EVENTS: dict[str, tuple[str, ...]] = {
    # event_type -> field name(s) carrying a ScreenSnapshot
    "user_screen": ("screen",),
    "user_confirmation": ("screen",),
    "user_message": ("uploaded_images",),
}


class SessionEventLog:
    """Per-session JSONL writer. Cheap to construct; opens the file lazily.

    Also doubles as the frame store: ScreenSnapshot payloads in known
    client events are content-addressed into ``frames/`` and replaced with
    a reference on the wire.
    """

    def __init__(self, session_id: str, root: Path | None = None) -> None:
        self._session_id = session_id
        self._dir = (root or default_log_root()) / session_id
        self._path = self._dir / "events.jsonl"
        self._frames_dir = self._dir / "frames"
        self._ready = False
        # Serializes JSONL appends across the asyncio loop + worker threads
        # the LLM recorder runs in. Frame/payload writes are content-addressed
        # so they don't need the same protection.
        self._write_lock = threading.Lock()

    @property
    def session_dir(self) -> Path:
        return self._dir

    @property
    def events_path(self) -> Path:
        return self._path

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir

    @property
    def llm_calls_dir(self) -> Path:
        return self._dir / "llm_calls"

    def _ensure_dir(self) -> None:
        if self._ready:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._frames_dir.mkdir(exist_ok=True)
        (self._dir / "llm_calls").mkdir(exist_ok=True)
        self._ready = True

    def write(
        self,
        direction: Literal["client", "server"],
        event: BaseModel | dict[str, Any],
    ) -> None:
        try:
            self._ensure_dir()
            payload = event.model_dump(mode="json") if isinstance(event, BaseModel) else dict(event)
            payload = self._substitute_screens(payload)
            line = json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "direction": direction,
                    "event": payload,
                },
                ensure_ascii=False,
            )
            with self._write_lock, self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            logger.exception(
                "Failed to append session event",
                extra={"session_id": self._session_id, "direction": direction},
            )

    # -------- frame persistence --------

    def _substitute_screens(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Replace inline ScreenSnapshot.data_base64 with a frame reference.

        Mutates the payload dict in place and returns it. Unknown event
        types pass through unchanged. Decode errors fall back to the
        original snapshot so a bad frame never blocks event logging.
        """
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            return payload
        fields = _SCREEN_BEARING_EVENTS.get(event_type)
        if not fields:
            return payload
        for field in fields:
            value = payload.get(field)
            if value is None:
                continue
            if isinstance(value, list):
                payload[field] = [self._persist_snapshot(item) for item in value]
            elif isinstance(value, dict):
                payload[field] = self._persist_snapshot(value)
        return payload

    def _persist_snapshot(self, snapshot: Any) -> Any:
        if not isinstance(snapshot, dict):
            return snapshot
        data_b64 = snapshot.get("data_base64")
        mime_type = snapshot.get("mime_type", "")
        if not isinstance(data_b64, str) or not data_b64:
            return snapshot
        try:
            raw = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError):
            logger.warning(
                "Failed to decode frame for persistence; keeping inline",
                extra={"session_id": self._session_id, "mime_type": mime_type},
            )
            return snapshot
        frame_hash = hashlib.sha256(raw).hexdigest()
        ext = _ext_for_mime(mime_type)
        rel_path = f"frames/{frame_hash}{ext}"
        abs_path = self._dir / rel_path
        try:
            if not abs_path.exists():
                abs_path.write_bytes(raw)
        except OSError:
            logger.exception(
                "Failed to write frame; keeping inline",
                extra={
                    "session_id": self._session_id,
                    "frame_hash": frame_hash,
                },
            )
            return snapshot
        return {
            "mime_type": mime_type,
            "frame_hash": frame_hash,
            "frame_ref": rel_path,
            "byte_size": len(raw),
        }

    # -------- llm call persistence --------

    def write_llm_call(self, record: Any) -> str:
        """Persist a ``LLMCallRecord`` and append a compact ``LLMCallEvent``.

        Returns the relative payload path so callers can correlate. Safe
        to call from worker threads; uses thread-local file appends.

        Imported lazily to avoid a circular import between session_event_log
        (low-level) and llm_recording (which imports llm.py).
        """
        from backend.llm_recording import LLMCallRecord  # local import
        from backend.tutorial_session_events import (
            LLMCallEvent,
            LLMToolCallSummary,
        )

        if not isinstance(record, LLMCallRecord):
            raise TypeError(
                f"write_llm_call expects LLMCallRecord, got {type(record).__name__}"
            )

        try:
            self._ensure_dir()
            rel_path = f"llm_calls/{record.call_id}.json"
            payload = {
                "call_id": record.call_id,
                "agent": record.agent,
                "model": record.model,
                "method": record.method,
                "elapsed_ms": record.elapsed_ms,
                "image_count": record.image_count,
                "prompt_system": record.prompt_system,
                "prompt_user": record.prompt_user,
                "response_text": record.response_text,
                "tool_calls": [
                    {"name": call.name, "arguments": call.arguments}
                    for call in record.tool_calls
                ],
                "ok": record.ok,
                "error": record.error,
                "extra": record.extra,
            }
            (self._dir / rel_path).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.exception(
                "Failed to persist llm call payload",
                extra={"session_id": self._session_id, "call_id": record.call_id},
            )
            rel_path = ""

        event = LLMCallEvent(
            call_id=record.call_id,
            agent=record.agent,
            model=record.model,
            elapsed_ms=record.elapsed_ms,
            image_count=record.image_count,
            prompt_system_chars=len(record.prompt_system),
            prompt_user_chars=len(record.prompt_user),
            response_text_chars=len(record.response_text),
            tool_calls=[
                LLMToolCallSummary(
                    name=call.name,
                    arguments_chars=len(call.arguments),
                )
                for call in record.tool_calls
            ],
            ok=record.ok,
            error=record.error,
            payload_ref=rel_path,
        )
        self.write("server", event)
        return rel_path
