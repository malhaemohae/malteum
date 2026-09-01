"""/ws 진입. 텍스트 프레임 → c2s 파싱 → 처리. 바이너리 프레임(오디오)은 services/stt 가 생기면."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from contracts.engine_contract import Utterance
from engine.pack.source import PackNotFound
from server.mapping.event_to_s2c import ready
from server.services.event.envelope import ID_MAX, ID_MIN, valid_id
from server.services.session.pipeline import Pipeline
from server.services.session.refiner import Refiner
from server.services.session.registry import Session
from server.services.session.replay import replay
from server.ws.connection import Connection
from server.ws.handlers import human
from server.ws.protocol import InvalidMessage, parse_c2s

router = APIRouter()


def _error(code: str, message: str, retryable: bool = False) -> dict:
    """계약의 error 는 code 가 enum 이고 retryable 이 프런트의 분기 재료다.
    (stt_unavailable 이면 프런트가 text 모드 전환을 제안한다 — 3층 폴백)"""
    return {"t": "error", "code": code, "message": message[:300], "retryable": retryable}


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
    refiner: Refiner | None = None
    started_at = time.monotonic()

    async def refine_failed(e: Exception) -> None:
        """보정은 화면 뒤에서 돈다. 실패해도 상담은 이어져야 하므로 알리기만 한다."""
        await conn.send(_error("internal", f"L3 보정 실패: {e}", retryable=True))

    try:
        while True:
            raw = await socket.receive_text()
            try:
                msg = parse_c2s(raw)
            except InvalidMessage as e:
                await conn.send(_error("invalid_message", str(e)))
                continue

            if msg.t == "hello":
                if msg.session_id and not valid_id(msg.session_id):
                    await conn.send(
                        _error(
                            "invalid_message",
                            f"session_id 는 {ID_MIN}~{ID_MAX} 자여야 합니다 (events.schema.json).",
                        )
                    )
                    continue
                customer_type = (msg.customer_profile and msg.customer_profile.type) or "general"
                # POST /sessions 로 미리 연 세션이면 그것을 잇는다. trace 의 재생 대상이 거기 있다
                session = registry.get(msg.session_id) if msg.session_id else None
                if session is None:
                    try:
                        session = registry.open(
                            settings.default_pack_version, msg.mode, customer_type, msg.session_id
                        )
                    except PackNotFound:
                        await conn.send(_error("pack_not_found", "규정 팩이 없습니다."))
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
                refiner = Refiner(session, pipeline, conn.send, refine_failed)
                if session.mode == "trace":
                    # 계약: ready 직후 서버가 스스로 재생을 시작한다. 시작 메시지는 없다
                    trace = asyncio.create_task(_start_trace(session, pipeline, conn))
            elif msg.t == "pong":
                pass
            elif session is None:
                await conn.send(_error("invalid_message", "hello 가 먼저입니다."))
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
                    await pipeline.submit_utterance(
                        session,
                        utterance,
                        conn.send,
                        refiner.schedule if refiner else None,
                    )
                except NotImplementedError as e:  # 엔진 뼈대 단계. tiers/ 가 생기면 사라진다
                    await conn.send(_error("internal", str(e), retryable=True))
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
            elif msg.t == "mark_met":
                problem = await human.mark_met(
                    session, pipeline, msg.item_code, bool(msg.undo), conn.send
                )
                if problem:
                    await conn.send(_error("invalid_message", problem))
            elif msg.t == "mark_waived":
                problem = await human.mark_waived(
                    session, pipeline, msg.item_code, msg.reason, conn.send
                )
                if problem:
                    await conn.send(_error("invalid_message", problem))
            elif msg.t == "acknowledge":
                problem = await human.acknowledge(session, pipeline, msg.alert_ref, conn.send)
                if problem:
                    await conn.send(_error("invalid_message", problem))
            else:  # ask·assist_request — engine 의 assist 가 붙으면
                await conn.send(_error("internal", f"{msg.t} 는 아직 없습니다."))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001  버그가 소켓을 조용히 끊지 않게 한다
        with suppress(Exception):
            await conn.send(_error("internal", str(e), retryable=True))
    finally:
        if trace is not None:
            trace.cancel()
        if refiner is not None:
            await refiner.aclose()
        await conn.close()


async def _start_trace(session: Session, pipeline: Pipeline, conn: Connection) -> None:
    """원본 세션의 이벤트를 다시 흘린다. STT·LLM 을 부르지 않는다.

    별도 태스크로 돌기 때문에 예외를 여기서 잡아야 한다. 안 잡으면 화면은 아무 통보도
    못 받고 멈춘 채 기다린다. trace 는 장애 폴백 카드라 조용히 죽으면 안 된다.
    """
    try:
        events = pipeline.store.of_session(session.source_session_id or "")
        if not events:
            # POST /sessions 가 먼저 걸러 준다. 여기까지 오면 그 사이에 사라진 것이다
            await conn.send(_error("session_expired", "재생할 원본 세션이 없습니다."))
            return
        await replay(pipeline.engine, session.pack, events, conn.send)
        # 재생이 끝난 시점의 상태를 세션에 반영해 둔다. end 의 요약이 원본과 맞아야 한다
        session.state = pipeline.engine.fold(events)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001  재생 실패를 화면에 알린다
        await conn.send(_error("internal", f"재생 실패: {e}", retryable=True))
