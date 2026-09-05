"""부팅 예열. 첫 상담이 임베딩 모델 로딩을 기다리지 않는다는 것을 지킨다.

실측(2026-09-06): sentence-transformers 첫 사용까지 26.5초. 그 로딩이 `registry.open`
안에서 일어나면 동기 호출이라 이벤트 루프 전체가 그동안 멈춘다.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from server.bootstrap.warmup import Warmup, warm


def _runtime(loaded: list[str], *, versions: list[str] | None = None, boom: str | None = None):
    def pack(version: str):
        if boom is not None and version == boom:
            raise RuntimeError("팩을 읽지 못했습니다")
        loaded.append(version)

    rows = [{"pack_version": v} for v in (versions if versions is not None else [])]
    return SimpleNamespace(
        registry=SimpleNamespace(pack=pack),
        pack_store=SimpleNamespace(list=lambda code, latest: rows),
        warmup=Warmup(),
    )


def _settings(default: str = "DEP-DEFAULT"):
    return SimpleNamespace(default_pack_version=default, embedding_model="e5-small")


def test_warms_every_latest_pack_so_the_first_session_finds_them_loaded():
    loaded: list[str] = []
    runtime = _runtime(loaded, versions=["DEP-2026.08-v6", "LOAN-2026.08-v7"])
    asyncio.run(warm(runtime, _settings()))
    assert loaded == ["DEP-2026.08-v6", "LOAN-2026.08-v7"]
    assert runtime.warmup.ready is True
    assert runtime.warmup.versions == ("DEP-2026.08-v6", "LOAN-2026.08-v7")
    assert runtime.warmup.error is None


def test_falls_back_to_the_default_pack_when_the_catalog_is_empty():
    loaded: list[str] = []
    runtime = _runtime(loaded, versions=[])
    asyncio.run(warm(runtime, _settings("DEP-DEFAULT")))
    assert loaded == ["DEP-DEFAULT"]
    assert runtime.warmup.ready is True


def test_catalog_failure_still_warms_the_default_pack():
    loaded: list[str] = []
    runtime = _runtime(loaded)

    def explode(code, latest):
        raise RuntimeError("DB 없음")

    runtime.pack_store.list = explode
    asyncio.run(warm(runtime, _settings("DEP-DEFAULT")))
    assert loaded == ["DEP-DEFAULT"]
    assert runtime.warmup.ready is True


def test_a_broken_pack_does_not_stop_the_others_or_the_server():
    loaded: list[str] = []
    runtime = _runtime(loaded, versions=["BROKEN", "DEP-2026.08-v6"], boom="BROKEN")
    asyncio.run(warm(runtime, _settings()))
    assert loaded == ["DEP-2026.08-v6"]
    assert runtime.warmup.ready is True  # 하나라도 데웠으면 판정은 돈다
    assert runtime.warmup.error is not None and "BROKEN" in runtime.warmup.error


def test_every_pack_failing_leaves_not_ready_without_raising():
    loaded: list[str] = []
    runtime = _runtime(loaded, versions=["BROKEN"], boom="BROKEN")
    asyncio.run(warm(runtime, _settings()))
    assert loaded == []
    assert runtime.warmup.ready is False
    assert runtime.warmup.error is not None


def test_health_reports_embedding_only_when_it_is_configured():
    """계약의 `checks.embedding` 자리. 예열 전에는 준비되지 않았음을 그대로 알린다."""
    from fastapi.testclient import TestClient

    from server.bootstrap.settings import Settings
    from server.main import create_app

    settings = Settings(event_store="memory", database_url="postgresql+psycopg://x/y")
    with TestClient(create_app(settings)) as client:
        checks = client.get("/api/health").json()["checks"]
    # 임베딩을 안 쓰는 설정에서는 키 자체가 없다
    assert ("embedding" in checks) is bool(settings.embedding_model)
