"""세션 REST. 생성 하나와 조회 넷.

    POST /sessions                    소켓 없이 세션을 연다
    GET  /sessions                    목록 (mode 필터·커서)
    GET  /sessions/{id}               이벤트를 접은 파생 상태
    GET  /sessions/{id}/events        감사의 원본이자 trace 재생의 입력
    GET  /sessions/{id}/report        증빙 리포트

`POST /sessions` 는 **mode=trace 의 재생 대상(`source_session_id`)을 지정할 수 있는
유일한 곳**이다. ws `hello` 에는 그 필드가 없어서, trace 는 여기서 세션을 만들고
돌려받은 session_id 로 소켓에 붙는다.

조회는 투영이 아니라 이벤트에서 만든다. 요청·응답 모델은 계약에 인라인으로 적혀 있어
생성 모델이 없는 것만 여기서 옮겨 적고, 나머지는 `server/generated/api.py` 를 쓴다.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from contracts.engine_contract import Mode
from engine.pack.source import PackNotFound
from server.generated.api import Report, SessionDetail, SessionSummary
from server.services import report as report_builder

router = APIRouter(tags=["sessions"])


class CustomerProfile(BaseModel):
    type: Literal["general", "professional"] = "general"
    tags: list[str] = []


class CreateSession(BaseModel):
    mode: Mode
    preset_id: str | None = None
    product_code: str | None = None
    pack_version: str | None = None
    customer_profile: CustomerProfile | None = None
    source_session_id: str | None = None  # mode=trace 재생 대상
    audio_ref: str | None = None  # mode=replay 업로드된 오디오


class CreatedSession(BaseModel):
    session_id: str
    pack_version: str
    ws_url: str


@router.post("/sessions", status_code=201)
def create_session(body: CreateSession, request: Request) -> CreatedSession:
    runtime = request.app.state.runtime
    if body.mode == "trace":
        if not body.source_session_id:
            raise HTTPException(400, "mode=trace 는 재생할 source_session_id 가 필요합니다.")
        # 소켓에 붙기 전에 여기서 거른다. ws 에는 not_found 에 해당하는 error code 가 없다
        if not runtime.event_store.of_session(body.source_session_id):
            raise HTTPException(404, "재생할 원본 세션이 없습니다.")
    settings = request.app.state.settings
    profile = body.customer_profile or CustomerProfile()
    try:
        session = runtime.registry.open(
            body.pack_version or settings.default_pack_version,
            body.mode,
            profile.type,
            source_session_id=body.source_session_id,
            audio_ref=body.audio_ref,
        )
    except PackNotFound as e:
        raise HTTPException(404, "규정 팩이 없습니다.") from e
    # 소켓 주소는 상대 경로로 돌려준다. 공개 주소는 배포 형상에 달렸고 서버가 모른다
    return CreatedSession(
        session_id=session.session_id,
        pack_version=session.pack.pack_version,
        ws_url="/ws",
    )


EVENT_KINDS = ("session_started", "utterance", "verdict", "alert", "assist", "session_ended")


def _encode(started: datetime, session_id: str) -> str:
    raw = f"{started.isoformat()}|{session_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        started, _, session_id = raw.partition("|")
        return datetime.fromisoformat(started), session_id
    except (ValueError, binascii.Error) as e:
        raise HTTPException(400, "cursor 를 해석할 수 없습니다.") from e


@router.get("/sessions")
def list_sessions(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    mode: Mode | None = None,
) -> dict[str, Any]:
    projection = request.app.state.runtime.projection
    rows = projection.page(limit, mode, _decode(cursor) if cursor else None)
    next_cursor = (
        _encode(rows[-1]["started_at"], rows[-1]["session_id"]) if len(rows) == limit else None
    )
    return {
        "sessions": [SessionSummary.model_validate(r) for r in rows],
        "next_cursor": next_cursor,
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> SessionDetail:
    """이벤트를 접어 만든 파생 상태다. 원본이 아니다(계약).

    투영(sessions)이 아니라 이벤트에서 직접 만든다. 그래야 투영이 없거나 어긋나도
    같은 답이 나온다.
    """
    runtime = request.app.state.runtime
    events = runtime.event_store.of_session(session_id)
    if not events:
        raise HTTPException(404, "세션이 없습니다.")
    started = next(e for e in events if e["kind"] == "session_started")
    ended = next((e for e in reversed(events) if e["kind"] == "session_ended"), None)
    state = runtime.engine.fold(events)
    try:
        pack = runtime.registry.pack(state.pack_version)
    except PackNotFound as e:
        raise HTTPException(404, "규정 팩이 없습니다.") from e

    summary = runtime.engine.summarize(state, pack, events)
    names = {it.code: it.name for it in pack.items}
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}
    evidence = {
        (e["verdict"]["item_code"], e["verdict"]["axis"]): e["event_id"]
        for e in events
        if e["kind"] == "verdict"
        and e["event_id"] not in superseded
        and e["verdict"].get("evidence")
    }
    body = started["session_started"]
    reason = ended["session_ended"]["reason"] if ended else None
    return SessionDetail.model_validate(
        {
            "session_id": session_id,
            "mode": body["mode"],
            "pack_version": started["pack_version"],
            "product_name": (body.get("product") or {}).get("name"),
            "started_at": started["occurred_at"],
            "ended_at": ended["occurred_at"] if ended else None,
            "status": "running" if ended is None else ("ended" if reason == "normal" else reason),
            "met": summary["met"],
            "items_total": summary["items_total"],
            "violations": summary["violations"],
            "duration_ms": ended["session_ended"]["duration_ms"] if ended else None,
            "items": [
                {
                    "item_code": s.item_code,
                    "name": names.get(s.item_code, s.item_code),
                    "axis": s.axis,
                    "state": s.state,
                    "decided_by": s.decided_by,
                    "missing_elements": list(s.missing_elements) or None,
                    "waive_reason": s.waive_reason,
                    "evidence_ref": evidence.get((s.item_code, s.axis)),
                }
                for s in state.items
            ],
            "alerts": [
                {
                    "event_id": e["event_id"],
                    "alert_type": e["alert"].get("alert_type"),
                    "severity": e["alert"].get("severity"),
                    "message": e["alert"].get("message"),
                }
                for e in events
                if e["kind"] == "alert" and e["event_id"] not in superseded
            ],
        }
    )


@router.get("/sessions/{session_id}/events")
def list_events(
    session_id: str,
    request: Request,
    from_seq: Annotated[int, Query(ge=0)] = 0,
    kind: Annotated[list[str] | None, Query()] = None,
    include_superseded: bool = True,
) -> dict[str, Any]:
    """감사의 원본이자 trace 재생의 입력이다. seq_in_session 오름차순.

    정정 이력이 필요한 쪽이 감사이므로 include_superseded 기본값이 true 다(계약).
    """
    events = request.app.state.runtime.event_store.of_session(session_id)
    if not events:
        raise HTTPException(404, "세션이 없습니다.")
    if kind:
        unknown = set(kind) - set(EVENT_KINDS)
        if unknown:
            raise HTTPException(400, f"알 수 없는 kind: {sorted(unknown)}")
    superseded = {e["supersedes"] for e in events if e.get("supersedes")}
    picked = [
        e
        for e in events
        if e["seq_in_session"] >= from_seq
        and (not kind or e["kind"] in kind)
        and (include_superseded or e["event_id"] not in superseded)
    ]
    return {"session_id": session_id, "events": picked}


@router.get("/sessions/{session_id}/report")
def get_report(session_id: str, request: Request) -> Report:
    """증빙 리포트. 이벤트를 접어 만들고 PDF 와 같은 내용을 준다(계약)."""
    runtime = request.app.state.runtime
    events = runtime.event_store.of_session(session_id)
    if not events:
        raise HTTPException(404, "세션이 없습니다.")
    pack_version = events[0]["pack_version"]
    try:
        pack = runtime.registry.pack(pack_version)
        doc = runtime.pack_source.read(pack_version)
    except PackNotFound as e:
        raise HTTPException(404, "규정 팩이 없습니다.") from e
    return Report.model_validate(
        report_builder.build(session_id, events, runtime.engine, pack, doc)
    )
