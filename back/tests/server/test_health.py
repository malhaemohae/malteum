"""/health 의 응답 모양. 계약은 부분 장애를 checks 로 구분하고 status 로 요약한다."""

from pathlib import Path

from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app


def _client(**overrides) -> TestClient:
    # CI 에 postgres 가 없다. 저장소가 살아 있는 경우를 memory 로 만든다
    return TestClient(create_app(Settings(event_store="memory", **overrides)))


def test_health_ok():
    with _client() as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "version", "checks"}
    assert body["checks"]["db"] == "ok"


def test_health_degraded_when_store_is_down():
    """저장소가 죽으면 degraded 다. 접속 보장 기간의 외부 감시가 이 값을 본다."""
    with _client() as client:
        client.app.state.runtime.event_store.healthy = lambda: False
        r = client.get("/api/health")
    body = r.json()
    assert r.status_code == 200  # 살아서 답은 한다. 상태로 알린다
    assert body["status"] == "degraded"
    assert body["checks"]["db"] == "fail"


def test_health_matches_the_contract_when_adapters_are_configured():
    """**설정이 있는 쪽이 배포다.** 없는 쪽만 보면 계약 위반이 안 잡힌다.

    실제로 `configured` 를 내보내고 있었고, 계약 enum 은 ok·fail·unconfigured 셋뿐이라
    STT·LLM 이 붙은 배포에서만 어기는 모양이었다. 9/7~9/11 접속 보장의 외부 감시가
    보는 값이라(기획 16 리스크 5) 조용히 틀리면 감시가 무력해진다.
    """
    import yaml
    from jsonschema import Draft202012Validator

    contracts = Path(__file__).resolve().parents[2] / "contracts"
    spec = yaml.safe_load((contracts / "api.openapi.yaml").read_text(encoding="utf-8"))
    got = spec["paths"]["/health"]["get"]["responses"]["200"]
    validator = Draft202012Validator(got["content"]["application/json"]["schema"])

    for label, settings in [
        ("어댑터 없음", Settings(event_store="memory")),
        (
            "어댑터 설정됨 (배포)",
            Settings(event_store="memory", stt_api_key="x", llm_model="qwen/qwen3-32b"),
        ),
    ]:
        with TestClient(create_app(settings)) as client:
            body = client.get("/api/health").json()
        errors = [
            f"/{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(body)
        ]
        assert not errors, f"{label}: {errors}"


def test_missing_admin_token_is_announced_at_boot(caplog):
    """토큰이 없어도 서버는 뜨고 심사 기본 경로는 돈다. 그래서 아무도 눈치채지 못한 채
    배포되고, 팩을 발행하려는 순간에야 401 로 드러난다 — 그때는 시연 중이다."""
    import logging

    with caplog.at_level(logging.WARNING, logger="server.bootstrap.startup"):
        with TestClient(create_app(Settings(event_store="memory", admin_token=None))):
            pass
    assert "APP_ADMIN_TOKEN" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="server.bootstrap.startup"):
        with TestClient(create_app(Settings(event_store="memory", admin_token="set"))):
            pass
    assert "APP_ADMIN_TOKEN" not in caplog.text, "설정했는데도 경고가 납니다"
