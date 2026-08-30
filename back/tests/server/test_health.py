"""/health 의 응답 모양. 계약은 부분 장애를 checks 로 구분하고 status 로 요약한다."""

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
