"""M1 gateway 진입점. `uv run uvicorn server.main:app`."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from server import errors
from server.bootstrap.settings import Settings, get_settings
from server.bootstrap.startup import build_runtime
from server.routers import documents, evidence, health, packs, sessions
from server.ws import endpoint as ws_endpoint


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = build_runtime(settings)
        yield

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
