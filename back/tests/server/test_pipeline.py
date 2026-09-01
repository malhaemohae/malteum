"""submit_utterance 가 저장 → 판정 → 적용 → 변환 → 전송 순서를 지키는가. 엔진은 가짜."""

import pytest

from contracts.engine_contract import JudgeResult, Utterance, VerdictPayload
from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from server.bootstrap.settings import BACK_DIR
from server.services.event.store import MemoryEventStore
from server.services.session.pipeline import Pipeline
from server.services.session.refiner import Refiner
from server.services.session.registry import SessionRegistry

L1_PARTIAL = VerdictPayload(
    item_code="DEP-INT-002", axis="omission", state="partial", decided_by="L1"
)
L3_MET = VerdictPayload(item_code="DEP-INT-002", axis="omission", state="met", decided_by="L3")


class StubEngine:
    """judge 만 바꿔 끼운 엔진. 나머지는 실물."""

    def __init__(self, verdicts):
        self._real = build_engine(FilePackSource(BACK_DIR / "contracts" / "fixtures"))
        self._verdicts = verdicts

    def __getattr__(self, name):
        return getattr(self._real, name)

    def judge(self, utterance, pack, state):
        return JudgeResult(verdicts=self._verdicts.pop(0) if self._verdicts else ())


class RefiningEngine(StubEngine):
    """judge 는 잠정 판정 + needs_refine, refine 은 확정 판정을 낸다."""

    def __init__(self, provisional, corrected, needs_refine=True):
        super().__init__([])
        self._provisional = provisional
        self._corrected = corrected
        self._needs_refine = needs_refine
        self.refine_calls = 0
        self.refined_utterance_id = None

    def judge(self, utterance, pack, state):
        return JudgeResult(verdicts=self._provisional, needs_refine=self._needs_refine)

    async def refine(self, utterance, pack, state):
        self.refine_calls += 1
        self.refined_utterance_id = utterance.utterance_id
        return JudgeResult(verdicts=self._corrected)


def _fixture_session(engine, session_id):
    store = MemoryEventStore()
    registry = SessionRegistry(engine, store)
    session = registry.open("DEP-2026.08-v4", "text", session_id=session_id)
    return store, session, Pipeline(engine, store)


@pytest.mark.anyio
async def test_submit_utterance_persists_and_publishes_with_supersedes():
    l1 = VerdictPayload(item_code="DEP-INT-002", axis="omission", state="partial", decided_by="L1")
    l3 = VerdictPayload(item_code="DEP-INT-002", axis="omission", state="met", decided_by="L3")
    engine = StubEngine([(l1,), (l3,)])
    store = MemoryEventStore()
    registry = SessionRegistry(engine, store)
    pipeline = Pipeline(engine, store)
    session = registry.open("DEP-2026.08-v4", "text", session_id="FIXT-SESS-0B")
    sent = []

    async def publish(m):
        sent.append(m)

    u = Utterance(utterance_id="", speaker="teller", text="중도해지하시면", t_ms=100)
    await pipeline.submit_utterance(session, u, publish)
    await pipeline.submit_utterance(session, u, publish)

    kinds = [e["kind"] for e in store.of_session("FIXT-SESS-0B")]
    assert kinds == ["utterance", "verdict", "utterance", "verdict"]
    verdicts = [e for e in store.of_session("FIXT-SESS-0B") if e["kind"] == "verdict"]
    assert verdicts[0]["supersedes"] is None
    assert verdicts[1]["supersedes"] == verdicts[0]["event_id"]  # M1 이 채운다 (D9)

    types = [m["t"] for m in sent]
    assert types == ["utterance", "verdict", "progress", "utterance", "verdict", "progress"]
    assert [m["ver"] for m in sent if m["t"] == "verdict"] == [1, 2]
    assert sent[-1]["partial"] == 0 and sent[-1]["met"] == 1
    assert session.state.state_of("DEP-INT-002").state == "met"


@pytest.mark.anyio
async def test_refine_runs_when_needs_refine_and_supersedes_the_provisional_verdict():
    """계약: judge 가 needs_refine 을 켜면 M1 이 refine 을 비동기로 예약한다."""
    engine = RefiningEngine((L1_PARTIAL,), (L3_MET,))
    store, session, pipeline = _fixture_session(engine, "FIXT-SESS-0C")
    sent = []

    async def publish(m):
        sent.append(m)

    async def on_error(e):
        raise AssertionError(f"보정이 실패하면 안 된다: {e}")

    refiner = Refiner(session, pipeline, publish, on_error)
    u = Utterance(utterance_id="", speaker="teller", text="중도해지하시면", t_ms=100)
    await pipeline.submit_utterance(session, u, publish, refiner.schedule)
    await refiner.queue.join()
    await refiner.aclose()

    events = store.of_session("FIXT-SESS-0C")
    verdicts = [e for e in events if e["kind"] == "verdict"]
    assert [v["verdict"]["decided_by"] for v in verdicts] == ["L1", "L3"]
    assert verdicts[1]["supersedes"] == verdicts[0]["event_id"]
    assert engine.refine_calls == 1
    # 보정이 근거로 짚을 발화 id 가 채워진 채 넘어가야 한다. 빈 문자열이면 무엇을
    # 다시 판정하는지 엔진이 알 수 없다
    assert engine.refined_utterance_id == events[0]["event_id"]
    assert session.state.state_of("DEP-INT-002").state == "met"


@pytest.mark.anyio
async def test_refine_is_not_scheduled_when_needs_refine_is_off():
    """계약: False 면 부르지 않는다. 매 발화마다 L3 를 부르면 예산이 샌다."""
    engine = RefiningEngine((L1_PARTIAL,), (L3_MET,), needs_refine=False)
    _, session, pipeline = _fixture_session(engine, "FIXT-SESS-0D")
    scheduled = []

    async def publish(m):
        pass

    u = Utterance(utterance_id="", speaker="teller", text="중도해지하시면", t_ms=100)
    await pipeline.submit_utterance(session, u, publish, scheduled.append)

    assert scheduled == []
    assert engine.refine_calls == 0
