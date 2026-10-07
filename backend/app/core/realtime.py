"""WebSocket fan-out. Events carry identifiers only, never clinical content."""
import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger("medflow.realtime")


class Hub:
    def __init__(self) -> None:
        self._conns: dict[WebSocket, int] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add(self, ws: WebSocket, user_id: int) -> None:
        self._conns[ws] = user_id

    def remove(self, ws: WebSocket) -> None:
        self._conns.pop(ws, None)

    async def _send(self, message: dict, user_ids: set[int] | None) -> None:
        for ws, uid in list(self._conns.items()):
            if user_ids is not None and uid not in user_ids:
                continue
            try:
                await ws.send_json(message)
            except Exception:  # client went away mid-send
                self.remove(ws)

    def publish(self, event: str, user_ids: set[int] | None = None, **payload) -> None:
        """Safe from both sync (threadpool) and async handlers."""
        if not self._loop or not self._conns:
            return
        coro = self._send({"type": event, **payload}, user_ids)
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(coro, self._loop)


hub = Hub()
