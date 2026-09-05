from contracts.engine_contract import JudgeResult, VerdictPayload
from engine.build import build_engine
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource


def _engine(pack_json):
    return build_engine(FakePackSource(pack_json))


def test_initial_state_required_unmet_forbidden_clean(pack_json):
    engine = _engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S1", pack, "text")
    by_code = {s.item_code: s for s in state.items}
    # required 8 + forbidden 1. reference(DOC-001·002)·risk(RSK-001) 항목은 제외
    assert len(by_code) == 9
    assert all(by_code[c].state == "unmet" for c in ("DEP-INT-002", "DEP-PRO-001"))
    assert all(by_code[c].state == "clean" for c in ("DEP-BAN-001", "DEP-BAN-001"))
    assert state.unmet_codes() == tuple(it.code for it in pack.required_items())


def test_apply_is_idempotent_and_bumps_ver_only_on_change(pack_json):
    engine = _engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    s0 = engine.initial_state("S1", pack, "text")
    result = JudgeResult(
        verdicts=(
            VerdictPayload(item_code="DEP-INT-001", axis="omission", state="met", decided_by="L1"),
        )
    )
    s1 = engine.apply(s0, result)
    s2 = engine.apply(s1, result)
    assert s1 == s2
    assert s0.state_of("DEP-INT-001").state == "unmet"  # 인자는 안 바뀐다
    assert s1.state_of("DEP-INT-001").state == "met"
    assert s1.state_of("DEP-INT-001").ver == 1
    l3 = JudgeResult(
        verdicts=(
            VerdictPayload(item_code="DEP-INT-001", axis="omission", state="met", decided_by="L3"),
        )
    )
    assert engine.apply(s1, l3).state_of("DEP-INT-001").ver == 2


def test_term_density_follows_teller_jargon_and_matches_fold(pack_json, scenario_a):
    """⑧. 팩 jargon_terms 대조로만 센다. 실시간(observe)과 접기(fold)가 같은 값을 낸다."""
    from contracts.engine_contract import Utterance

    engine = _engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("FIXT-SESS-0A", pack, "replay")
    assert state.term_density == "normal"  # 아직 잰 것이 없다

    seen: dict[int, str] = {}
    for e in sorted(scenario_a, key=lambda e: e["seq_in_session"]):
        if e["kind"] != "utterance":
            continue
        u = e["utterance"]
        state = engine.observe(state, Utterance(e["event_id"], u["speaker"], u["text"], u["t_ms"]))
        seen[e["seq_in_session"]] = state.term_density

    assert seen[5] == "normal"  # 우대이자율·기본이자율 두 개. high 는 아직 아니다
    assert seen[28] == "low"  # 은행원 발화가 이어지는 동안 용어가 하나도 없다
    assert seen[29] == "normal"  # 만기후이자율 하나만 나와 high 는 아니다
    assert engine.fold(scenario_a).term_density == state.term_density


def test_term_density_high_and_stt_variant_counts(pack_json):
    from contracts.engine_contract import Utterance

    engine = _engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    state = engine.initial_state("S1", pack, "text")
    # "차감율" 은 L0 가 "차감률" 로 바로잡으므로 센다. 고객 발화의 용어는 세지 않는다
    state = engine.observe(state, Utterance("u1", "customer", "만기후이자율이 뭐예요?", 0))
    said = Utterance("u2", "teller", "차감율과 약정이율, 재예치 기준입니다", 1)
    state = engine.observe(state, said)
    assert state.term_density == "high"
    assert engine.observe(state, Utterance("u2", "teller", "같은 발화", 1)) == state  # 멱등
