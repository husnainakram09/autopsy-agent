from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator


EVENT_NAMES = {
    "plan_update": "step_started",
    "tool_call": "tool_call",
    "tool_summary": "tool_result_summary",
    "hypothesis_change": "hypothesis_update",
    "report_submitted": "report_ready",
}


@dataclass(frozen=True)
class RunEvent:
    id: int
    event: str
    data: dict[str, Any]


class _RunChannel:
    def __init__(self) -> None:
        self.next_id = 1
        self.history: deque[RunEvent] = deque(maxlen=500)
        self.subscribers: set[asyncio.Queue[RunEvent]] = set()


class RunEventHub:
    """In-memory per-run event queues with bounded replay history."""

    def __init__(self) -> None:
        self._channels: dict[int, _RunChannel] = {}
        self._lock = asyncio.Lock()

    async def publish(self, run_id: int, event: str, data: dict[str, Any]) -> RunEvent:
        async with self._lock:
            channel = self._channels.setdefault(run_id, _RunChannel())
            item = RunEvent(
                id=channel.next_id,
                event=EVENT_NAMES.get(event, event),
                data=data,
            )
            channel.next_id += 1
            channel.history.append(item)
            for queue in tuple(channel.subscribers):
                queue.put_nowait(item)
            return item

    async def subscribe(self, run_id: int, after_id: int = 0) -> AsyncIterator[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        async with self._lock:
            channel = self._channels.setdefault(run_id, _RunChannel())
            replay = [item for item in channel.history if item.id > after_id]
            channel.subscribers.add(queue)
        try:
            for item in replay:
                yield item
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                channel = self._channels.get(run_id)
                if channel is not None:
                    channel.subscribers.discard(queue)


run_event_hub = RunEventHub()

