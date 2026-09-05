"""계약 fixture 팩이 canonical(candidate_rules 재빌드 번들)과 같은지 상시 대조한다.

fixture 는 손으로 옮겨 적는다. 아무 테스트도 둘을 비교하지 않으면 canonical 만
고친 변경이 검색면에 조용히 안 실리고(2026-09-01 예시 보강이 하루 그랬다),
반대로 fixture 를 canonical 에서 다시 만들면 시연용 임시 부채(`DEP-INT-002`
numeric_facts, `contracts/fixtures/README.md` 참조)가 소리 없이 지워진다.
의도된 드리프트를 allowlist 로 못박아 양방향 모두 빨간 테스트가 되게 한다.

대출 fixture(`LOAN-2026.08-v7`, 2026-09-05)와 예금 v5(같은 날)도 같은 대조를 받는다. 서버의
`pack_dir`
이 fixtures 폴더라 이 파일이 시연 서버가 읽는 대출 팩 그 자체다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "back" / "contracts" / "fixtures"

# 상품 → (fixture 파일, 의도된 드리프트, 있어도 없어도 되는 드리프트)
PACKS = {
    # 2026-09-03 예금 v4 를 canonical 에서 다시 발행하면서 옛 원천 0.10% 임시 부채
    # (`DEP-INT-002` numeric_facts · numeric l1 패턴)가 사라졌다. 이제 두 팩 모두
    # 드리프트 0 이 정상이고, 하나라도 생기면 fixture 를 손으로 고친 것이다.
    "deposit": ("rulepack_DEP-2026.08-v5.json", set(), set()),
    "loan": ("rulepack_LOAN-2026.08-v7.json", set(), set()),
}

# compiler._schema_item 이 번들에서 팩으로 옮기는 내용 키. 승인 메타(approved_*)와
# embedding_id 는 컴파일 시점 산물이라 비교 대상이 아니다.
CONTENT_KEYS = (
    "name",
    "type",
    "axis",
    "requirement_elements",
    "legal_basis",
    "evidence",
    "plain_language",
    "numeric_facts",
    "documents_required",
    "forbidden_examples",
    "risk_examples",
    "l1_patterns",
)


def _norm(value):
    """없음(None)과 빈 목록을 같게 본다. 번들은 키를 생략하고 팩은 [] 를 적기도 한다."""
    return None if value in (None, []) else value


@pytest.mark.parametrize("product", sorted(PACKS))
def test_fixture_items_match_canonical(bundles, product) -> None:
    filename, expected_drift, tolerated_drift = PACKS[product]
    pack = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    canonical = {
        item["code"]: item
        for item in bundles[product]["items"]
        if item["status"] == "evidence_verified"
    }
    assert {item["code"] for item in pack["items"]} == set(canonical), (
        f"{product}: fixture 항목 집합이 발행 가능 후보와 다르다"
    )

    drift = {
        (item["code"], key)
        for item in pack["items"]
        for key in CONTENT_KEYS
        if _norm(item.get(key)) != _norm(canonical[item["code"]].get(key))
    }
    assert expected_drift <= drift <= expected_drift | tolerated_drift, (
        f"{product}: 허용 밖 드리프트 {sorted(drift - expected_drift - tolerated_drift)} / "
        f"사라진 의도 드리프트 {sorted(expected_drift - drift)}"
    )
