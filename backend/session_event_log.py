"""Append-only JSONL log of every event flowing through a session.

Layout on disk:

    {root}/{session_id}/events.jsonl   # one event per line, both directions
    {root}/{session_id}/frames/        # reserved for screenshots (future)

Default root is ``~/.context/sessions``; override with ``CONTEXT_SESSIONS_DIR``.

Both server-emitted events (``ServerSessionEvent``) and decoded client events
(``ClientSessionEvent``) are written through the same sink so the file is the
authoritative chronological record. Each line is wrapped with a ``direction``
discriminator so an extractor can replay either side.

The sink is intentionally fire-and-forget at the I/O layer: a write failure
logs but does not block the session. We never want eval logging to take down
a live tutorial.
"""

from __future__ import annotations

import json
import logging
import os
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


class SessionEventLog:
    """Per-session JSONL writer. Cheap to construct; opens the file lazily."""

    def __init__(self, session_id: str, root: Path | None = None) -> None:
        self._session_id = session_id
        self._dir = (root or default_log_root()) / session_id
        self._path = self._dir / "events.jsonl"
        self._ready = False

    @property
    def session_dir(self) -> Path:
        return self._dir

    @property
    def events_path(self) -> Path:
        return self._path

    def _ensure_dir(self) -> None:
        if self._ready:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "frames").mkdir(exist_ok=True)
        self._ready = True

    def write(
        self,
        direction: Literal["client", "server"],
        event: BaseModel | dict[str, Any],
    ) -> None:
        try:
            self._ensure_dir()
            payload = event.model_dump(mode="json") if isinstance(event, BaseModel) else event
            line = json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "direction": direction,
                    "event": payload,
                },
                ensure_ascii=False,
            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            logger.exception(
                "Failed to append session event",
                extra={"session_id": self._session_id, "direction": direction},
            )
