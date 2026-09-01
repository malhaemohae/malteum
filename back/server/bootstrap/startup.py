"""엔진·저장·투영 조립. lifespan 에서 한 번.

조립 순서가 있다. 저장소가 먼저 있어야 레지스트리가 재접속을 복원할 수 있고, 팩 저장소가
먼저 있어야 엔진이 DB 의 팩을 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.engine_contract import Engine
from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.pack_source.file import FilePackSource
from engine.adapters.vector_index.memory import MemoryVectorIndex
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
from server.services.stt.base import SttAdapter


@dataclass(frozen=True)
class Runtime:
    engine: Engine
    registry: SessionRegistry
    event_store: EventStore
    projection: SessionProjection
    pack_store: PackStore
    # 팩 원문(rulepack.schema.json 그대로). RulePack dataclass 에는 sources 가 없다
    pack_source: PackSource
    # STT. 키가 없으면 None 이고 ws 가 stt_unavailable 을 낸다 (3층 폴백)
    stt: SttAdapter | None = None


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
    engine = build_engine(source, l3_budget_ms=settings.l3_budget_ms, **_adapters(settings))
    return Runtime(
        engine,
        SessionRegistry(engine, store),
        store,
        projection,
        packs,
        source,
        _stt(settings),
    )


def _stt(settings: Settings) -> SttAdapter | None:
    """키가 없으면 STT 층을 만들지 않는다. LLM·임베딩과 같은 규칙이다.

    keyterm 은 팩의 `jargon_terms` 를 그대로 넣는다 — 끄면 `만기후이자율` 이
    `만기 후 이자율` 로 갈라져 L1 정확 일치가 깨진다(scripts/stt_check.py 실측).
    """
    if not settings.stt_api_key:
        return None
    from server.services.stt.deepgram import DeepgramAdapter

    return DeepgramAdapter(
        settings.stt_api_key,
        model=settings.stt_model,
        language=settings.stt_language,
        mip_opt_out=settings.stt_mip_opt_out,
    )


def _adapters(settings: Settings) -> dict:
    """실물 LLM·임베딩. 설정이 비면 그 층은 빠지고 engine 이 [DUMMY] 경고로 알린다."""
    out: dict = {}
    if settings.embedding_model:
        if settings.embedding_backend == "local":
            from engine.adapters.embedder.local import LocalStEmbedder

            out["embedder"] = LocalStEmbedder(settings.embedding_model, settings.embedding_dim)
        else:
            from engine.adapters.embedder.litellm import LiteLlmEmbedder

            out["embedder"] = LiteLlmEmbedder(
                settings.embedding_model,
                settings.embedding_dim,
                provider=settings.llm_provider,
                api_key=settings.llm_api_key,
            )
        out["index"] = MemoryVectorIndex()
    if settings.llm_model:
        from engine.adapters.llm.litellm import LiteLlmCorrector, LiteLlmGenerator, LiteLlmJudge

        kw = dict(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            extra_body={"reasoning": {"enabled": False}} if settings.llm_no_reasoning else None,
        )
        out["llm"] = LiteLlmJudge(settings.llm_model, **kw)
        out["cache"] = MemoryDecisionCache()
        if settings.llm_corrector:
            out["corrector"] = LiteLlmCorrector(settings.llm_model, **kw)
        if settings.llm_generator:
            out["generator"] = LiteLlmGenerator(settings.llm_model, **kw)
    return out
