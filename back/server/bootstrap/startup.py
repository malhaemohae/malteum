"""엔진·저장·투영 조립. lifespan 에서 한 번."""

from __future__ import annotations

from dataclasses import dataclass

from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from engine.engine import RuleEngine
from server.bootstrap.settings import Settings
from server.database.session import make_sessions
from server.services.event.store import EventStore, MemoryEventStore, PostgresEventStore
from server.services.pack_store import NullPackStore, PackStore, PostgresPackStore
from server.services.session.projection import (
    NullSessionProjection,
    PostgresSessionProjection,
    SessionProjection,
)
from server.services.session.registry import SessionRegistry


@dataclass(frozen=True)
class Runtime:
    engine: RuleEngine
    registry: SessionRegistry
    event_store: EventStore
    projection: SessionProjection
    pack_store: PackStore


def build_runtime(settings: Settings) -> Runtime:
    engine = build_engine(FilePackSource(settings.pack_dir))
    if settings.event_store == "postgres":
        sessions = make_sessions(settings.database_url)
        store: EventStore = PostgresEventStore(sessions)
        projection: SessionProjection = PostgresSessionProjection(sessions)
        packs: PackStore = PostgresPackStore(sessions)
    else:
        store, projection, packs = MemoryEventStore(), NullSessionProjection(), NullPackStore()
    return Runtime(engine, SessionRegistry(engine), store, projection, packs)
