"""세션 REST. 지금은 생성만 있다.

`POST /sessions` 는 소켓 없이 세션을 여는 경로다(api.openapi.yaml). **mode=trace 의
재생 대상(`source_session_id`)을 지정할 수 있는 유일한 곳**이기도 하다. ws `hello` 에는
그 필드가 없어서, trace 는 여기서 세션을 만들고 돌려받은 session_id 로 소켓에 붙는다.

요청·응답 모델은 계약에 인라인으로 적혀 있어 생성 모델이 없다. 여기서 계약을 옮겨 적되
필드를 늘리지 않는다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from contracts.engine_contract import Mode
from engine.pack.source import PackNotFound

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
    if body.mode == "trace" and not body.source_session_id:
        raise HTTPException(400, "mode=trace 는 재생할 source_session_id 가 필요합니다.")
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    profile = body.customer_profile or CustomerProfile()
    try:
        session = runtime.registry.open(
            body.pack_version or settings.default_pack_version,
            body.mode,
            profile.type,
            source_session_id=body.source_session_id,
        )
    except PackNotFound as e:
        raise HTTPException(404, "규정 팩이 없습니다.") from e
    # 소켓 주소는 상대 경로로 돌려준다. 공개 주소는 배포 형상에 달렸고 서버가 모른다
    return CreatedSession(
        session_id=session.session_id,
        pack_version=session.pack.pack_version,
        ws_url="/ws",
    )
