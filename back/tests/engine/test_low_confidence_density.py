"""⑧ 용어 밀도는 저신뢰 은행원 발화를 세지 않는다.

판정과 같은 `gate()` 정책(화자 신뢰도 0.6 미만)을 재사용한다. 용어 개수뿐 아니라
'용어 없는 은행원 발화 수' 에서도 빠지고, 실시간 observe 와 저장 이벤트 fold 가 같은 값을 낸다.
창(recent_utterances) 자체에는 남으므로 원문 감사와 L3 문맥은 그대로다.
"""

from __future__ import annotations

import pytest

from contracts.engine_contract import Utterance
from engine.build import build_engine
from engine.tiers.l1.gate import SPEAKER_CONFIDENCE_THRESHOLD
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource

TERMS = "우대이자율 기본이자율 만기후이자율"
LOW = 0.2


@pytest.fixture
def engine(pack_json):
    return build_engine(FakePackSource(pack_json))


@pytest.fixture
def pack(engine):
    return engine.load_pack(PACK_VERSION)


def _teller(text, conf, uid="U1", t_ms=1):
    return Utterance(uid, "teller", text, t_ms, speaker_confidence=conf)


def test_low_confidence_terms_do_not_raise_density(engine, pack):
    state = engine.initial_state("S", pack, "text")
    state = engine.observe(state, _teller(TERMS, LOW))
    assert state.term_density == "normal"
    state = engine.observe(state, _teller(TERMS, 0.95, uid="U2", t_ms=2))
    assert state.term_density == "high"


def test_low_confidence_termless_utterances_do_not_lower_density(engine, pack):
    state = engine.initial_state("S", pack, "text")
    for i in range(3):
        state = engine.observe(state, _teller("네, 잠시만요.", LOW, uid=f"L{i}", t_ms=i))
    assert state.term_density == "normal"  # 아직 신뢰할 은행원 발화가 없다
    for i in range(3):
        state = engine.observe(state, _teller("네, 잠시만요.", 0.95, uid=f"C{i}", t_ms=10 + i))
    assert state.term_density == "low"


def test_density_threshold_edge_matches_gate(engine, pack):
    state = engine.initial_state("S", pack, "text")
    state = engine.observe(state, _teller(TERMS, 0.59))
    assert state.term_density == "normal"
    state = engine.observe(state, _teller(TERMS, SPEAKER_CONFIDENCE_THRESHOLD, uid="U2", t_ms=2))
    assert state.term_density == "high"


def test_observe_and_fold_agree_with_low_confidence_in_window(engine, pack):
    utterances = [
        _teller(TERMS, LOW, uid="E1", t_ms=1),
        _teller("네, 잠시만요.", None, uid="E2", t_ms=2),
        _teller(TERMS, 0.95, uid="E3", t_ms=3),
        Utterance("E4", "customer", TERMS, 4, speaker_confidence=0.9),
    ]
    live = engine.initial_state("FOLD", pack, "text")
    events = [
        {
            "event_id": "E0",
            "session_id": "FOLD",
            "seq_in_session": 0,
            "pack_version": PACK_VERSION,
            "kind": "session_started",
            "session_started": {"mode": "text"},
        }
    ]
    for i, u in enumerate(utterances, start=1):
        live = engine.observe(live, u)
        events.append(
            {
                "event_id": u.utterance_id,
                "session_id": "FOLD",
                "seq_in_session": i,
                "pack_version": PACK_VERSION,
                "kind": "utterance",
                "utterance": {
                    "speaker": u.speaker,
                    "text": u.text,
                    "t_ms": u.t_ms,
                    "speaker_confidence": u.speaker_confidence,
                },
            }
        )
    folded = engine.fold(events)
    assert folded.term_density == live.term_density == "high"
    assert folded.recent_utterances == live.recent_utterances  # 저신뢰 원문도 창에는 남는다
