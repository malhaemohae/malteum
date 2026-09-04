"""후보 규칙의 L1 패턴이 요건 요소를 빈틈없이 덮는지 본다.

L1 패턴이 없는 항목은 엔진이 요건 요소 이름을 임시 키워드로 쓰며 `[DUMMY]` 경고를
낸다(`engine/pack/compiler.py`). 그러면 은행원이 "변동 가능성" 이라는 요소 이름을
글자 그대로 말해야만 잡히고, 나머지는 전부 L3(LLM) 몫이 된다. 2026-09-02 시연
대본을 엔진에 통과시켜 보니 대출 팩 6항목이 그 상태였다.

여기서 세 가지를 못박는다. 판정 대상 항목(required·forbidden·risk)은 패턴이 있어야
하고, required 는 요소마다 하나 이상 있어야 하며, 정규식은 컴파일돼야 한다. 그리고
대표 문장 하나씩으로 패턴이 실제 상담 말투를 잡는지, 무관·정정 문장은 안 잡는지 본다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from rulepack import paths

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES = paths.config_dir(REPO_ROOT) / "candidate_rules.json"

# 항목 코드 → 은행원이 실제로 할 만한 한 문장. 모든 요건 요소를 L1 만으로 채워야 한다
POSITIVE = {
    "LOAN-INT-001": "변동금리라서 기준금리가 바뀌면 고객님 금리도 바뀔 수 있습니다.",
    "LOAN-RDR-001": "신용상태가 좋아지면 금리인하요구를 하실 수 있고, 대상이 아닌 상품도 있습니다.",
    "LOAN-ARR-001": "연체하시면 대출이자율에 연체가산이자율이 더해집니다.",
    "LOAN-PRE-001": "3년 안에 일찍 갚으시면 중도상환해약금이 붙을 수 있습니다.",
    "LOAN-DSR-001": "DSR을 산출해서 심사에 활용합니다.",
    "LOAN-WDR-001": "14일 안에 청약철회 의사를 밝히고 대출금을 반환하시면 됩니다.",
    "LOAN-CIC-001": "심사를 위해 신용정보를 조회하니 동의가 필요합니다.",
    "LOAN-BAN-001": "심사는 무조건 승인됩니다.",
    "LOAN-RSK-001": "다른 상환방식은 안 됩니다.",
}

# 금지 패턴에 걸리면 안 되는 은행원 문장. 정정·정상 안내가 위반으로 뜨면 경보 무시가 시작된다
FORBIDDEN_NEGATIVE = (
    "정확히는 내부 결재 전이라 확정은 아니고, 심사 결과에 따라 달라질 수 있습니다.",
    "상환은 원리금균등으로만 가능합니다.",
    "갚는 방법은 고객님이 원하시는 쪽으로 고르실 수 있습니다.",
    "네, 잠시만 기다려 주세요. 조회해 보겠습니다.",
)

# 기획 9장 B 표와 골든셋의 단정 표현. L1 정규식이 잡아야 하는 것
FORBIDDEN_POSITIVE = (
    "이 금리로 확정이라고 보시면 돼요.",
    "심사는 걱정 안 하셔도 돼요, 통과된 거나 다름없어요.",
    "상환 방식은 저희가 정한 대로 하셔야 합니다.",
)


@pytest.fixture(scope="module")
def rules() -> dict[str, list[dict]]:
    return json.loads(RULES.read_text(encoding="utf-8"))["products"]


def _compiled(rule: dict) -> list[tuple[re.Pattern[str], str | None]]:
    out = []
    for p in rule.get("l1_patterns", []):
        value = re.escape(p["value"]) if p["kind"] == "keyword" else p["value"]
        flags = re.IGNORECASE if "i" in p.get("flags", "") else 0
        out.append((re.compile(value, flags), p.get("element")))
    return out


def _hit_elements(rule: dict, text: str) -> set[str]:
    return {el for rx, el in _compiled(rule) if el and rx.search(text)}


def test_judged_items_have_patterns_for_every_element(rules) -> None:
    """판정 대상 항목은 패턴이 있어야 하고, required 는 요소마다 하나 이상."""
    for product, items in rules.items():
        for rule in items:
            if rule.get("type") not in ("required", "forbidden", "risk"):
                continue
            if rule["code"].endswith("-REJ-001"):
                continue  # 자동 폐기 부정 표본
            patterns = rule.get("l1_patterns", [])
            assert patterns, f"{product} {rule['code']}: l1_patterns 없음"
            for p in patterns:
                assert p["element"] in rule["requirements"], (
                    f"{rule['code']}: 패턴 element '{p['element']}' 가 requirements 에 없음"
                )
                if p["kind"] == "regex":
                    re.compile(p["value"])  # 안 되면 여기서 예외
            if rule["type"] == "required":
                covered = {p["element"] for p in patterns}
                missing = set(rule["requirements"]) - covered
                assert not missing, f"{rule['code']}: 패턴 없는 요소 {sorted(missing)}"


def test_loan_patterns_catch_natural_teller_sentences(rules) -> None:
    """대표 문장 하나로 모든 요소가 채워져야 L1 met 이 가능하다(요소 1개 히트는 판정 안 함)."""
    by_code = {r["code"]: r for r in rules["loan"]}
    for code, sentence in POSITIVE.items():
        rule = by_code[code]
        hit = _hit_elements(rule, sentence)
        if rule["type"] == "required":
            assert hit == set(rule["requirements"]), (
                f"{code}: '{sentence}' 가 채운 요소 {sorted(hit)} != {rule['requirements']}"
            )
        else:
            # 금지는 요소 하나만 걸려도 suspected 다 (matcher.forbidden_verdict)
            assert hit, f"{code}: '{sentence}' 를 못 잡음"


def test_loan_forbidden_patterns_do_not_hit_corrections(rules) -> None:
    forbidden = [r for r in rules["loan"] if r["type"] == "forbidden"]
    for text in FORBIDDEN_NEGATIVE:
        for rule in forbidden:
            assert not _hit_elements(rule, text), f"{rule['code']} 가 정상 문장을 잡음: {text}"


def test_loan_forbidden_patterns_hit_known_assertions(rules) -> None:
    forbidden = [r for r in rules["loan"] if r["type"] == "forbidden"]
    for text in FORBIDDEN_POSITIVE:
        assert any(_hit_elements(rule, text) for rule in forbidden), f"단정 표현을 못 잡음: {text}"


def test_dsr_pattern_tolerates_spaced_transcription(rules) -> None:
    """Qwen3-ASR 이 B02 를 "DSL 총 부채 원리금 상환 비율" 로 냈다(2026-09-04 E2E). 'DSR' 은
    빗나가도 한글 풀이가 띄어 전사된 채로 잡혀야 L1 met 이 나고, 그래야 B03 되물음의
    재진술 카드가 뜬다(되물음 대상은 이미 met·partial 인 항목에서만 고른다)."""
    rule = next(r for r in rules["loan"] if r["code"] == "LOAN-DSR-001")
    said = "먼저 소득과 기존 대출을 확인해서 DSL 총 부채 원리금 상환 비율을 산출하고 "
    said += "심사에 활용합니다."
    assert _hit_elements(rule, said) == set(rule["requirements"])
