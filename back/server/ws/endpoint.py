"""/ws 진입. 한 소켓에 오디오 업링크와 이벤트 다운링크를 함께 태운다(계약).

텍스트 프레임은 c2s 로 파싱해 처리하고, 바이너리 프레임은 오디오다. STT 어댑터가
붙기 전까지 오디오는 껍질만 벗겨 버리고 `stt_unavailable` 을 한 번 알린다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
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
from server.services.stt.session import SttSession
from server.ws.connection import Connection
from server.ws.handlers import assist, human
from server.ws.protocol import InvalidMessage, parse_audio_frame, parse_c2s

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
    stt: SttSession | None = None
    # 마지막으로 받은 오디오 시퀀스. -1 은 아직 한 조각도 안 받았다는 뜻
    audio_seq = -1

    async def refine_failed(e: Exception) -> None:
        """보정은 화면 뒤에서 돈다. 실패해도 상담은 이어져야 하므로 알리기만 한다."""
        await conn.send(_error("internal", f"L3 보정 실패: {e}", retryable=True))

    try:
        while True:
            frame = await socket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            # 오디오는 JSON 이 아니라 바이너리로 온다(계약 $defs/audioFrame). 텍스트만
            # 받으면 프런트가 마이크를 켜는 순간 소켓이 죽는다
            if (blob := frame.get("bytes")) is not None:
                audio_seq = await _on_audio(blob, conn, audio_seq, stt)
                continue
            try:
                msg = parse_c2s(frame["text"])
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
                if session.mode == "live" and runtime.stt is not None:
                    stt = await _start_stt(
                        session, pipeline, conn, runtime.stt, refiner, runtime.pack_source
                    )
                if session.mode in ("trace", "replay"):
                    # 계약: replay·trace 는 ready 직후 서버가 스스로 시작한다. 시작 메시지는 없다
                    trace = asyncio.create_task(_autostart(session, pipeline, conn))
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
                    t_ms=session.elapsed_ms(),
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
                duration_ms = session.elapsed_ms()
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
            elif msg.t == "ask":
                await _assist(assist.ask(session, pipeline, msg.question, conn.send), conn)
            elif msg.t == "assist_request":
                await _assist(
                    assist.assist_request(session, pipeline, msg.assist_type, conn.send), conn
                )
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001  버그가 소켓을 조용히 끊지 않게 한다
        with suppress(Exception):
            await conn.send(_error("internal", str(e), retryable=True))
    finally:
        if trace is not None:
            trace.cancel()
        if stt is not None:
            await stt.aclose()
        if refiner is not None:
            await refiner.aclose()
        await conn.close()


async def _assist(call: Awaitable[str | None], conn: Connection) -> None:
    """assist 호출 하나. 엔진이 아직 없거나 근거를 못 찾으면 사유를 알린다.

    침묵하지 않는 것이 요점이다. 은행원이 버튼을 눌렀는데 아무 일도 안 일어나면 고장인지
    근거가 없는 것인지 구분할 수 없다.
    """
    try:
        problem = await call
    except NotImplementedError as e:  # engine 의 assist 가 붙기 전
        problem = str(e)
    if problem:
        await conn.send(_error("internal", problem))


async def _start_stt(
    session: Session,
    pipeline: Pipeline,
    conn: Connection,
    adapter,
    refiner: Refiner,
    pack_source,
) -> SttSession | None:
    """live 모드에서 상담 하나에 STT 스트림 하나를 연다.

    팩의 `jargon_terms` 를 keyterm 으로 넣는다. 없으면 `만기후이자율` 이
    `만기 후 이자율` 로 갈라져 L1 의 정확 일치가 깨진다(scripts/stt_check.py 실측).
    `RulePack` dataclass 에는 그 필드가 없어 팩 원문에서 꺼낸다.

    여는 데 실패해도 상담은 이어져야 한다 — 계약의 `stt_unavailable` 이 프런트에
    text 모드 전환을 제안하게 한다(3층 폴백).
    """

    async def submit(utterance) -> None:
        await pipeline.submit_utterance(session, utterance, conn.send, refiner.schedule)

    keyterms: list[str] = []
    with suppress(Exception):  # 용어가 없어도 전사는 돈다. 적중률만 떨어진다
        keyterms = list(pack_source.read(session.pack.pack_version).get("jargon_terms") or [])

    stt = SttSession(session, conn.send, submit)
    try:
        await stt.start(adapter, keyterms)
    except Exception as e:  # noqa: BLE001  공급자 장애가 상담을 끊지 않게 한다
        await conn.send(_error("stt_unavailable", f"STT 를 열지 못했습니다: {e}", retryable=True))
        return None
    return stt


async def _on_audio(blob: bytes, conn: Connection, last_seq: int, stt: SttSession | None) -> int:
    """오디오 프레임 하나. 껍질을 벗겨 STT 로 흘린다.

    STT 가 없으면 연결당 한 번만 `stt_unavailable` 을 보낸다. 100ms 마다 오는 것이라
    매 조각에 답하면 화면이 오류로 뒤덮인다. 계약이 그 코드를 둔 이유가 이것이다 —
    프런트가 받으면 text 모드 전환을 제안한다(3층 폴백, 기획 7.1 ⑪).
    """
    try:
        audio = parse_audio_frame(blob)
    except InvalidMessage as e:
        # 규격이 어긋난 것은 매번 알린다. 프런트가 프레임을 잘못 만들고 있다는 뜻이라
        # 조용히 버리면 마이크가 안 되는 이유를 아무도 못 찾는다
        await conn.send(_error("invalid_message", str(e)))
        return last_seq
    if stt is None:
        if last_seq < 0:
            await conn.send(
                _error("stt_unavailable", "STT 가 설정되지 않았습니다.", retryable=True)
            )
        return audio.seq
    if 0 <= last_seq < audio.seq - 1:
        # 계약: 시퀀스는 재접속 시 손실 구간 판정에 쓴다. 지금은 알리기만 하고 메우지
        # 않는다 — 빠진 소리를 지어낼 수는 없고, 리포트가 그 구간을 모르는 편이 낫다
        gap = audio.seq - last_seq - 1
        await conn.send(_error("internal", f"오디오 {gap}조각이 비었습니다.", retryable=True))
    await stt.feed(audio.pcm)
    return audio.seq


async def _autostart(session: Session, pipeline: Pipeline, conn: Connection) -> None:
    """계약: replay·trace 는 hello 를 받은 서버가 ready 직후 스스로 시작한다.

    두 모드가 같은 약속을 지고 다른 재료를 쓴다. trace 는 저장된 이벤트를, replay 는
    사전 오디오를 실시간 속도로 STT 에 흘린다(11.4).
    """
    if session.mode == "trace":
        await _start_trace(session, pipeline, conn)
    else:
        await _start_replay(conn)


async def _start_replay(conn: Connection) -> None:
    """사전 오디오 재생. STT 어댑터가 붙으면 여기서 흘린다(11.4 기본 시연 경로).

    아직 어댑터가 없다. 계약이 자동 시작을 약속했으므로 아무 말 없이 멈춰 있으면 화면은
    영원히 기다린다. 못 하는 이유를 말해 주면 프런트가 trace·text 로 갈아탄다(3층 폴백).
    """
    await conn.send(
        _error("stt_unavailable", "STT 어댑터가 없어 replay 를 시작할 수 없습니다.", retryable=True)
    )


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
