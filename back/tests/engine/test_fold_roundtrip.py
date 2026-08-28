"""시나리오 A 이벤트 27건을 접으면 session_ended.summary 와 같아야 한다."""

from engine.adapters.pack_source.fake import FakePackSource
from engine.build import build_engine
from tests.engine.conftest import PACK_VERSION


def test_fold_scenario_a_matches_summary(pack_json, scenario_a):
    engine = build_engine(FakePackSource(pack_json))
    pack = engine.load_pack(PACK_VERSION)
    state = engine.fold(scenario_a)

    assert state.session_id == "FIXT-SESS-0A"
    assert state.mode == "replay"
    # supersedes 체인: EV-0006 partial → EV-0019 met
    assert state.state_of("DEP-INT-002").state == "partial"  # 이율 정정 후에도 차감률 미고지
    assert state.state_of("DEP-INT-002").ver == 2
    assert state.state_of("DEP-BAN-002", "commission").state == "violated"
    assert state.state_of("DEP-INT-003").state == "met"

    ended = next(e for e in scenario_a if e["kind"] == "session_ended")
    assert engine.summarize(state, pack, scenario_a) == ended["session_ended"]["summary"]


def test_fold_is_order_independent(pack_json, scenario_a):
    engine = build_engine(FakePackSource(pack_json))
    shuffled = list(reversed(scenario_a))
    assert engine.fold(shuffled) == engine.fold(scenario_a)
