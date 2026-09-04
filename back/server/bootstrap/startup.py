"""엔진·저장·투영 조립. lifespan 에서 한 번.

조립 순서가 있다. 저장소가 먼저 있어야 레지스트리가 재접속을 복원할 수 있고, 팩 저장소가
먼저 있어야 엔진이 DB 의 팩을 읽는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from contracts.engine_contract import Engine
from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.pack_source.file import FilePackSource
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from engine.pack.source import PackSource
from server.bootstrap.settings import Settings
from server.database.session import make_sessions
from server.services.approval_store import (
    ApprovalStore,
    MemoryApprovalStore,
    PostgresApprovalStore,
)
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
from server.services.stt.speaker import RoleJudge, RuleRoleJudge

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    engine: Engine
    registry: SessionRegistry
    event_store: EventStore
    projection: SessionProjection
    pack_store: PackStore
    # 팩 원문(rulepack.schema.json 그대로). RulePack dataclass 에는 sources 가 없다
    pack_source: PackSource
    # 후보 승인 기록. 후보 자체는 저장하지 않는다 — 사람이 누른 결정만 원본이다
    approvals: ApprovalStore
    # STT. 키가 없으면 None 이고 ws 가 stt_unavailable 을 낸다 (3층 폴백)
    stt: SttAdapter | None = None
    # 화자 분리 번호 → 역할. LLM 설정이 없으면 규칙 폴백이라 None 이 되지 않는다
    role_judge: RoleJudge = RuleRoleJudge()


def build_runtime(settings: Settings) -> Runtime:
    _warn_open_write_paths(settings)
    if settings.event_store == "postgres":
        sessions = make_sessions(settings.database_url)
        store: EventStore = PostgresEventStore(sessions)
        projection: SessionProjection = PostgresSessionProjection(sessions)
        packs: PackStore = PostgresPackStore(sessions)
        approvals: ApprovalStore = PostgresApprovalStore(sessions)
        source = DbThenFilePackSource(packs, settings.pack_dir)
    else:
        store, projection, packs = MemoryEventStore(), NullSessionProjection(), NullPackStore()
        # 승인은 누른 직후 다시 읽는 값이라 이 모드에서도 담는다(approval_store.py)
        approvals = MemoryApprovalStore()
        source = FilePackSource(settings.pack_dir)
    engine = build_engine(source, l3_budget_ms=settings.l3_budget_ms, **_adapters(settings))
    return Runtime(
        engine,
        SessionRegistry(engine, store),
        store,
        projection,
        packs,
        source,
        approvals,
        _stt(settings),
        _role_judge(settings),
    )


def _warn_open_write_paths(settings: Settings) -> None:
    """토큰이 없으면 부팅 때 한 번 말한다.

    없어도 서버는 뜨고 심사 기본 경로(기획 10.1)는 전부 돈다 — 조회·세션 시작은 계약이
    열어 두라고 했기 때문이다. 그래서 **아무도 눈치채지 못한 채 배포되고, 팩을 발행하려는
    순간에야 401 로 드러난다.** 그때는 시연 중이다.
    """
    if settings.admin_token:
        return
    log.warning(
        "APP_ADMIN_TOKEN 이 없습니다. 쓰기 경로가 401 입니다 — "
        "POST /packs/publish · POST /documents · 후보 승인. "
        "조회와 세션 시작은 계약대로 열려 있어 심사 기본 경로는 그대로 돕니다. "
        "설정하려면 배포 .env 에 APP_ADMIN_TOKEN 을 넣으십시오 (.env.example 참고)."
    )


def _stt(settings: Settings) -> SttAdapter | None:
    """공급자별 어댑터. 설정이 없으면 STT 층을 만들지 않는다. LLM·임베딩과 같은 규칙이다.

    keyterm 은 팩의 `jargon_terms` 를 그대로 넣는다 — 끄면 `만기후이자율` 이
    `만기 후 이자율` 로 갈라져 L1 정확 일치가 깨진다(scripts/stt_check.py 실측).
    """
    if settings.stt_provider == "openai_file":
        if not settings.stt_base_url:
            log.warning(
                "APP_STT_PROVIDER=openai_file 인데 APP_STT_BASE_URL 이 없습니다. "
                "오디오 층을 만들지 않습니다 — ws 가 stt_unavailable 을 냅니다."
            )
            return None
        if not settings.diarization_url:
            # 발화 단위 어댑터는 끊을 자리를 화자 분리 구간에서 얻는다. 공급원이 없으면
            # 어댑터는 열리지만 구간이 오지 않아 **전사가 조용히 멈춘다** — ws 는 정상으로
            # 보이고 화면에는 아무 오류도 안 뜬다. 여기서 접어야 3층 폴백이 돈다
            log.warning(
                "APP_STT_PROVIDER=openai_file 인데 APP_DIARIZATION_URL 이 없습니다. "
                "끊을 자리를 얻을 화자 분리 공급원이 없어 오디오 층을 만들지 않습니다 — "
                "ws 가 stt_unavailable 을 냅니다."
            )
            return None
        from server.services.stt.openai_file import SegmentedFileSttAdapter

        return SegmentedFileSttAdapter(
            settings.stt_base_url,
            model=settings.stt_model,
            api_key=settings.stt_api_key,
            language=settings.stt_language,
        )
    if not settings.stt_api_key:
        return None
    from server.services.stt.deepgram import DeepgramAdapter

    return DeepgramAdapter(
        settings.stt_api_key,
        model=settings.stt_model,
        language=settings.stt_language,
        mip_opt_out=settings.stt_mip_opt_out,
    )


def _role_judge(settings: Settings) -> RoleJudge:
    """화자 분리 번호를 역할로 옮길 때 물을 상대. LLM 설정을 그대로 재사용한다.

    LLM 이 없거나 꺼 두었으면 규칙 폴백이다 — 확정 번호가 하나면 그 반대, 아니면
    teller, 신뢰도는 낮게. 문장을 읽지 않는 판단이라 게이트가 은행원 판정을 접는다.
    """
    if not (settings.speaker_role_judge and settings.llm_model):
        return RuleRoleJudge()
    from server.services.stt.role_judge import LiteLlmRoleJudge

    return LiteLlmRoleJudge(
        settings.llm_model,
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        extra_body={"reasoning": {"enabled": False}} if settings.llm_no_reasoning else None,
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
