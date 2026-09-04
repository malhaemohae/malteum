"""시나리오 A 이벤트 48건을 접으면 session_ended.summary 와 같아야 한다."""

from engine.build import build_engine
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource


def test_fold_scenario_a_matches_summary(pack_json, scenario_a):
    engine = build_engine(FakePackSource(pack_json))
    pack = engine.load_pack(PACK_VERSION)
    state = engine.fold(scenario_a)

    assert state.session_id == "FIXT-SESS-0A"
    assert state.mode == "replay"
    # 체인: EV-0011 partial(L1) → EV-0012 partial(L3) → EV-0034 met(L1). 넛지 뒤 산식을 채움
    assert state.state_of("DEP-INT-002").state == "met"
    assert state.state_of("DEP-INT-002").ver == 3
    assert state.state_of("DEP-BAN-001", "commission").state == "violated"
    assert state.state_of("DEP-INT-003").state == "met"
    assert state.state_of("DEP-TAX-001").state == "met"  # 세율은 틀렸지만(경보) 항목은 설명함
    assert state.state_of("DEP-PRO-001").state == "partial"  # 합산 미고지
    assert state.state_of("DEP-LIM-001") is None  # 끝까지 말하지 않아 unmet

    ended = next(e for e in scenario_a if e["kind"] == "session_ended")
    assert engine.summarize(state, pack, scenario_a) == ended["session_ended"]["summary"]


def test_fold_is_order_independent(pack_json, scenario_a):
    engine = build_engine(FakePackSource(pack_json))
    shuffled = list(reversed(scenario_a))
    assert engine.fold(shuffled) == engine.fold(scenario_a)
