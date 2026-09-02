"""항목 후보 조회와 승인.

계약이 이 경로의 존재 이유를 적어 두었다 — "아직 팩이 아니다. **사람이 승인해야 팩에
들어간다. 이 경계가 P4 를 지키는 지점이다.**"

여기서 지키는 것 넷:
  1. 응답이 계약 스키마를 만족한다 (손으로 적은 기대값이 아니라 계약 파일로 대조)
  2. 자동 폐기된 후보를 숨기지 않는다 (기획 8.2 의 "P4 의 시각 증거")
  3. `span_verified=false` 는 승인되지 않는다 (계약이 400 을 명시)
  4. 후보의 출처 파일이 사라지면 조용히 비지 않고 여기서 깨진다
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from server.bootstrap.settings import Settings
from server.main import create_app
from server.services import candidates

BACK = Path(__file__).resolve().parents[2]
CONTRACTS = BACK / "contracts"
RULES = BACK / "rulepack" / "config" / "candidate_rules.json"

DEPOSIT = "05_상품설명서_정기예금"
TOKEN = "test-admin-token"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(event_store="memory", admin_token=TOKEN))) as c:
        yield c


@pytest.fixture(scope="module")
def schema() -> dict:
    """계약의 응답 스키마. `components` 를 함께 얹어 `$ref` 가 풀리게 한다
    (`suggested_code` 가 `#/components/schemas/ItemCode` 를 가리킨다)."""
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    got = spec["paths"]["/documents/{doc_id}/candidates"]["get"]["responses"]["200"]
    return {**got["content"]["application/json"]["schema"], "components": spec["components"]}


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_source_file_is_where_settings_says():
    """M3 가 이 파일을 옮기면 후보 목록이 조용히 빈다. 그 전에 여기서 깨진다.

    `server → rulepack` 은 import-linter 가 막으므로 값을 파일로 읽는다. 코드 의존이
    아니라 경로 의존이라 컴파일 단계에서 안 잡히고, 잡아 줄 자리가 여기뿐이다.
    """
    assert RULES.exists(), f"M3 후보 규칙이 없습니다: {RULES}"
    doc = json.loads(RULES.read_text(encoding="utf-8"))
    assert doc.get("products"), "products 키가 사라졌습니다 — candidates.py 가 빈 목록을 냅니다"
    rule = next(iter(next(iter(doc["products"].values()))))
    for field in ("code", "name", "type", "requirements", "doc_id", "page", "span"):
        assert field in rule, f"계약 후보를 만들 수 없습니다. 규칙에 {field} 가 없습니다"


def test_response_matches_contract_schema(client, schema):
    got = client.get(f"/api/documents/{DEPOSIT}/candidates")
    assert got.status_code == 200
    Draft202012Validator(schema).validate(got.json())


def test_rejected_candidates_are_shown_not_filtered(client):
    """기획 8.2 가 S4 에 요구하는 "자동 폐기 행 노출(P4 의 시각 증거)".

    걸러서 보내면 화면이 증거를 못 보여준다. M3 가 심어 둔 부정 표본
    `DEP-REJ-001`(원문에 없는 문장)이 그 증거다 — rulepack/docs/STATUS.md.
    """
    body = client.get(f"/api/documents/{DEPOSIT}/candidates").json()
    rejected = [c for c in body["candidates"] if not c["span_verified"]]
    assert rejected, "자동 폐기 행이 사라졌습니다"
    assert {c["suggested_code"] for c in rejected} == {"DEP-REJ-001"}
    assert all(c["status"] == "rejected" for c in rejected)
    assert all("bbox" not in c["evidence"] for c in rejected), "근거가 없는데 좌표가 붙었습니다"


def test_verified_candidates_carry_coordinates(client):
    """`span_verified` 는 `contracts/find_span.py` 가 뜬 결과다. 통과하면 좌표가 따라온다 —
    화면이 원문 위에 형광펜을 얹는 값이다(기능 ⑭)."""
    body = client.get(f"/api/documents/{DEPOSIT}/candidates").json()
    verified = [c for c in body["candidates"] if c["span_verified"]]
    assert len(verified) == 6
    assert all(len(c["evidence"]["bbox"]) == 4 for c in verified)


def test_risk_type_is_withheld_until_the_contract_carries_it(client):
    """계약 공백. `rulepack.schema.json` 은 `risk` 를 담는데 REST 후보 type 은 3종뿐이다.

    그대로 내보내면 계약 enum 밖이라 뺀다. **빼되 숨기지 않는다** — 조용히 사라지면
    화면에서 항목 하나가 없는 것을 아무도 눈치채지 못한다.

    계약에 `risk` 가 추가되면 이 테스트가 깨진다. 그때 이 테스트를 지우는 것이 맞다.
    """
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    got = spec["paths"]["/documents/{doc_id}/candidates"]["get"]["responses"]["200"]
    item = got["content"]["application/json"]["schema"]["properties"]["candidates"]["items"]
    assert "risk" not in item["properties"]["type"]["enum"], (
        "계약이 risk 를 받게 됐습니다. candidates.py 의 보류를 지우고 이 테스트도 지우세요"
    )

    body = client.get("/api/documents/03_예금거래기본약관/candidates").json()
    assert [w["suggested_code"] for w in body["withheld"]] == ["DEP-RSK-001"]
    assert "risk" not in {c["type"] for c in body["candidates"]}


def test_unknown_document_is_empty_not_an_error(client):
    """문서 목록에 없는 id 는 후보가 없을 뿐이다. 404 로 만들면 화면이 빈 화면과 오류를
    구분해서 처리해야 하는데, 둘 다 "보여줄 후보 없음" 으로 같다."""
    body = client.get("/api/documents/NO-SUCH-DOC/candidates").json()
    assert body == {"candidates": [], "withheld": []}


def test_candidate_id_survives_a_rebuild():
    """무작위로 매기면 어제 승인한 후보가 오늘 다른 후보가 된다. 승인 기록이 이 id 로 남는다."""
    first = candidates.candidate_id(DEPOSIT, "DEP-INT-001")
    assert first == candidates.candidate_id(DEPOSIT, "DEP-INT-001")
    assert first != candidates.candidate_id(DEPOSIT, "DEP-INT-002")
    assert first != candidates.candidate_id("06_상품설명서_가계대출", "DEP-INT-001")


# --- 승인 -------------------------------------------------------------------


def _candidate(client, *, verified: bool) -> dict:
    body = client.get(f"/api/documents/{DEPOSIT}/candidates").json()
    return next(c for c in body["candidates"] if c["span_verified"] is verified)


def _approve_url(cid: str) -> str:
    return f"/api/documents/{DEPOSIT}/candidates/{cid}/approve"


def test_approve_requires_a_token(client):
    """계약 securitySchemes: 후보 승인은 쓰기 경로다."""
    target = _candidate(client, verified=True)
    got = client.post(_approve_url(target["candidate_id"]), json={"approved_by": "노순혁"})
    assert got.status_code == 401


def test_approve_rejects_a_candidate_without_evidence(client):
    """**이 400 이 이 경로의 존재 이유다.** 계약: "span_verified 가 false 인 후보는 400
    으로 거절한다." 여기가 뚫리면 P4 가 승인 버튼 하나로 뚫린다."""
    target = _candidate(client, verified=False)
    got = client.post(
        _approve_url(target["candidate_id"]), json={"approved_by": "노순혁"}, headers=_auth()
    )
    assert got.status_code == 400
    assert got.json()["code"] == "validation_failed"


