"""연결 하나. 전송·하트비트. **seq 와 재전송 로그는 세션이 든다.**

계약이 이유를 적어 두었다 — "세션 단위 단조 증가. 재접속해도 이어진다(**연결 단위로
리셋되면 resume 의 from_seq 가 무의미해짐**). 서버는 세션별 s2c 로그를 유지해 from_seq
이후를 재전송한다."

여기가 들고 있으면 재접속마다 새 `Connection` 이 생겨 번호가 0 부터 다시 매겨지고
로그도 빈 채로 시작한다. 그러면 화면은 끊긴 동안 놓친 판정을 영영 못 받는다.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from server.generated import ws

if TYPE_CHECKING:
    from server.services.session.registry import Session


class Connection:
    def __init__(self, socket: WebSocket, ping_interval_s: float) -> None:
        self.socket = socket
        self.ping_interval_s = ping_interval_s
        self.session: Session | None = None
        # hello 이전에 나가는 오류용. 그 연결은 이어붙일 세션이 없어 resume 대상이 아니다
        self._pre_session_seq = -1
        self._heartbeat: asyncio.Task | None = None

    def attach(self, session: Session) -> None:
        """hello 가 세션을 정한 뒤. 이 뒤의 seq 는 그 세션에서 이어진다."""
        self.session = session

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """seq 를 붙여 보낸다. message 에는 t 와 본문만 있다."""
        if self.session is not None:
            seq = self.session.take_s2c_seq()
        else:
            self._pre_session_seq += 1
            seq = self._pre_session_seq
        payload = {**message, "seq": seq}
        ws.s2c_adapter.validate_python(payload)
        if self.session is not None:
            self.session.s2c_log.append(payload)
        await self.socket.send_json(payload)
        return payload

    async def resend_from(self, from_seq: int) -> None:
        """계약: "서버는 그 다음부터 다시 보낸다". 세션 로그에서 꺼내므로 끊겼다 붙은
        새 연결에서도 놓친 구간이 그대로 나온다."""
        if self.session is None:
            return
        for m in self.session.since(from_seq):
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
