"""숫자 사실(numeric_facts)의 근거가 제 자리를 가리키는지 본다.

숫자 사실은 ⑤ 숫자 오류 감지의 정답이다. 정답의 근거가 틀린 줄을 가리키면 경보 카드의
"근거 원문 보기" 가 숫자 없는 문장에 형광펜을 친다. 2026-09-02 까지 파이프라인이 모든
숫자 사실의 근거를 항목 근거로 덮어써서, 항목 문장 밖에 적힌 수치(연체가산이자율 3%,
청약철회 14일, 세율 15.4%)는 실을 수 없었다. 이제 사실마다 자기 근거를 둘 수 있고
(`pipeline._verify_numeric_fact_evidence`), 여기서 그 경로가 실제로 도는지 못박는다.
"""

from __future__ import annotations

import pytest

# (상품, 항목) → 숫자 사실이 항목 근거와 다른 줄에 있어야 하는 것
OWN_EVIDENCE = {
    ("deposit", "DEP-TAX-001"): (1, "15.4%"),
    ("loan", "LOAN-ARR-001"): (7, "3%"),
    ("loan", "LOAN-WDR-001"): (3, "14일"),
}

# 항목 근거 안에 수치가 있어 근거를 물려받는 것
INHERITED_EVIDENCE = {
    ("deposit", "DEP-PRO-001"),
    ("loan", "LOAN-PRE-001"),
}


def _item(bundles, product, code):
    return next(item for item in bundles[product]["items"] if item["code"] == code)


@pytest.mark.parametrize(("product", "code"), sorted(OWN_EVIDENCE))
def test_fact_with_own_evidence_is_verified_and_located(bundles, product, code) -> None:
    item = _item(bundles, product, code)
    assert item["status"] == "evidence_verified", item.get("reason")
    page, token = OWN_EVIDENCE[(product, code)]
    fact = item["numeric_facts"][0]
    ev = fact["evidence"]
    assert ev["page"] == page
    assert ev["span"] != item["evidence"]["span"], "자기 근거인데 항목 근거와 같다"
    assert len(ev["bbox"]) == 4, "원문 대조가 좌표를 채워야 한다"
    assert token.replace(" ", "") in ev["span"].replace(" ", ""), "근거 줄에 그 수치가 없다"


@pytest.mark.parametrize(("product", "code"), sorted(INHERITED_EVIDENCE))
def test_fact_without_own_evidence_inherits_item_evidence(bundles, product, code) -> None:
    item = _item(bundles, product, code)
    fact = item["numeric_facts"][0]
    assert fact["evidence"]["span"] == item["evidence"]["span"]
    assert fact["evidence"]["page"] == item["evidence"]["page"]


def test_every_fact_value_appears_in_its_evidence(bundles) -> None:
    """라벨·값이 근거 줄에 없으면 컴파일이 막지만, 번들 단계에서 먼저 드러나야 한다.

    값 표기는 컴파일러와 같은 규칙(`_numeric_tokens`: `1억 원`·`100,000,000원` 류)으로 본다.
    """
    from rulepack.compiler import _numeric_tokens

    for product, bundle in bundles.items():
        for item in bundle["items"]:
            for fact in item.get("numeric_facts", []):
                span = fact["evidence"]["span"].replace(" ", "")
                assert fact["label"].replace(" ", "") in span, (product, item["code"])
                tokens = {t.replace(" ", "") for t in _numeric_tokens(fact["value"], fact["unit"])}
                assert any(t in span for t in tokens), (product, item["code"], tokens)


def test_ratio_items_carry_no_numeric_facts(bundles) -> None:
    """산식·비율(약정이율×0.5 류)은 숫자 대조 대상이 아니라 L1 정규식 + L3 판단 몫이다.

    `value + unit` 절대값 모델은 "약정이율의 절반" 을 표현하지 못한다. 억지로 50% 로
    넣으면 은행원이 0.5% 라고 말했을 때 "설명서 기준 50%" 라는 오해를 부르는 경보가
    뜬다(2026-09-03 팀 결정: 수식은 에이전트가 판단).
    """
    for code in ("DEP-INT-002", "DEP-INT-003"):
        item = _item(bundles, "deposit", code)
        assert not item.get("numeric_facts"), f"{code} 는 비율 항목이라 숫자 사실을 두지 않는다"


def test_own_evidence_schema_rejects_page_zero_and_empty_span() -> None:
    """page:0·빈 span 이 여기서 막혀야 `_verify_numeric_fact_evidence` 와
    `find_span`/`count_exact_span` 의 0-페이지 해석 불일치(코드 리뷰 발견, 2026-09-03)로
    새지 않는다. 항목 근거 스키마와 같은 하한을 사실별 근거에도 건다."""
    import jsonschema

    from rulepack.pipeline import CANDIDATE_OUTPUT_SCHEMA

    schema = CANDIDATE_OUTPUT_SCHEMA["properties"]["numeric_facts"]["items"]["properties"][
        "evidence"
    ]
    base = {"doc_id": "05_상품설명서_정기예금", "page": 1, "span": "연 3%"}
    jsonschema.validate(instance=base, schema=schema)  # 정상 값은 통과
    for bad in ({**base, "page": 0}, {**base, "span": ""}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)
