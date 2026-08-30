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
    assert len(by_code) == 7  # reference(DEP-DOC-001)·risk(DEP-RSK-001) 항목은 제외
    assert all(by_code[c].state == "unmet" for c in ("DEP-INT-002", "DEP-LON-001"))
    assert all(by_code[c].state == "clean" for c in ("DEP-BAN-001", "DEP-BAN-002"))
    assert state.unmet_codes() == tuple(it.code for it in pack.required_items())


def test_apply_is_idempotent_and_bumps_ver_only_on_change(pack_json):
    engine = _engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    s0 = engine.initial_state("S1", pack, "text")
    result = JudgeResult(
        verdicts=(
            VerdictPayload(item_code="DEP-INT-004", axis="omission", state="met", decided_by="L1"),
        )
    )
    s1 = engine.apply(s0, result)
    s2 = engine.apply(s1, result)
    assert s1 == s2
    assert s0.state_of("DEP-INT-004").state == "unmet"  # 인자는 안 바뀐다
    assert s1.state_of("DEP-INT-004").state == "met"
    assert s1.state_of("DEP-INT-004").ver == 1
    l3 = JudgeResult(
        verdicts=(
            VerdictPayload(item_code="DEP-INT-004", axis="omission", state="met", decided_by="L3"),
        )
    )
    assert engine.apply(s1, l3).state_of("DEP-INT-004").ver == 2
