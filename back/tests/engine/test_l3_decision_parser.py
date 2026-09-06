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


def test_l3_partial_accumulates_previously_satisfied_elements(pack_json):
    """모델은 이번 발화만 본다. 이전에 채운 요소는 다시 요구하지 않는다 (L1 known 과 같은 규칙)."""
    before = ItemState(
        "DEP-INT-002",
        "omission",
        "partial",
        "L3",
        1,
        missing_elements=("적용 이율", "차감률 또는 산출식"),
    )
    proposed = VerdictPayload(
        "DEP-INT-002", "omission", "partial", "L3", missing_elements=("만기 전 해지 시 불이익",)
    )

    (v,), _, assists, rejected = _parse(pack_json, proposed, items=(before,))

    assert (v.state, v.missing_elements) == ("met", ()) and rejected == []
    assert assists == []  # met 이면 넛지 없음


def test_l3_partial_keeps_only_still_missing_elements_in_pack_order(pack_json):
    before = ItemState(
        "DEP-INT-002",
        "omission",
        "partial",
        "L1",
        1,
        missing_elements=("차감률 또는 산출식", "적용 이율"),
    )
    proposed = VerdictPayload(
        "DEP-INT-002",
        "omission",
        "partial",
        "L3",
        missing_elements=("차감률 또는 산출식", "만기 전 해지 시 불이익"),
    )

    (v,), _, assists, _ = _parse(pack_json, proposed, items=(before,))

    assert (v.state, v.missing_elements) == ("partial", ("차감률 또는 산출식",))
    assert len(assists) == 1  # 남은 요소로 넛지


def test_l3_same_partial_from_l3_is_dropped_but_new_missing_is_kept(pack_json):
    before = ItemState(
        "DEP-INT-002", "omission", "partial", "L3", 1, missing_elements=("적용 이율",)
    )
    same = VerdictPayload(
        "DEP-INT-002", "omission", "partial", "L3", missing_elements=("적용 이율",)
    )
    assert _parse(pack_json, same, items=(before,))[0] == []

    # 이번 발화가 아무 요소도 채우지 못했다는 뜻이면 변화 없음
    nothing_new = VerdictPayload(
        "DEP-INT-002",
        "omission",
        "partial",
        "L3",
        missing_elements=("만기 전 해지 시 불이익", "적용 이율", "차감률 또는 산출식"),
    )
    assert _parse(pack_json, nothing_new, items=(before,))[0] == []


def test_l3_rejects_partial_without_missing_elements(pack_json):
    proposed = VerdictPayload("DEP-INT-002", "omission", "partial", "L3")

    verdicts, _, _, rejected = _parse(pack_json, proposed)

    assert verdicts == [] and rejected == ["DEP-INT-002: partial 인데 빠진 요소가 없음"]


def test_cache_key_changes_with_prompt_version(pack_json, monkeypatch):
    from engine.tiers.l3 import prompt_builder

    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    state = SessionState("S", PACK_VERSION, "text")
    before = prompt_builder.build("중도해지", pack, state, ["DEP-INT-002"], "m", "teller").cache_key
    monkeypatch.setattr(prompt_builder, "PROMPT_VERSION", "other")
    after = prompt_builder.build("중도해지", pack, state, ["DEP-INT-002"], "m", "teller").cache_key
    assert before != after
