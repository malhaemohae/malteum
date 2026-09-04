"""서버 테스트는 개발자의 .env 에 있는 실물 어댑터 설정을 무시한다. 네트워크 없이 부팅해야 한다."""

import pytest


@pytest.fixture(autouse=True)
def _no_live_adapters(monkeypatch):
    monkeypatch.setenv("APP_LLM_MODEL", "")
    monkeypatch.setenv("APP_EMBEDDING_MODEL", "")
    monkeypatch.setenv("APP_STT_API_KEY", "")
    # 온프레미스 경로는 키가 아니라 주소로 붙는다. 키만 지우면 개발자의 .env 에
    # APP_STT_BASE_URL 이 있는 동안 테스트가 그 vLLM 컨테이너로 전사를 보낸다
    monkeypatch.setenv("APP_STT_PROVIDER", "deepgram")
    monkeypatch.setenv("APP_STT_BASE_URL", "")
    monkeypatch.setenv("APP_DIARIZATION_URL", "")
