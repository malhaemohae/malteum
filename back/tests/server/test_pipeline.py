"""submit_utterance 가 저장 → 판정 → 적용 → 변환 → 전송 순서를 지키는가. 엔진은 가짜."""

import pytest

from contracts.engine_contract import JudgeResult, Utterance, VerdictPayload
from engine.adapters.pack_source.file import FilePackSource
from engine.build import build_engine
from server.bootstrap.settings import BACK_DIR
from server.services.event.store import MemoryEventStore
from server.services.session.pipeline import Pipeline
from server.services.session.registry import SessionRegistry


class StubEngine:
    """judge 만 바꿔 끼운 엔진. 나머지는 실물."""

    def __init__(self, verdicts):
        self._real = build_engine(FilePackSource(BACK_DIR / "contracts" / "fixtures"))
        self._verdicts = verdicts

    def __getattr__(self, name):
        return getattr(self._real, name)

    def judge(self, utterance, pack, state):
        return JudgeResult(verdicts=self._verdicts.pop(0) if self._verdicts else ())


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