def test_approve_unknown_candidate_is_404(client):
    got = client.post(_approve_url("no-such-candidate"), json={"approved_by": "x"}, headers=_auth())
    assert got.status_code == 404
    assert got.json()["code"] == "not_found"


def test_approve_needs_an_approver(client):
    """계약 requestBody 가 `approved_by` 를 required 로 둔다. 누가 승인했는지가 증빙이다."""
    target = _candidate(client, verified=True)
    got = client.post(_approve_url(target["candidate_id"]), json={}, headers=_auth())
    assert got.status_code == 422


def test_approve_records_and_shows_up_in_the_listing(client):
    """승인하면 목록이 바뀐다. 화면이 누른 직후 같은 경로를 다시 읽는다."""
    target = _candidate(client, verified=True)
    cid = target["candidate_id"]
    got = client.post(
        _approve_url(cid),
        json={"approved_by": "노순혁", "edits": {"name": "검수자가 고친 이름"}},
        headers=_auth(),
    )
    assert got.status_code == 200
    assert got.json()["candidate_id"] == cid
    assert got.json()["status"] == "approved"
    assert got.json()["approved_at"]

    body = client.get(f"/api/documents/{DEPOSIT}/candidates").json()
    after = next(c for c in body["candidates"] if c["candidate_id"] == cid)
    assert after["status"] == "approved"
    assert after["name"] == "검수자가 고친 이름", "검수자가 고친 내용이 목록에 안 얹혔습니다"

    # 두 번째 승인은 거절한다. 누가 언제 승인했는지가 증빙이라 조용히 덮이면 안 된다
    again = client.post(_approve_url(cid), json={"approved_by": "딴사람"}, headers=_auth())
    assert again.status_code == 409
    assert again.json()["code"] == "conflict"
