"""숫자 표현·분리 발화의 누락과, 같은 단위의 다른 수치에 대한 오탐 회귀."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from contracts.engine_contract import Utterance
from engine.build import build_engine
from engine.tiers.l1.numeric import said_numbers
from tests.engine.conftest import FIX, PACK_VERSION
from tests.engine.fakes import FakePackSource


@pytest.mark.parametrize(
    "text, expected",
    [
        ("15퍼입니다", [(15.0, "%", "15%")]),
        ("24 퍼", [(24.0, "%", "24%")]),
        ("15.4 퍼센트", [(15.4, "%", "15.4%")]),
        ("연 0.10프로", [(0.1, "%", "0.10%")]),
        ("십오 퍼센트", [(15.0, "%", "15%")]),
        ("이십사퍼", [(24.0, "%", "24%")]),
        ("십오 점 사 퍼센트", [(15.4, "%", "15.4%")]),
        ("영 점 일 프로", [(0.1, "%", "0.1%")]),
        ("백 퍼센트", [(100.0, "%", "100%")]),
        ("14일, 3년, 24개월", [(14.0, "일", "14일"), (3.0, "년", "3년"), (24.0, "개월", "24개월")]),
        ("십오 퍼센트포인트", []),
        ("15퍼센트포인트", []),
        ("15%p", []),
        ("15%p입니다", []),
        ("15퍼포먼스", []),
        ("15퍼센티지", []),
        ("삼십십 퍼센트", []),
        ("이십오점 퍼센트", []),
        ("십오 점 사십 퍼센트", []),
        ("십오 점 사 점 오 퍼센트", []),
        ("일만 오천 퍼센트", []),
        ("15 점 4 퍼센트", [(15.4, "%", "15.4%")]),
        ("15점4퍼센트", [(15.4, "%", "15.4%")]),
        ("십오점4퍼", [(15.4, "%", "15.4%")]),
        ("15점사프로", [(15.4, "%", "15.4%")]),
        ("십5점4퍼센트", []),
        ("십사퍼 센트", [(14.0, "%", "14%")]),
        ("15퍼 센티지", []),
        ("연사점 5%", [(4.5, "%", "4.5%")]),
        ("연사 점 오 퍼센트", [(4.5, "%", "4.5%")]),
        ("연 삼 퍼센트", [(3.0, "%", "3%")]),
        ("-15점4퍼센트", [(-15.4, "%", "-15.4%")]),
        ("+십오점사퍼", [(15.4, "%", "+15.4%")]),
        ("-15%", [(-15.0, "%", "-15%")]),
        ("이자 수익을 설명합니다", []),
    ],
)
def test_number_expressions(text, expected):
    assert said_numbers(text) == expected


@pytest.fixture(scope="module")
def engine(pack_json):
    loan = json.loads((FIX / "rulepack_LOAN-2026.08-v5.json").read_text())
    return build_engine(FakePackSource(pack_json, loan))


def _judge(engine, text, *, previous=(), version=PACK_VERSION, speaker="teller", confidence=0.95):
    pack = engine.load_pack(version)
    state = engine.initial_state("S-NUMERIC", pack, "text")
    for utterance in previous:
        result = engine.judge(utterance, pack, state)
        state = engine.apply(engine.observe(state, utterance), result)
    current = Utterance("U-NUMBER", speaker, text, 5_000, speaker_confidence=confidence)
    result = engine.judge(current, pack, state)
    assert current.text == text  # 숫자 해석이 전사 원문을 교정하지 않는다
    return [a for a in result.alerts if a.alert_type == "number_mismatch"]


TAX_CONTEXT = Utterance(
    "U-TOPIC",
    "teller",
    "받으시는 이자 수익에는 과세가 되는데요.",
    1_000,
    speaker_confidence=0.95,
)


@pytest.mark.parametrize(
    "amount", ["14%", "15퍼", "24퍼", "십오 퍼센트", "십오 점 오 퍼센트", "15점5퍼센트"]
)
def test_split_tax_explanation_keeps_evidence_and_current_utterance(engine, amount):
    alerts = _judge(engine, f"세율은 {amount}입니다.", previous=(TAX_CONTEXT,))
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.item_code == "DEP-TAX-001"
    assert alert.utterance_ref == "U-NUMBER"
    assert alert.evidence is not None and "15.4%" in alert.evidence.span
    assert alert.comparison.reference == "15.4%"
    assert alert.comparison.said == said_numbers(amount)[0][2]


@pytest.mark.parametrize("text", ["과세 세율은 14%입니다.", "정상일반세율은 14퍼입니다."])
def test_explicit_subject_works_without_prior_context(engine, text):
    assert len(_judge(engine, text)) == 1


def test_bare_number_uses_only_immediate_teller_context(engine):
    assert len(_judge(engine, "14퍼입니다.", previous=(TAX_CONTEXT,))) == 1
    assert _judge(engine, "14퍼입니다.") == []


def test_nemotron_split_unit_keeps_tax_context(engine):
    previous = replace(TAX_CONTEXT, text="받으 시는 이 자 수익 에는 과세 가 되는데 요.")
    assert len(_judge(engine, "세율 은 십사퍼 센트 입니다.", previous=(previous,))) == 1


@pytest.mark.parametrize(
    "text", ["15.4퍼입니다.", "십오 점 사 퍼센트입니다.", "15점4퍼센트입니다."]
)
def test_correct_tax_rate_does_not_alert(engine, text):
    assert _judge(engine, text, previous=(TAX_CONTEXT,)) == []


@pytest.mark.parametrize(
    "previous",
    [
        (replace(TAX_CONTEXT, speaker="customer"),),
        (replace(TAX_CONTEXT, speaker_confidence=0.5),),
        (replace(TAX_CONTEXT, t_ms=-30_000),),
        (replace(TAX_CONTEXT, t_ms=6_000),),
        (TAX_CONTEXT, Utterance("U-OTHER", "customer", "네.", 2_000)),
        (TAX_CONTEXT, Utterance("U-OTHER", "teller", "다음 내용을 안내합니다.", 2_000)),
    ],
)
def test_context_is_not_borrowed_across_unreliable_or_unrelated_turns(engine, previous):
    assert _judge(engine, "14퍼입니다.", previous=previous) == []


@pytest.mark.parametrize(
    "text",
    [
        "기본이자율은 3퍼입니다.",
        "주차 할인율은 24퍼입니다.",
        "우대이자율은 2퍼입니다.",
    ],
)
def test_new_subject_does_not_inherit_tax_reference(engine, text):
    assert _judge(engine, text, previous=(TAX_CONTEXT,)) == []


@pytest.mark.parametrize("speaker, confidence", [("customer", 0.95), ("teller", 0.5)])
def test_current_speaker_gate_still_applies(engine, speaker, confidence):
    assert (
        _judge(
            engine,
            "과세 세율은 14퍼입니다.",
            previous=(TAX_CONTEXT,),
            speaker=speaker,
            confidence=confidence,
        )
        == []
    )


@pytest.mark.parametrize(
    "text, said",
    [
        ("약정금리는 5%입니다.", None),
        ("약정금리는 5%, 연체가산금리는 3%입니다.", None),
        ("약정금리는 5%, 연체가산금리는 4퍼입니다.", "4%"),
        ("연체가산이자율은 삼 퍼센트입니다.", None),
        ("연체가산이자율은 사 퍼센트입니다.", "4%"),
    ],
)
def test_loan_rate_is_compared_to_the_matching_fact_only(engine, text, said):
    alerts = _judge(engine, text, version="LOAN-2026.08-v5")
    assert [a.comparison.said for a in alerts] == ([said] if said else [])
    if said:
        assert alerts[0].item_code == "LOAN-ARR-001"
        assert alerts[0].comparison.reference == "연 3%"


def test_split_loan_rate_uses_the_fact_from_the_previous_turn(engine):
    context = replace(TAX_CONTEXT, text="연체가산이자율을 설명드릴게요.")
    alerts = _judge(engine, "4퍼입니다.", previous=(context,), version="LOAN-2026.08-v5")
    assert [a.comparison.said for a in alerts] == ["4%"]


@pytest.mark.parametrize("days, expected", [("14", []), ("15", ["15일"])])
def test_number_before_the_subject_is_still_checked(engine, days, expected):
    alerts = _judge(engine, f"{days}일 이내에 청약철회가 가능합니다.", version="LOAN-2026.08-v5")
    assert [a.comparison.said for a in alerts] == expected


def test_context_gap_is_measured_from_the_end_of_the_previous_utterance(engine):
    previous = replace(TAX_CONTEXT, t_ms=-20_000, duration_ms=22_000)
    assert len(_judge(engine, "14퍼입니다.", previous=(previous,))) == 1


@pytest.mark.parametrize("offset_ms", [0, 500])
def test_sentences_from_one_stt_segment_can_share_or_overlap_timestamps(engine, offset_ms):
    # 2026-09-05 dep-a 음원 실측: 한 전사를 두 문장으로 나누며 양쪽에 같은 t_ms·길이를 준다.
    pack = engine.load_pack(PACK_VERSION)
    previous = replace(TAX_CONTEXT, t_ms=34_295, duration_ms=4_640)
    state = engine.observe(engine.initial_state("S-STT-SPLIT", pack, "replay"), previous)
    current = Utterance(
        "U-NUMBER",
        "teller",
        "세율은 14%입니다.",
        34_295 + offset_ms,
        duration_ms=4_640,
        speaker_confidence=0.95,
    )
    alerts = engine.judge(current, pack, state).alerts
    assert len(alerts) == 1
    assert alerts[0].comparison.said == "14%"
    assert alerts[0].comparison.reference == "15.4%"
    assert alerts[0].utterance_ref == current.utterance_id


def test_ambiguous_previous_subjects_do_not_select_a_reference(pack_json):
    loan = json.loads((FIX / "rulepack_LOAN-2026.08-v5.json").read_text())
    # 테스트 팩에 서로 다른 % 기준 두 개를 함께 넣는다. 공식 fixture 는 변경하지 않는다.
    combined = dict(pack_json, items=[*pack_json["items"], *loan["items"]])
    engine = build_engine(FakePackSource(combined))
    context = replace(TAX_CONTEXT, text="과세와 연체가산이자율을 설명드릴게요.")
    assert _judge(engine, "14퍼입니다.", previous=(context,)) == []


def test_loan_rate_cannot_be_identified_when_both_rate_labels_precede_it(engine):
    assert (
        _judge(engine, "대출이자율과 연체가산이자율은 5%입니다.", version="LOAN-2026.08-v5") == []
    )


def test_fold_restores_numeric_context_without_hidden_engine_state(engine, scenario_a):
    started = scenario_a[0]
    event = {
        "event_id": TAX_CONTEXT.utterance_id,
        "seq_in_session": 2,
        "kind": "utterance",
        "utterance": {
            "speaker": TAX_CONTEXT.speaker,
            "text": TAX_CONTEXT.text,
            "t_ms": TAX_CONTEXT.t_ms,
            "speaker_confidence": TAX_CONTEXT.speaker_confidence,
        },
    }
    folded = engine.fold([started, event])
    pack = engine.load_pack(PACK_VERSION)
    current = Utterance("U-NUMBER", "teller", "14퍼입니다.", 5_000)
    observed = engine.observe(engine.initial_state("S-NUMERIC", pack, "text"), TAX_CONTEXT)
    restored = engine.judge(current, pack, folded).alerts
    assert restored == engine.judge(current, pack, observed).alerts
    assert len(restored) == 1
    assert engine.judge(current, pack, engine.initial_state("S-OTHER", pack, "text")).alerts == ()
