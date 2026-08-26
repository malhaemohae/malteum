from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    # db·stt·llm·embedding 점검은 각 어댑터가 생기면 여기서 부른다
    return {
        "status": "ok",
        "version": request.app.state.settings.version,
        "checks": {"stt": "unconfigured", "llm": "unconfigured"},
    }
