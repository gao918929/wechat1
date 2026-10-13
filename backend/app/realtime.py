"""WebSocket hub for real-time multi-person sync (one person's edit reaches everyone)."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("mealagent.realtime")


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def join(self, group_id: int, ws: WebSocket) -> None:
        self.rooms.setdefault(group_id, set()).add(ws)

    def leave(self, group_id: int, ws: WebSocket) -> None:
        self.rooms.get(group_id, set()).discard(ws)

    async def broadcast(self, group_id: int, event: dict) -> None:
        msg = json.dumps(event, ensure_ascii=False, default=str)
        for ws in list(self.rooms.get(group_id, ())):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001 - drop dead sockets
                self.leave(group_id, ws)

    def publish(self, group_id: int, event_type: str, **data) -> None:
        """Thread-safe fire-and-forget broadcast, callable from sync endpoints."""
        if not self.rooms.get(group_id) or self.loop is None:
            return
        event = {"type": event_type, "group_id": group_id, **data}
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self.broadcast(group_id, event))
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast(group_id, event), self.loop)


hub = Hub()
