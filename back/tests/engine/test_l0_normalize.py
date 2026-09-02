"""L0 정규화. 오인식 교정은 한 어절, 붙여쓰기 교정은 정확 일치만 (과교정 회귀 포함)."""

from __future__ import annotations

from engine.tiers.l0_normalize import JargonIndex, normalize

INDEX = JargonIndex(
    ["우대이자율", "기본이자율", "만기후이자율", "중도해지이율", "차감률", "약정이율"]
)


def test_misheard_single_word_is_corrected():
    text, reps = normalize("차감율 적용이 어떻게 되나요", INDEX)
    assert text == "차감률 적용이 어떻게 되나요"
    assert [(r.original, r.replaced) for r in reps] == [("차감율", "차감률")]


def test_ambiguous_word_left_for_llm_corrector():
    # "차감눌" 은 확신 임계 아래 → L0 은 손대지 않고 refine 의 교정 후보로만 올라간다
    text, reps = normalize("차감눌 적용이 어떻게 되나요", INDEX)
    assert text == "차감눌 적용이 어떻게 되나요" and reps == []


def test_spaced_exact_term_is_joined():
    text, _ = normalize("우대 이자 율은 적용이 안 됩니다", INDEX)
    assert text.startswith("우대이자율은")


def test_fuzzy_multiword_join_is_rejected():
    # 회귀: "아까 중도해지 이자는" 이 "중도해지이율자는" 으로 뭉개지던 과교정
    src = "그리고 아까 중도해지 이자는, 한 달 안에 해지하시면 연 0.10% 입니다."
    text, reps = normalize(src, INDEX)
    assert text == src and reps == []


def test_numbers_survive():
    text, _ = normalize("연 0.10% 입니다", INDEX)
    assert "0.10%" in text


def test_exact_term_untouched():
    text, reps = normalize("중도해지이율 안내드릴게요", INDEX)
    assert text == "중도해지이율 안내드릴게요" and reps == []
