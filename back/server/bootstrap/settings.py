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
    # 구조 추출 덤프. `scripts/dump_extraction.py` 가 오프라인에서 떠서 커밋한 결과다.
    # 서버는 자바를 부르지 않는다 — 이유는 services/extraction.py
    extraction_dir: Path = BACK_DIR.parent / "assets" / "extraction"
    # 항목 후보의 출처(M3 소유). import 가 아니라 파일 읽기다 — services/candidates.py 참고.
    # M3 가 이 파일을 옮기면 후보 목록이 빈다. tests/server/test_candidates.py 가 먼저 깨진다
    candidate_rules: Path = BACK_DIR / "rulepack" / "config" / "candidate_rules.json"
    # 시연 자산 루트. replay 의 audio_ref 가 이 아래를 가리킨다(최상위 README).
    # 지금 `scenarios/` 가 비어 있고 R5 가 채우면 그대로 붙는다
    assets_dir: Path = BACK_DIR.parent / "assets"
    # 심사위원이 올린 오디오. assets 는 읽기 전용으로 붙이므로(compose) 쓰는 자리를 따로 둔다
    upload_dir: Path = BACK_DIR.parent / "uploads"
    default_pack_version: str = "DEP-2026.08-v4"
    ws_ping_interval_s: float = 30.0
    # 계약 securitySchemes.bearerAuth. 쓰기 경로(팩 발행·문서 업로드·후보 승인)에만 건다.
    # 비어 있으면 그 경로들이 401 이다 — 열어 두면 배포에서 누구나 팩을 발행한다
    admin_token: str | None = None
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
    # 계약 BUDGET_L3_MS. OpenRouter 왕복이 1.5초를 자주 넘겨 refine 이 통째로 버려졌다 —
    # 실측에 맞춰 3초로 완화했다 (사용자 결정, 월요일 합의 대상)
    l3_budget_ms: float = 3000
    # STT. 키가 비면 오디오 층이 빠지고 ws 가 stt_unavailable 을 낸다(3층 폴백).
    # 기획 11.3: Deepgram nova-3 ko · keyterm·numerals·mip_opt_out
    #   deepgram      스트리밍. APP_STT_API_KEY 가 있어야 한다
    #   openai_file   온프레미스 Qwen3-ASR(vLLM). 화자 분리 구간마다 WAV 하나를
    #                 {APP_STT_BASE_URL}/v1/audio/transcriptions 에 보낸다.
    #                 끊을 자리를 구간에서 얻으므로 APP_DIARIZATION_URL 이 함께 있어야 한다.
    #                 APP_STT_BASE_URL=https://api.openai.com 이면 OpenAI 배치 전사에도 붙는다
    #   openai_realtime  OpenAI Realtime WebSocket 전사(1차 MVP 합의). 어댑터는 아직 없다 —
    #                 services/stt/README.md 의 프로토콜대로 구현해 startup._stt 에 끼운다
    stt_provider: Literal["deepgram", "openai_file", "openai_realtime"] = "deepgram"
    stt_api_key: str | None = None
    stt_base_url: str | None = None  # openai_file 전용. 예: http://localhost:8100
    stt_model: str = "nova-3"  # openai_file 이면 예: Qwen/Qwen3-ASR-1.7B
    stt_language: str = "ko"
    # 13장이 라이선스·약관 조건으로 정한 값. 할인을 포기하고 학습 사용을 거부한다.
    # 은행 도입 전제에서 옵션이 아니라 조건이라 기본값을 켜 둔다
    stt_mip_opt_out: bool = True
    # 화자 분리 번호를 teller·customer 로 옮길 때 LLM 에 묻는다. LLM_MODEL 설정을 그대로
    # 쓰므로 그것이 비면 어차피 규칙 폴백(확정 번호가 하나면 반대, 아니면 teller, 낮은
    # 신뢰도)이다. 끄는 자리를 둔 것은 LLM 은 쓰되 화자 추론만 빼고 싶을 때를 위해서다
    speaker_role_judge: bool = True
    # DEC-7. 새 화자 번호의 발화를 역할이 확정될 때까지 붙잡는 상한. LLM 왕복 실측이
    # 1~2초지만(CTX-005) OpenRouter 경유는 2초를 넘기는 일이 있어 3초로 둔다. 넘기면
    # 잠정 라벨(0.2)로 흘려보낸다.
    # 0 으로 두면 붙잡지 않는다 — 첫 발화의 필수 고지·위험 신호는 게이트에 접힌다
    speaker_hold_ms: int = 3000
    # Sortformer 사이드카(`back/sidecar/diarization/`)의 WebSocket. 비면 화자 분리
    # 공급원이 없고, 그러면 발화가 예전대로 teller 고정에 신뢰도 None 으로 나간다
    diarization_url: str | None = None


def get_settings() -> Settings:
    return Settings()
