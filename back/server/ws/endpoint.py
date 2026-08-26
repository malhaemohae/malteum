"""/ws 진입. 텍스트 프레임 → c2s 파싱 → 처리. 바이너리 프레임(오디오)은 services/stt 가 생기면."""

from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from contracts.engine_contract import Utterance
from engine.pack.source import PackNotFound
from server.mapping.event_to_s2c import ready
from server.services.event.store import MemoryEventStore
from server.services.session.pipeline import Pipeline
from server.ws.connection import Connection
from server.ws.protocol import InvalidMessage, parse_c2s

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(socket: WebSocket) -> None:
    app = socket.app
    settings = app.state.settings
    registry = app.state.registry
    if not hasattr(app.state, "event_store"):
        app.state.event_store = MemoryEventStore()
    pipeline = Pipeline(app.state.engine, app.state.event_store)

    await socket.accept()
    conn = Connection(socket, settings.ws_ping_interval_s)
    session = None
    started_at = time.monotonic()
    try:
        while True:
            raw = await socket.receive_text()
            try:
                msg = parse_c2s(raw)
            except InvalidMessage as e:
                await conn.send({"t": "error", "code": "invalid_message", "message": str(e)})
                continue

            if msg.t == "hello":
                customer_type = (msg.customer_profile and msg.customer_profile.type) or "general"
                try:
                    session = registry.open(
                        settings.default_pack_version, msg.mode, customer_type, msg.session_id
                    )
                except PackNotFound:
                    await conn.send(
                        {"t": "error", "code": "pack_not_found", "message": "규정 팩이 없습니다."}
                    )
                    continue
                product = {
                    "code": session.pack.product_code,
                    "name": session.pack.product_name,
                    "category": "deposit",
                }
                pipeline.start(session, msg.mode, product, customer_type)
                await conn.send(ready(session.session_id, session.pack, session.state, msg.mode))
                conn.start_heartbeat()
            elif msg.t == "pong":
                pass
            elif session is None:
                await conn.send(
                    {"t": "error", "code": "invalid_message", "message": "hello 가 먼저입니다."}
                )
            elif msg.t == "resume":
                await conn.resend_from(msg.from_seq)
            elif msg.t == "text_utterance":
                utterance = Utterance(
                    utterance_id="",
                    speaker=msg.speaker,
                    text=msg.text,
                    t_ms=int((time.monotonic() - started_at) * 1000),
                )
                try:
                    await pipeline.submit_utterance(session, utterance, conn.send)
                except NotImplementedError as e:  # 엔진 뼈대 단계. tiers/ 가 생기면 사라진다
                    await conn.send({"t": "error", "code": "internal", "message": str(e)})
            elif msg.t == "end":
                duration_ms = int((time.monotonic() - started_at) * 1000)
                ended = pipeline.end(session, duration_ms)
                await conn.send(
                    {
                        "t": "ended",
                        "session_id": session.session_id,
                        "summary": ended["session_ended"]["summary"],
                        "report_url": f"/api/sessions/{session.session_id}/report.pdf",
                    }
                )
                registry.close(session.session_id)
                break
            else:  # ask·assist_request·mark_waived·acknowledge — ws/handlers/ 가 생기면
                await conn.send(
                    {"t": "error", "code": "internal", "message": f"{msg.t} 는 아직 없습니다."}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await conn.close()
