"""M1 gateway 진입점. `uv run uvicorn server.main:app`."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from server import errors
from server.bootstrap.settings import Settings, get_settings
from server.bootstrap.startup import build_runtime
from server.bootstrap.warmup import warm
from server.routers import documents, evidence, health, packs, sessions
from server.ws import endpoint as ws_endpoint


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = build_runtime(settings)
        # 임베딩 모델의 첫 로딩은 26초쯤 걸린다(warmup.py 실측). 미리 배경에서 치러
        # 두면 첫 상담이 그만큼 빨라진다. 설정이 없으면 데울 것도 없다.
        # 취소는 대기 중인 코루틴만 푼다. 적재 스레드는 끝까지 돌고, 종료는 그것을
        # 기다린다. 테스트가 매번 그 비용을 치르지 않도록 조건을 둔다
        warming = (
            asyncio.create_task(warm(app.state.runtime, settings))
            if settings.embedding_model
            else None
        )
        try:
            yield
        finally:
            if warming is not None:
                warming.cancel()
                with suppress(asyncio.CancelledError):
                    await warming

    app = FastAPI(
        title=settings.display_name,
        version=settings.version,
        lifespan=lifespan,
        # 문서도 /api 아래. 배포에서 nginx 가 /api/·/ws 만 서버로 보내고 / 는 프런트 몫이다
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    errors.install(app)  # 계약 Error 모양. ws 와 같은 code 집합을 쓴다
    app.include_router(health.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(packs.router, prefix="/api")
    app.include_router(evidence.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(ws_endpoint.router)
    return app


app = create_app()
