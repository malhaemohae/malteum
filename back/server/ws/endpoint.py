"""/ws 진입. 텍스트 프레임 → c2s 파싱 → 처리. 바이너리 프레임(오디오)은 services/stt 가 생기면."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from contracts.engine_contract import Utterance
from engine.pack.source import PackNotFound
from server.mapping.event_to_s2c import ready
from server.services.session.pipeline import Pipeline
from server.services.session.replay import replay
from server.ws.connection import Connection
from server.ws.protocol import InvalidMessage, parse_c2s

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(socket: WebSocket) -> None:
    app = socket.app
    settings = app.state.settings
    runtime = app.state.runtime
    registry = runtime.registry
    pipeline = Pipeline(runtime.engine, runtime.event_store, runtime.projection)

    await socket.accept()
    conn = Connection(socket, settings.ws_ping_interval_s)
    session = None
    trace: asyncio.Task | None = None
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
                # POST /sessions 로 미리 연 세션이면 그것을 잇는다. trace 의 재생 대상이 거기 있다
                session = registry.get(msg.session_id) if msg.session_id else None
                if session is None:
                    try:
                        session = registry.open(
                            settings.default_pack_version, msg.mode, customer_type, msg.session_id
                        )
                    except PackNotFound:
                        await conn.send(
                            {
                                "t": "error",
                                "code": "pack_not_found",
                                "message": "규정 팩이 없습니다.",
                            }
                        )
                        continue
                product = {
                    "code": session.pack.product_code,
                    "name": session.pack.product_name,
                    "category": "deposit",
                }
                if not session.restored:
                    # 되살린 세션은 session_started 가 이미 있다. 다시 쓰면 seq 가 겹친다
                    pipeline.start(session, session.mode, product, customer_type)
                await conn.send(
                    ready(session.session_id, session.pack, session.state, session.mode)
                )
                conn.start_heartbeat()
                if session.mode == "trace":
                    # 계약: ready 직후 서버가 스스로 재생을 시작한다. 시작 메시지는 없다
                    trace = asyncio.create_task(_start_trace(session, pipeline, conn))
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
        if trace is not None:
            trace.cancel()
        await conn.close()


async def _start_trace(session, pipeline: Pipeline, conn: Connection) -> None:
    """원본 세션의 이벤트를 다시 흘린다. STT·LLM 을 부르지 않는다."""
    events = pipeline.store.of_session(session.source_session_id or "")
    if not events:
        await conn.send({"t": "error", "code": "not_found", "message": "재생할 이벤트가 없습니다."})
        return
    await replay(pipeline.engine, session.pack, events, conn.send)
    # 재생이 끝난 시점의 상태를 세션에 반영해 둔다. end 의 요약이 원본과 맞아야 한다
    session.state = pipeline.engine.fold(events)
