"""설정 한 곳. 환경변수·.env 로 덮어쓴다. 제품 표시 이름은 여기에만 둔다."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACK_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACK_DIR.parent


class Settings(BaseSettings):
    # 루트 .env 하나에 compose 변수와 APP_ 변수를 함께 둔다. back/.env 가 있으면 그쪽이 덮어쓴다
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACK_DIR / ".env"), env_prefix="APP_", extra="ignore"
    )

    display_name: str = "말틈"
    version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    # postgres 가 정상 경로. memory 는 DB 없이 도는 테스트·데모용이며 재시작하면 사라진다
    event_store: Literal["postgres", "memory"] = "postgres"
    pack_dir: Path = BACK_DIR / "contracts" / "fixtures"
    # 근거 원문 PDF. 팩의 sources[].doc_id 와 파일명이 1:1 이다
    docs_dir: Path = BACK_DIR.parent / "assets" / "03_규정문서"
    # 시연 자산 루트. replay 의 audio_ref 가 이 아래를 가리킨다(최상위 README).
    # 지금 `scenarios/` 가 비어 있고 R5 가 채우면 그대로 붙는다
    assets_dir: Path = BACK_DIR.parent / "assets"
    # 심사위원이 올린 오디오. assets 는 읽기 전용으로 붙이므로(compose) 쓰는 자리를 따로 둔다
    upload_dir: Path = BACK_DIR.parent / "uploads"
    default_pack_version: str = "DEP-2026.08-v4"
    ws_ping_interval_s: float = 30.0
    # 실물 어댑터. LLM_MODEL 이 비면 refine(L3) 생략, EMBEDDING_MODEL 이 비면 L2 생략
    llm_provider: str = "openrouter"  # LiteLLM provider 이름: openrouter · anthropic · openai …
    llm_api_key: str | None = None
    llm_model: str | None = None  # provider 공식 표기 그대로. 예: qwen/qwen3-32b
    # Qwen 등 thinking 기본 모델은 reasoning 을 꺼야 tool_choice 강제가 되고 지연도 준다
    llm_no_reasoning: bool = False
    llm_corrector: bool = False  # refine 앞 STT 교정 (LLM 1회 추가)
    llm_generator: bool = False  # answer 문장 생성 (guard P4 가 거른다)
    # 임베딩. 비우면 L2 생략. local 은 sentence-transformers(M3 팩 발행과 같은 모델),
    # litellm 은 llm_provider 의 API 임베딩
    embedding_backend: Literal["local", "litellm"] = "local"
    embedding_model: str | None = None  # 예: intfloat/multilingual-e5-small
    embedding_dim: int = 384  # 팩의 embedding.dim 과 같아야 load_pack 이 받는다
    l3_budget_ms: float = (
        1500  # 계약 BUDGET_L3_MS. 실물 API 왕복이 넘기면 여기서 완화 (월요일 합의 대상)
    )
    # STT. 키가 비면 오디오 층이 빠지고 ws 가 stt_unavailable 을 낸다(3층 폴백).
    # 기획 11.3: Deepgram nova-3 ko · keyterm·numerals·mip_opt_out
    stt_provider: str = "deepgram"
    stt_api_key: str | None = None
    stt_model: str = "nova-3"
    stt_language: str = "ko"
    # 13장이 라이선스·약관 조건으로 정한 값. 할인을 포기하고 학습 사용을 거부한다.
    # 은행 도입 전제에서 옵션이 아니라 조건이라 기본값을 켜 둔다
    stt_mip_opt_out: bool = True


def get_settings() -> Settings:
    return Settings()
