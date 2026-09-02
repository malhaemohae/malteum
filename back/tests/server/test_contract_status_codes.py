"""서버가 내는 상태 코드가 계약이 정의한 것 안에 있는지.

계약(`api.openapi.yaml`)이 경로마다 응답 코드를 적어 두었다. 거기 없는 코드를 내면
화면은 계약에 없는 분기를 짜야 하고, 그 분기는 계약을 다시 읽어도 안 나온다.

**계약 밖으로 나가는 자리는 이 파일에 이름을 적어야 통과한다.** 적는 행위가 곧 "이건
계약에 추가해야 한다" 는 목록이 된다. 조용히 하나 더 늘어나는 것을 막는 것이 목적이다.
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app

BACK = Path(__file__).resolve().parents[2]
CONTRACTS = BACK / "contracts"
TOKEN = "test-admin-token"
DEPOSIT = "05_상품설명서_정기예금"
NO = "NOSUCH-0001"


# 계약이 정의하지 않았지만 서버가 내야만 하는 코드. 각각 왜 뺄 수 없는지 적는다.
#
# **2026-09-02 에 비었다.** 여기 있던 열 개를 계약이 흡수했다 — 404 여섯, 415, 422 둘,
# 401 둘. 계약에 `NotFound`·`ValidationFailed`·`Unauthorized` 응답 컴포넌트가 있으므로
# 새 항목은 그것을 `$ref` 하면 된다.
#
# 비어 있는 것이 정상이다. 여기에 무언가 적어야 하는 상황이면 계약을 먼저 보라.
BEYOND_CONTRACT: dict[tuple[str, str, int], str] = {}


@pytest.fixture(scope="module")
def declared() -> dict[tuple[str, str], set[int]]:
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    out = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                out[(method.upper(), path)] = {int(c) for c in operation.get("responses", {})}
    return out


@pytest.fixture(scope="module")
def probes():
    """각 경로를 실패 쪽으로 한 번씩 두드린다. (메서드, 계약 경로, 상황, 응답)"""
    settings = Settings(event_store="memory", admin_token=TOKEN)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    approve = "/documents/{doc_id}/candidates/{candidate_id}/approve"
    bad_pack = json.loads(
        (CONTRACTS / "fixtures" / "rulepack_DEP-2026.08-v4.json").read_text("utf-8")
    )
    bad_pack["items"][0]["evidence"]["span"] = "원문에 없는 문장입니다"

    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        cid = c.get(f"/api/documents/{DEPOSIT}/candidates").json()["candidates"][0]["candidate_id"]
        base = f"/api/documents/{DEPOSIT}/candidates"
        yield [
            ("GET", "/packs/{pack_version}", "없는 팩", c.get(f"/api/packs/{NO}")),
            (
                "GET",
                "/packs/{pack_version}/briefing",
                "없는 팩",
                c.get(f"/api/packs/{NO}/briefing"),
            ),
            ("GET", "/sessions/{session_id}", "없는 세션", c.get(f"/api/sessions/{NO}")),
            (
                "GET",
                "/sessions/{session_id}/events",
                "없는 세션",
                c.get(f"/api/sessions/{NO}/events"),
            ),
            (
                "GET",
                "/sessions/{session_id}/report",
                "없는 세션",
                c.get(f"/api/sessions/{NO}/report"),
            ),
            ("GET", "/evidence/{evidence_ref}", "없는 근거", c.get(f"/api/evidence/{NO}")),
            (
                "GET",
                "/documents/{doc_id}/pages/{page}.png",
                "없는 문서",
                c.get(f"/api/documents/{NO}/pages/1.png"),
            ),
            ("POST", "/sessions", "본문 누락", c.post("/api/sessions", json={})),
            (
                "POST",
                "/sessions/{session_id}/audio",
                "WAV 아님",
                c.post(f"/api/sessions/{NO}/audio", files={"file": ("a.wav", b"x", "audio/wav")}),
            ),
            ("POST", "/packs/publish", "토큰 없음", c.post("/api/packs/publish", json={})),
            (
                "POST",
                "/packs/publish",
                "스키마 위반",
                c.post("/api/packs/publish", json={"pack_version": "X"}, headers=auth),
            ),
            (
                "POST",
                "/packs/publish",
                "근거 불일치 (P4)",
                c.post("/api/packs/publish", json=bad_pack, headers=auth),
            ),
            (
                "POST",
                approve,
                "토큰 없음",
                c.post(f"{base}/{cid}/approve", json={"approved_by": "x"}),
            ),
            (
                "POST",
                approve,
                "없는 후보",
                c.post(f"{base}/nope/approve", json={"approved_by": "x"}, headers=auth),
            ),
            (
                "POST",
                approve,
                "approved_by 누락",
                c.post(f"{base}/{cid}/approve", json={}, headers=auth),
            ),
        ]


def test_every_status_code_is_in_the_contract(declared, probes):
    strays = []
    for method, path, why, got in probes:
        if got.status_code in declared[(method, path)]:
            continue
        if (method, path, got.status_code) in BEYOND_CONTRACT:
            continue
        strays.append(
            f"{method} {path} ({why}) → {got.status_code}, "
            f"계약은 {sorted(declared[(method, path)])}"
        )
    assert not strays, (
        "계약에 없는 상태 코드입니다. 계약에 넣거나 BEYOND_CONTRACT 에 이유를 적으세요:\n"
        + "\n".join(strays)
    )


def test_every_error_body_is_the_contract_error_shape(declared, probes):
    """계약 밖 코드로 나가더라도 본문 모양은 계약 `Error` 다. ws 와 같은 code 집합을 쓴다."""
    spec = yaml.safe_load((CONTRACTS / "api.openapi.yaml").read_text(encoding="utf-8"))
    codes = set(spec["components"]["schemas"]["Error"]["properties"]["code"]["enum"])
    for method, path, why, got in probes:
        if got.status_code < 400:
            continue
        body = got.json()
        assert set(body) >= {"code", "message"}, f"{method} {path} ({why}): {body}"
        assert body["code"] in codes, f"{method} {path} ({why}): 계약 enum 밖 {body['code']}"


def test_beyond_contract_list_has_no_stale_entry(declared, probes):
    """계약이 그 코드를 받아들이면 여기서 지워야 한다. 안 지우면 목록이 낡는다."""
    stale = [
        f"{method} {path} {status}"
        for (method, path, status) in BEYOND_CONTRACT
        if status in declared.get((method, path), set())
    ]
    assert not stale, "계약이 이제 정의합니다. BEYOND_CONTRACT 에서 지우세요:\n" + "\n".join(stale)
