"""연결 하나. seq 발급·전송·(resume 용) 최근 전송분 보관·하트비트."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from fastapi import WebSocket

from server.generated import ws

REPLAY_WINDOW = 500


class Connection:
    def __init__(self, socket: WebSocket, ping_interval_s: float) -> None:
        self.socket = socket
        self.ping_interval_s = ping_interval_s
        self.seq = -1
        self.sent: deque[dict[str, Any]] = deque(maxlen=REPLAY_WINDOW)
        self._heartbeat: asyncio.Task | None = None

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """seq 를 붙여 보낸다. message 에는 t 와 본문만 있다."""
        self.seq += 1
        payload = {**message, "seq": self.seq}
        ws.s2c_adapter.validate_python(payload)
        self.sent.append(payload)
        await self.socket.send_json(payload)
        return payload

    async def resend_from(self, from_seq: int) -> None:
        for m in list(self.sent):
            if m["seq"] > from_seq:
                await self.socket.send_json(m)

    def start_heartbeat(self) -> None:
        self._heartbeat = asyncio.create_task(self._ping_loop())

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(self.ping_interval_s)
            await self.send({"t": "ping"})

    async def close(self) -> None:
        if self._heartbeat:
            self._heartbeat.cancel()
