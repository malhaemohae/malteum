"""서버 테스트는 개발자의 .env 에 있는 실물 어댑터 설정을 무시한다. 네트워크 없이 부팅해야 한다."""

import pytest


@pytest.fixture(autouse=True)
def _no_live_adapters(monkeypatch):
    monkeypatch.setenv("APP_LLM_MODEL", "")
    monkeypatch.setenv("APP_EMBEDDING_MODEL", "")
