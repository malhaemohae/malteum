"""세션 REST. 생성 하나와 조회 넷.

    POST /sessions                    소켓 없이 세션을 연다
    GET  /sessions                    목록 (mode 필터·커서)
    GET  /sessions/{id}               이벤트를 접은 파생 상태
    GET  /sessions/{id}/events        감사의 원본이자 trace 재생의 입력
    POST /sessions/{id}/audio         replay 용 오디오 업로드
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
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from contracts.engine_contract import Mode
from engine.pack.source import PackNotFound
from server.generated.api import Report, SessionDetail, SessionSummary
from server.services import report as report_builder
from server.services import report_pdf
from server.services.event.envelope import ID_MAX, ID_MIN, valid_id
from server.services.stt import audio

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
        "sessions": [_summary(r) for r in rows],
        "next_cursor": next_cursor,
    }


# 계약이 integer 로 둔 옵셔널 값들. 아직 접지 않은 세션은 이 값이 없다
_COUNTS = ("met", "items_total", "violations")

# 계약 전체에서 null 을 허용하는 자리는 이 둘뿐이다(`type: [string, "null"]` 전수 검색).
# 나머지 옵셔널 필드는 값이 없으면 **키를 빼야 한다** — 생성 모델은 안 채운 필드를 null 로
# 내보내는데, 계약의 그 자리들은 string·integer·array 여서 null 이 타입 위반이다.
# `scripts/smoke.py` 의 응답 모양 대조가 이것을 세 경로에서 잡았다
_NULLABLE = ("ended_at", "next_cursor")


def _contract_json(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump(mode="json", exclude_none=True)
    for key in _NULLABLE:
        if key in type(model).model_fields:
            data.setdefault(key, None)  # 진행 중인 상담은 ended_at 이 null 이어야 한다
    return data


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    """세션 요약 한 줄. **집계가 없으면 0 이 아니라 키를 뺀다.**

    위반 0 건과 "아직 모름" 은 다른 말이다. 목록에서 0 을 보면 사람은 깨끗이 끝난 상담으로
    읽는다. 계약이 옵셔널로 둔 자리라 빼는 쪽이 맞고, null 로 두면 integer 타입에 어긋난다
    (scripts/smoke.py 의 응답 모양 대조가 잡았다).
    """
    data = SessionSummary.model_validate(row).model_dump(mode="json")
    return {k: v for k, v in data.items() if not (v is None and k in _COUNTS)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    """이벤트를 접어 만든 파생 상태다. 원본이 아니다(계약).

    투영(sessions)이 아니라 이벤트에서 직접 만든다. 그래야 투영이 없거나 어긋나도
    같은 답이 나온다.

    반환 타입이 `SessionDetail` 이 아니라 dict 인 이유: 그 모델은 안 채운 옵셔널 필드를
    null 로 내보내는데, 계약에서 그 자리들은 `string`·`integer`·`array` 라 null 이 타입
    위반이다. 아래에서 검증은 그대로 하고 직렬화만 우리가 한다.
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
    detail = SessionDetail.model_validate(
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
    return _contract_json(detail)


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


@router.post("/sessions/{session_id}/audio", status_code=202)
async def upload_audio(session_id: str, request: Request, file: UploadFile) -> dict[str, Any]:
    """replay 용 오디오 업로드. 계약: "파일로 재생한다. live 와 게이트웨이 이후 경로가 같다".

    받아서 검사하고 저장만 한다. 재생은 ws `hello` 가 `mode=replay` 로 붙을 때
    시작한다(계약: ready 직후 자동). 여기서 바로 흘리면 결과를 받을 소켓이 없다.

    규격이 다른 파일은 거절한다. 넘겨 보내면 STT 가 소리를 어긋나게 해석해 전사가
    비거나 밀리고, 그 사실이 상담 한복판에서야 드러난다.
    """
    settings = request.app.state.settings
    if not valid_id(session_id):
        raise HTTPException(400, f"session_id 는 {ID_MIN}~{ID_MAX} 자여야 합니다.")

    target = Path(settings.upload_dir) / f"{session_id}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await file.read())
    try:
        pcm = audio.read_pcm(target)
    except audio.AudioNotFound as e:
        target.unlink(missing_ok=True)  # 못 쓸 파일을 남기지 않는다
        raise HTTPException(415, str(e)) from e
    except Exception:
        # 예상 못 한 실패에도 파일은 지운다. 남으면 다음 replay 가 그 파일을 재생한다
        target.unlink(missing_ok=True)
        raise

    session = request.app.state.runtime.registry.get(session_id)
    audio_ref = target.name
    if session is not None:
        session.audio_ref = audio_ref
    return {
        "audio_ref": audio_ref,
        "duration_ms": len(pcm) * 1000 // (audio.SAMPLE_RATE * 2),
    }


def _report(session_id: str, request: Request) -> dict[str, Any]:
    """리포트 한 벌. JSON 경로와 PDF 경로가 이것을 나눠 쓴다.

    계약이 두 경로에 **같은 내용**을 요구하므로 만드는 자리를 하나로 둔다. 각자
    만들면 언젠가 다른 수를 말하고, 그러면 증빙으로 못 쓴다.
    """
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
    return report_builder.build(session_id, events, runtime.engine, pack, doc)


@router.get("/sessions/{session_id}/report")
def get_report(session_id: str, request: Request) -> dict[str, Any]:
    """증빙 리포트. 이벤트를 접어 만들고 PDF 와 같은 내용을 준다(계약).

    dict 로 내보내는 이유는 `get_session` 과 같다 — `_contract_json` 주석 참조.
    """
    return _contract_json(Report.model_validate(_report(session_id, request)))


@router.get(
    "/sessions/{session_id}/report.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_report_pdf(session_id: str, request: Request) -> Response:
    """같은 리포트를 PDF 로. 상담이 끝나면 `ended` 가 이 경로를 `report_url` 로 알린다.

    화면의 "PDF로 저장" 은 그 값이 있으면 새 탭으로 연다(없을 때만 브라우저 인쇄).
    그래서 이 경로가 비어 있으면 심사위원이 그 버튼을 눌렀을 때 404 를 본다.

    `Content-Disposition` 을 `inline` 으로 둔다 — 새 탭에서 바로 보이는 편이 낫고,
    저장은 뷰어가 한다.
    """
    body = report_pdf.render(_report(session_id, request))
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="report-{session_id}.pdf"'},
    )
