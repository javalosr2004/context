from __future__ import annotations

import asyncio

import pytest

from recording_enrichment.event_bus import EventBus


@pytest.mark.asyncio
async def test_late_subscriber_replays_history():
    bus = EventBus()
    bus.publish("r1", "enriched", {"event_id": "e1"})
    bus.publish("r1", "enriched", {"event_id": "e2"})

    seen: list = []
    async def consume():
        async for ev in bus.subscribe("r1"):
            seen.append((ev.sequence, ev.kind))
            if len(seen) == 2:
                return
    await asyncio.wait_for(consume(), timeout=1.0)
    assert seen == [(0, "enriched"), (1, "enriched")]


@pytest.mark.asyncio
async def test_last_event_id_skips_replay():
    bus = EventBus()
    bus.publish("r1", "enriched", {})  # seq 0
    bus.publish("r1", "enriched", {})  # seq 1

    seen: list = []
    async def consume():
        async for ev in bus.subscribe("r1", last_event_id=0):
            seen.append(ev.sequence)
            if seen == [1]:
                return
    await asyncio.wait_for(consume(), timeout=1.0)
    assert seen == [1]


@pytest.mark.asyncio
async def test_done_terminates_stream():
    bus = EventBus()
    async def producer():
        await asyncio.sleep(0.02)
        bus.publish("r1", "progress", {"completed": 1, "total": 2})
        bus.publish("r1", "done", {"status": "ready"})

    async def consume():
        kinds = []
        async for ev in bus.subscribe("r1"):
            kinds.append(ev.kind)
            if ev.kind == "done":
                return kinds
        return kinds

    consumer_task = asyncio.create_task(consume())
    await producer()
    kinds = await asyncio.wait_for(consumer_task, timeout=1.0)
    assert "done" in kinds


@pytest.mark.asyncio
async def test_heartbeat_emits_when_idle():
    bus = EventBus()
    seen: list = []
    async def consume():
        async for ev in bus.subscribe("r1", heartbeat_s=0.05):
            seen.append(ev.payload.get("heartbeat", False))
            if len(seen) >= 2:
                return
    await asyncio.wait_for(consume(), timeout=1.0)
    assert all(seen)
