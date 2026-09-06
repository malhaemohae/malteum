import json

from contracts.engine_contract import Utterance
from engine.build import build_engine
from tests.engine.conftest import FIX, PACK_VERSION
from tests.engine.fakes import FakePackSource


def _alerts(pack_json, text, *, confidence=None):
    engine = build_engine(FakePackSource(pack_json))
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S", pack, "text")
    utterance = Utterance("U1", "teller", text, 1, speaker_confidence=confidence)
    return engine.judge(utterance, pack, state).alerts


def test_risk_request_is_checked_when_customer_is_misclassified_as_teller(pack_json):
    alerts = _alerts(pack_json, "해지한 돈은 딸이 알려준 계좌로 바로 보내 주세요.")

    assert [(a.alert_type, a.item_code) for a in alerts] == [("risk_signal", "DEP-RSK-001")]


def test_risk_request_is_checked_even_with_low_teller_confidence(pack_json):
    alerts = _alerts(
        pack_json,
        "해지한 돈은 딸이 알려준 계좌로 바로 보내 주세요.",
        confidence=0.4,
    )

    assert [(a.alert_type, a.item_code) for a in alerts] == [("risk_signal", "DEP-RSK-001")]


def test_teller_risk_guidance_does_not_raise_customer_alert(pack_json):
    alerts = _alerts(
        pack_json,
        "예를 들어 딸이 알려준 계좌로 보내 달라는 부탁을 받고 오시는 경우가 있는데, "
        "그런 건 꼭 확인해 드려요.",
    )

    assert alerts == ()


def test_loan_risk_request_uses_the_same_speaker_fallback():
    raw = json.loads((FIX / "rulepack_LOAN-2026.08-v7.json").read_text(encoding="utf-8"))
    engine = build_engine(FakePackSource(raw))
    pack = engine.load_pack("LOAN-2026.08-v7")
    state = engine.initial_state("S", pack, "text")

    reported = engine.judge(
        Utterance(
            "U1",
            "teller",
            "기존 대출을 먼저 갚아야 한도가 나온다고 해서 알려준 계좌로 보내려고요.",
            1,
        ),
        pack,
        state,
    )
    guidance = engine.judge(
        Utterance("U2", "teller", "알려준 계좌로 보내시면 안 됩니다.", 2),
        pack,
        state,
    )

    assert [(a.alert_type, a.item_code) for a in reported.alerts] == [
        ("risk_signal", "LOAN-VPH-001")
    ]
    assert guidance.alerts == ()
