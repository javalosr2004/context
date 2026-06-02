"""In-memory pub/sub for per-recording enrichment events.

Each subscriber gets its own queue. Recent events are kept in a small ring
buffer so that an SSE client reconnecting with `Last-Event-ID` can be caught
up without rereading from SQLite.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


logger = logging.getLogger(__name__)

REPLAY_BUFFER_SIZE = 256


@dataclass(frozen=True)
class BusEvent:
    sequence: int
    kind: str        # "enriched" | "progress" | "done"
    payload: dict


@dataclass
class _Channel:
    history: deque[BusEvent] = field(default_factory=lambda: deque(maxlen=REPLAY_BUFFER_SIZE))
    next_sequence: int = 0
    subscribers: list[asyncio.Queue] = field(default_factory=list)


class EventBus:
    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}
        self._lock = asyncio.Lock()

    def _channel(self, recording_id: str) -> _Channel:
        return self._channels.setdefault(recording_id, _Channel())

    def publish(self, recording_id: str, kind: str, payload: dict) -> BusEvent:
        ch = self._channel(recording_id)
        event = BusEvent(sequence=ch.next_sequence, kind=kind, payload=payload)
        ch.next_sequence += 1
        ch.history.append(event)
        for q in list(ch.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("subscriber_queue_full recording_id=%s", recording_id)
        return event

    async def subscribe(
        self,
        recording_id: str,
        *,
        last_event_id: Optional[int] = None,
        heartbeat_s: float = 2.0,
    ) -> AsyncIterator[BusEvent]:
        ch = self._channel(recording_id)
        queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=1024)
        ch.subscribers.append(queue)
        try:
            # Replay missed history first.
            for past in ch.history:
                if last_event_id is None or past.sequence > last_event_id:
                    yield past
            done = False
            while not done:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_s)
                except asyncio.TimeoutError:
                    # Yield a synthetic heartbeat (no sequence bump).
                    yield BusEvent(
                        sequence=ch.next_sequence,
                        kind="progress",
                        payload={"heartbeat": True, "ts": int(time.time() * 1000)},
                    )
                    continue
                yield event
                if event.kind == "done":
                    done = True
        finally:
            try:
                ch.subscribers.remove(queue)
            except ValueError:
                pass
