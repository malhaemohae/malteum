"""쓰기 경로의 토큰. 계약 `securitySchemes.bearerAuth` 가 정한 범위 그대로.

계약: "심사위원이 로그인 없이 시연할 수 있어야 하므로 조회·세션 시작은 security 를 비워
두고, 문서 업로드·후보 승인·팩 발행만 토큰을 요구한다."

**조회가 잠기면 심사가 막힌다**는 것이 이 테스트의 절반이다.
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
TOKEN = "test-admin-token"
PACK = json.loads((CONTRACTS / "fixtures" / "rulepack_DEP-2026.08-v6.json").read_text("utf-8"))


def _client(token: str | None = TOKEN) -> TestClient:
    return TestClient(create_app(Settings(event_store="memory", admin_token=token)))


def test_contract_says_which_paths_need_a_token():
    """계약이 실제로 쓰기 경로만 지정했는지. 여기가 늘면 구현도 따라가야 한다."""
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    guarded = {
        f"{verb.upper()} {path}"
        for path, ops in spec["paths"].items()
        for verb, op in ops.items()
        if verb in ("get", "post") and op.get("security") != []
    }
    assert guarded == {
        "POST /packs/publish",
        "POST /documents",
        "GET /documents/{doc_id}/extraction",
        "GET /documents/{doc_id}/candidates",
        "POST /documents/{doc_id}/candidates/{candidate_id}/approve",
    }


@pytest.mark.parametrize(
    "headers",
    # HTTP 헤더는 latin-1 이라 한글을 못 넣는다. 값 자체는 ASCII 로 둔다
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": TOKEN}],
    ids=["없음", "틀린값", "Bearer 없음"],
)
def test_publish_rejects_without_a_valid_token(headers):
    with _client() as client:
        got = client.post("/api/packs/publish", json=PACK, headers=headers)
    assert got.status_code == 401
    assert got.json()["code"] == "validation_failed"


def test_publish_rejects_when_token_is_not_configured():
    """설정을 안 했으면 통과가 아니라 거절이다. 열어 두면 배포에서 누구나 발행한다."""
    with _client(token=None) as client:
        got = client.post(
            "/api/packs/publish", json=PACK, headers={"Authorization": f"Bearer {TOKEN}"}
        )
    assert got.status_code == 401
    assert "APP_ADMIN_TOKEN" in got.json()["message"]


@pytest.mark.parametrize(
    "path",
    ["/api/health", "/api/packs", "/api/presets", "/api/documents", "/api/sessions"],
)
def test_read_paths_stay_open(path):
    """심사위원은 로그인 없이 본다. 조회가 잠기면 심사가 막힌다."""
    with _client() as client:
        assert client.get(path).status_code == 200


def test_session_start_stays_open():
    with _client() as client:
        assert client.post("/api/sessions", json={"mode": "text"}).status_code == 201
