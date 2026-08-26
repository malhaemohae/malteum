"""M1 gateway 진입점. `uv run uvicorn server.main:app`."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.bootstrap.settings import Settings, get_settings
from server.bootstrap.startup import build_runtime
from server.routers import health
from server.ws import endpoint as ws_endpoint


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine, app.state.registry = build_runtime(settings)
        yield

    app = FastAPI(title=settings.display_name, version=settings.version, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router, prefix="/api")
    app.include_router(ws_endpoint.router)
    return app


app = create_app()
