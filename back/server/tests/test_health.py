from fastapi.testclient import TestClient

from server.main import create_app


def test_health_ok():
    with TestClient(create_app()) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "version", "checks"}
