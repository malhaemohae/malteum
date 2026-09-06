from contracts.engine_contract import ItemState, JudgeDecision, Utterance, VerdictPayload
from engine.pack.loader import load_pack
from engine.tiers.l3 import decision_parser
from engine.types import SessionState
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource


def _parse(pack_json, verdict, *, speaker="teller", items=()):
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    state = SessionState("S", PACK_VERSION, "text", items=items)
    utterance = Utterance("U1", speaker, "판정할 발화", 1)
    return decision_parser.parse(JudgeDecision(verdicts=(verdict,)), pack, state, utterance)


def test_l3_does_not_replace_human_decision(pack_json):
    human = ItemState("DEP-INT-002", "omission", "met", "human", 1)
    proposed = VerdictPayload("DEP-INT-002", "omission", "met", "L3")

    verdicts, _, _, rejected = _parse(pack_json, proposed, items=(human,))

    assert verdicts == []
    assert rejected == ["DEP-INT-002: 사람 판정은 L3가 변경할 수 없음"]


def test_l3_rejects_axis_and_state_that_do_not_match_item_type(pack_json):
    proposed = VerdictPayload("DEP-INT-002", "commission", "violated", "L3")

    verdicts, _, _, rejected = _parse(pack_json, proposed)

    assert verdicts == []
    assert rejected == ["DEP-INT-002: required/teller에 commission/violated 판정 불가"]


def test_l3_rejects_teller_verdict_from_customer_utterance(pack_json):
    proposed = VerdictPayload("DEP-INT-002", "omission", "met", "L3")

    verdicts, _, _, rejected = _parse(pack_json, proposed, speaker="customer")

    assert verdicts == []
    assert rejected == ["DEP-INT-002: required/customer에 omission/met 판정 불가"]


def test_l3_accepts_customer_comprehension_for_required_item(pack_json):
    proposed = VerdictPayload("DEP-INT-002", "comprehension", "confirmed", "L3")

    verdicts, _, _, rejected = _parse(pack_json, proposed, speaker="customer")

    assert [(v.axis, v.state, v.decided_by) for v in verdicts] == [
        ("comprehension", "confirmed", "L3")
    ]
    assert rejected == []
