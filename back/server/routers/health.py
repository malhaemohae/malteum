from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    """부분 장애를 구분한다(계약). stt 가 죽어도 text 모드는 살아 있다.

    9/7~9/11 접속 보장의 외부 감시가 이 값을 본다. 저장소가 죽었는데 ok 를 돌려주면
    감시가 무력해지므로 db 는 실제로 찔러 본다.
    """
    runtime = request.app.state.runtime
    checks = {
        "db": "ok" if runtime.event_store.healthy() else "fail",
        "stt": "unconfigured",
        "llm": "unconfigured",
    }
    return {
        "status": "ok" if "fail" not in checks.values() else "degraded",
        "version": request.app.state.settings.version,
        "checks": checks,
    }
