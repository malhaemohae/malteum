"""엔진·저장·투영 조립. lifespan 에서 한 번.

조립 순서가 있다. 저장소가 먼저 있어야 레지스트리가 재접속을 복원할 수 있고, 팩 저장소가
먼저 있어야 엔진이 DB 의 팩을 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.engine_contract import Engine
from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from engine.pack.source import PackSource
from server.bootstrap.settings import Settings
from server.database.session import make_sessions
from server.services.event.store import EventStore, MemoryEventStore, PostgresEventStore
from server.services.pack_source import DbThenFilePackSource
from server.services.pack_store import NullPackStore, PackStore, PostgresPackStore
from server.services.session.projection import (
    NullSessionProjection,
    PostgresSessionProjection,
    SessionProjection,
)
from server.services.session.registry import SessionRegistry


@dataclass(frozen=True)
class Runtime:
    engine: Engine
    registry: SessionRegistry
    event_store: EventStore
    projection: SessionProjection
    pack_store: PackStore
    # 팩 원문(rulepack.schema.json 그대로). RulePack dataclass 에는 sources 가 없다
    pack_source: PackSource


def build_runtime(settings: Settings) -> Runtime:
    if settings.event_store == "postgres":
        sessions = make_sessions(settings.database_url)
        store: EventStore = PostgresEventStore(sessions)
        projection: SessionProjection = PostgresSessionProjection(sessions)
        packs: PackStore = PostgresPackStore(sessions)
        source = DbThenFilePackSource(packs, settings.pack_dir)
    else:
        store, projection, packs = MemoryEventStore(), NullSessionProjection(), NullPackStore()
        source = FilePackSource(settings.pack_dir)
    engine = build_engine(source)
    return Runtime(engine, SessionRegistry(engine, store), store, projection, packs, source)
