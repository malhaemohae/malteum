"""저신뢰 은행원 발화는 verdict 를 만들지 않고 상태를 그대로 둔다 (P3).

`gate()` 가 화자 신뢰도 0.6 미만인 은행원 발화의 판정 타입을 비우면 judge 는 그 발화로
아무 항목도 올리지 않아야 한다. 현재 상태를 복사한 verdict 는 초기 ver=0 을 전송하고
L3·human 판정을 L1 으로 덮으며 waived 에서는 apply 가 실패했다.
speaker_confidence 는 화자 역할 신뢰도이지 STT 정확도가 아니다. None 은 미측정이며 정상 경로다.
"""

from __future__ import annotations

import pytest

from contracts.engine_contract import JudgeResult, Utterance, VerdictPayload
from engine.build import build_engine
from engine.tiers.l1.gate import SPEAKER_CONFIDENCE_THRESHOLD
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource

# DEP-PRO-001 요건 요소 셋(보호 대상·보호 한도·동일 은행 합산)을 모두 채우는 L1 양성 문장
FULL = "예금자보호법에 따라 원금과 이자를 합해서 1인당 1억 원까지 보호됩니다."
LOW = 0.2


@pytest.fixture
def engine(pack_json):
    return build_engine(FakePackSource(pack_json))


@pytest.fixture
def pack(engine):
    return engine.load_pack(PACK_VERSION)


def _teller(text, conf, uid="U1", t_ms=1):
    return Utterance(uid, "teller", text, t_ms, speaker_confidence=conf)


def _verdict(code, state, by, **kw):
    return VerdictPayload(item_code=code, axis="omission", state=state, decided_by=by, **kw)


def _with(engine, state, *verdicts):
    return engine.apply(state, JudgeResult(verdicts=tuple(verdicts)))


def test_confident_full_explanation_is_met_at_l1(engine, pack):
    state = engine.initial_state("S", pack, "text")
    result = engine.judge(_teller(FULL, 0.95), pack, state)
    assert [(v.item_code, v.state, v.decided_by) for v in result.verdicts] == [
        ("DEP-PRO-001", "met", "L1")
    ]
    assert result.alerts == ()


@pytest.mark.parametrize("conf", [0.0, 0.59, LOW])
def test_low_confidence_teller_emits_nothing(engine, pack, conf):
    state = engine.initial_state("S", pack, "text")
    result = engine.judge(_teller(FULL, conf), pack, state)
    assert result.verdicts == () and result.alerts == () and result.assists == ()
    assert engine.apply(state, result) == state


@pytest.mark.parametrize("conf", [SPEAKER_CONFIDENCE_THRESHOLD, 0.95, None])
def test_threshold_and_unmeasured_confidence_judge_normally(engine, pack, conf):
    state = engine.initial_state("S", pack, "text")
    result = engine.judge(_teller(FULL, conf), pack, state)
    assert [(v.item_code, v.state) for v in result.verdicts] == [("DEP-PRO-001", "met")]


@pytest.mark.parametrize("speaker", ["customer", "system"])
def test_non_teller_never_raises_omission(engine, pack, speaker):
    state = engine.initial_state("S", pack, "text")
    result = engine.judge(Utterance("U1", speaker, FULL, 1, speaker_confidence=0.95), pack, state)
    assert all(v.axis != "omission" for v in result.verdicts)


def _prior_states(engine, pack):
    s0 = engine.initial_state("S", pack, "text")
    yield "unmet/initial", s0
    yield (
        "partial/L1",
        _with(
            engine,
            s0,
            _verdict("DEP-PRO-001", "partial", "L1", missing_elements=("동일 은행 합산",)),
        ),
    )
    yield (
        "met/L3 ver=2",
        _with(
            engine,
            _with(engine, s0, _verdict("DEP-PRO-001", "met", "L1")),
            _verdict("DEP-PRO-001", "met", "L3"),
        ),
    )
    yield (
        "met/human ver=2",
        _with(
            engine,
            _with(engine, s0, _verdict("DEP-PRO-001", "met", "L1")),
            _verdict("DEP-PRO-001", "met", "human"),
        ),
    )
    yield (
        "waived/human",
        _with(
            engine, s0, _verdict("DEP-PRO-001", "waived", "human", waive_reason="전문투자자 확인")
        ),
    )


def test_low_confidence_preserves_every_prior_state(engine, pack):
    for label, before in _prior_states(engine, pack):
        result = engine.judge(_teller(FULL, LOW), pack, before)
        assert result.verdicts == (), f"{label}: {result.verdicts}"
        after = engine.apply(before, result)  # waived 라면 여기서 ValueError 가 났었다
        assert after == before, label
        again = engine.apply(after, engine.judge(_teller(FULL, LOW, uid="U2", t_ms=2), pack, after))
        assert again == before, f"{label}: 반복 입력이 상태를 바꿈"


def test_low_confidence_keeps_customer_risk_fallback(engine, pack):
    state = engine.initial_state("S", pack, "text")
    result = engine.judge(
        _teller("해지한 돈은 딸이 알려준 계좌로 바로 보내 주세요.", LOW), pack, state
    )
    assert [(a.alert_type, a.item_code) for a in result.alerts] == [("risk_signal", "DEP-RSK-001")]
    assert result.verdicts == ()
