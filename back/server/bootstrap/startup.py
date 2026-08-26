"""엔진 조립·팩 캐시. lifespan 에서 한 번."""

from __future__ import annotations

from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from engine.engine import RuleEngine
from server.bootstrap.settings import Settings
from server.services.session.registry import SessionRegistry


def build_runtime(settings: Settings) -> tuple[RuleEngine, SessionRegistry]:
    engine = build_engine(FilePackSource(settings.pack_dir))
    return engine, SessionRegistry(engine)
