"""엔진 조립·팩 캐시. lifespan 에서 한 번."""

from __future__ import annotations

from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.pack_source.file import FilePackSource
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from engine.engine import RuleEngine
from server.bootstrap.settings import Settings
from server.services.session.registry import SessionRegistry


def build_runtime(settings: Settings) -> tuple[RuleEngine, SessionRegistry]:
    embedder = index = llm = cache = None
    if settings.embedding_model:
        from engine.adapters.embedder.litellm import LiteLlmEmbedder

        embedder = LiteLlmEmbedder(
            settings.embedding_model,
            settings.embedding_dim,
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
        )
        index = MemoryVectorIndex()
    if settings.llm_model:
        from engine.adapters.llm.litellm import LiteLlmJudge

        llm = LiteLlmJudge(
            settings.llm_model, provider=settings.llm_provider, api_key=settings.llm_api_key
        )
        cache = MemoryDecisionCache()
    engine = build_engine(
        FilePackSource(settings.pack_dir),
        embedder,
        index,
        None,
        llm,
        cache,
        l3_budget_ms=settings.l3_budget_ms,
    )
    return engine, SessionRegistry(engine)
