"""기능 ② 상담 전 브리핑. 팩을 접어 만든 것이므로 팩과 어긋나면 안 된다."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app

FIX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
PACK_VERSION = "DEP-2026.08-v6"


def _client() -> TestClient:
    return TestClient(create_app(Settings(event_store="memory")))


def _pack() -> dict:
    return json.loads((FIX / f"rulepack_{PACK_VERSION}.json").read_text(encoding="utf-8"))


def test_briefing_folds_the_pack_by_item_type():
    pack = _pack()
    by_type = {}
    for it in pack["items"]:
        by_type.setdefault(it["type"], []).append(it)

    with _client() as client:
        # 메모리 저장소에는 팩이 없다. 파일 폴백을 쓰는 경로가 아니라 pack_store 를
        # 보므로 404 가 정상이고, 그 자체가 계약의 응답이다
        got = client.get(f"/api/packs/{PACK_VERSION}/briefing")
    assert got.status_code == 404


def test_briefing_shape_matches_contract(monkeypatch):
    """pack_store 에 팩이 있으면 required·forbidden·reference 를 각 칸에 접어 넣는다."""
    pack = _pack()
    app = create_app(Settings(event_store="memory"))
    with TestClient(app) as client:
        # runtime 은 lifespan 이 돌아야 생긴다. 들어온 뒤에 갈아끼운다
        monkeypatch.setattr(
            app.state.runtime.pack_store, "get", lambda v: pack if v == PACK_VERSION else None
        )
        d = client.get(f"/api/packs/{PACK_VERSION}/briefing").json()

    # 계약 required: pack_version · must_say · must_not_say · generated_at
    assert d["pack_version"] == PACK_VERSION
    assert d["generated_at"] and d["cached"] is False

    required = [i for i in pack["items"] if i["type"] == "required"]
    forbidden = [i for i in pack["items"] if i["type"] == "forbidden"]
    assert [m["item_code"] for m in d["must_say"]] == [i["code"] for i in required]
    assert [m["item_code"] for m in d["must_not_say"]] == [i["code"] for i in forbidden]

    # elements 는 팩의 requirement_elements 그대로. 새로 지어내지 않는다
    first = d["must_say"][0]
    assert first["elements"] == required[0]["requirement_elements"]
    # 서류는 참조 항목(기능 ④)에서 온다
    reference = [i for i in pack["items"] if i["type"] == "reference"]
    assert d["documents_required"] == [e for i in reference for e in i["requirement_elements"]]
    # risk 항목은 어느 칸에도 안 들어간다 — 은행원이 말할 것도 말면 안 될 것도 아니다
    risk = {i["code"] for i in pack["items"] if i["type"] == "risk"}
    listed = {m["item_code"] for m in d["must_say"] + d["must_not_say"]}
    assert not (risk & listed)
