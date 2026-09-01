"""REST 오류가 계약 `Error` 모양인지.

계약이 이유를 적어 두었다 — "ws_protocol 의 error.code 와 같은 집합을 쓴다. 두 경로에서
코드가 갈라지면 프런트가 분기를 두 번 짠다." FastAPI 기본값 `{"detail": ...}` 을 그대로
두면 화면이 REST 와 ws 에서 다른 모양을 받는다.
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


@pytest.fixture(scope="module")
def codes() -> set[str]:
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    return set(spec["components"]["schemas"]["Error"]["properties"]["code"]["enum"])


TOKEN = "test-admin-token"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(event_store="memory", admin_token=TOKEN))) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/api/sessions/NO-SUCH-SESSION-01",
        "/api/sessions/NO-SUCH-SESSION-01/events",
        "/api/sessions/NO-SUCH-SESSION-01/report",
        "/api/packs/NOSUCH-2026.01-v1",
        "/api/packs/NOSUCH-2026.01-v1/briefing",
        "/api/evidence/NOPE-EVENT-0001",
    ],
)
def test_not_found_uses_contract_error(client, codes, path):
    got = client.get(path)
    assert got.status_code == 404
    body = got.json()
    assert set(body) >= {"code", "message"}, f"계약 필수 필드 누락: {body}"
    assert body["code"] in codes, f"계약 enum 밖: {body['code']}"
    assert body["code"] == "not_found"
    assert body["message"]


def test_validation_error_is_also_contract_shaped(client, codes):
    """요청 자체가 계약과 안 맞을 때도 같은 모양이어야 한다."""
    got = client.post("/api/sessions", json={})  # mode 누락
    assert got.status_code == 422
    body = got.json()
    assert body["code"] in codes and body["code"] == "validation_failed"


def test_conflict_and_detail_survive(client, codes):
    """422 의 rejected_items 처럼 라우터가 실은 detail 이 살아남아야 한다."""
    pack = json.loads((CONTRACTS / "fixtures" / "rulepack_DEP-2026.08-v4.json").read_text("utf-8"))
    pack["items"][0]["evidence"]["span"] = "원문에 없는 문장입니다"
    got = client.post("/api/packs/publish", json=pack, headers={"Authorization": f"Bearer {TOKEN}"})
    assert got.status_code == 422
    body = got.json()
    assert body["code"] in codes
    assert body["detail"]["rejected_items"][0]["item_code"]
