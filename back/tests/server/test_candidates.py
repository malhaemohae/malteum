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


def test_risk_items_reach_the_review_screen(client):
    """위험 신호도 검수 화면에 떠야 한다.

    계약 후보 `type` 이 `rulepack.schema.json` 과 같은 집합이 되기 전에는 `DEP-RSK-001`
    이 목록에서 통째로 빠졌다. 검수자가 승인할 방법이 없으면 그 항목은 팩에 못 들어가고,
    기획 7.1 ⑦(위험 신호 감지)이 화면에서 통째로 사라진다.
    """
    body = client.get("/api/documents/03_예금거래기본약관/candidates").json()
    codes = {c["suggested_code"]: c for c in body["candidates"]}
    assert "DEP-RSK-001" in codes, "위험 신호 항목이 검수 화면에서 빠졌습니다"
    assert codes["DEP-RSK-001"]["type"] == "risk"


def test_contract_candidate_types_match_the_pack_schema(client):
    """두 계약이 같은 집합을 써야 한다. 갈리면 M3 가 만든 항목을 REST 가 못 나른다."""
    api = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    got = api["paths"]["/documents/{doc_id}/candidates"]["get"]["responses"]["200"]
    item = got["content"]["application/json"]["schema"]["properties"]["candidates"]["items"]
    rest = set(item["properties"]["type"]["enum"])

    pack = json.loads((CONTRACTS / "rulepack.schema.json").read_text(encoding="utf-8"))
    found = _find_item_type_enum(pack)
    assert found, "rulepack.schema.json 에서 item.type enum 을 못 찾았습니다"
    assert rest == found, f"REST {sorted(rest)} ↔ 팩 {sorted(found)}"


def _find_item_type_enum(node) -> set[str] | None:
    """`rulepack.schema.json` 의 item.type enum. 구조가 바뀌어도 찾게 훑는다."""
    if isinstance(node, dict):
        prop = node.get("properties", {}).get("type")
        if isinstance(prop, dict) and "required" in (prop.get("enum") or []):
            return set(prop["enum"])
        for value in node.values():
            found = _find_item_type_enum(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_item_type_enum(value)
            if found:
                return found
    return None


def test_unknown_document_is_empty_not_an_error(client):
    """문서 목록에 없는 id 는 후보가 없을 뿐이다. 404 로 만들면 화면이 빈 화면과 오류를
    구분해서 처리해야 하는데, 둘 다 "보여줄 후보 없음" 으로 같다."""
    body = client.get("/api/documents/NO-SUCH-DOC/candidates").json()
    assert body == {"candidates": []}


def test_response_has_no_field_outside_the_contract(client, schema):
    """계약 스키마에 없는 키를 얹지 않는다.

    스키마가 `additionalProperties: false` 가 아니라 검증은 통과하지만, 계약에 없는
    값을 화면이 받으면 그 값에 코드가 얹히고 나중에 계약을 맞출 때 화면을 고치게 된다.
    """
    allowed = set(schema["properties"])
    body = client.get(f"/api/documents/{DEPOSIT}/candidates").json()
    assert set(body) <= allowed, f"계약 밖 키: {sorted(set(body) - allowed)}"

    item_props = set(schema["properties"]["candidates"]["items"]["properties"])
    for candidate in body["candidates"]:
        extra = set(candidate) - item_props
        assert not extra, f"후보에 계약 밖 키: {sorted(extra)}"


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

    # 두 번째 승인은 멱등이다. 계약이 이 경로에 200·400 만 두어 409 를 낼 자리가 없다
    again = client.post(_approve_url(cid), json={"approved_by": "딴사람"}, headers=_auth())
    assert again.status_code == 200
    assert again.json()["approved_at"] == got.json()["approved_at"], (
        "두 번째 승인이 기록을 덮었습니다. 누가 언제 승인했는지가 증빙이라 첫 기록이 남아야 한다"
    )
