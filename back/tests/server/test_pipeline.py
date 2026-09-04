"""submit_utterance 가 저장 → 판정 → 적용 → 변환 → 전송 순서를 지키는가. 엔진은 가짜."""

from datetime import UTC, datetime

import pytest

from contracts.engine_contract import AssistPayload, JudgeResult, Utterance, VerdictPayload
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


def test_restored_session_keeps_the_original_t_ms_origin():
    """계약: t_ms 는 M1 이 세션 시작 기준 오프셋으로 찍는다.

    재접속하면 연결은 새것이지만 세션은 이어진다. 원점이 연결에 묶여 있으면 이어 붙인
    발화가 0 부터 다시 매겨져 앞부분과 t_ms 가 겹치고, 겹친 값으로는 발화 재생(C축 DoD)이
    어느 지점인지 못 짚는다.
    """
    engine = StubEngine([])
    store = MemoryEventStore()
    registry = SessionRegistry(engine, store)
    pipeline = Pipeline(engine, store)

    session = registry.open("DEP-2026.08-v4", "text", session_id="FIXT-SESS-0E")
    started = pipeline.start(
        session, "text", {"code": "x", "name": "x", "category": "deposit"}, "general"
    )
    registry.close("FIXT-SESS-0E")  # 연결이 끊긴 상황

    revived = registry.open("DEP-2026.08-v4", "text", session_id="FIXT-SESS-0E")
    assert revived.restored
    origin = datetime.fromisoformat(started["occurred_at"]).astimezone(UTC)
    assert revived.started_at == origin
    # 되살린 뒤의 경과는 세션 시작부터 잰다. 0 으로 돌아가지 않는다
    assert revived.elapsed_ms() >= 0


class ResultEngine(StubEngine):
    """judge 가 준비된 JudgeResult 를 순서대로 낸다(assist 포함)."""

    def __init__(self, results):
        super().__init__([])
        self._results = list(results)

    def judge(self, utterance, pack, state):
        return self._results.pop(0) if self._results else JudgeResult()


REPHRASE = AssistPayload(
    assist_type="rephrase",
    text="만기 전에 찾으면 약속한 이자보다 적게 받습니다.",
    item_code="DEP-INT-002",
    trigger="customer_reask",
    source_utterance_ref="u-previous-1",
)
NUDGE = AssistPayload(
    assist_type="nudge", text="중도해지이율을 안내하세요.", item_code="DEP-INT-002"
)


async def _run(results, utterances):
    store, session, pipeline = _fixture_session(ResultEngine(results), "FIXT-SESS-AD")
    sent = []

    async def publish(m):
        sent.append(m)

    for u in utterances:
        await pipeline.submit_utterance(session, u, publish)
    assists = [e for e in store.of_session("FIXT-SESS-AD") if e["kind"] == "assist"]
    return assists, [m for m in sent if m["t"] == "assist"]


@pytest.mark.anyio
async def test_a_rephrase_card_is_adopted_when_the_teller_repeats_its_sentence():
    assists, sent = await _run(
        [JudgeResult(assists=(REPHRASE,)), JudgeResult()],
        [
            Utterance(utterance_id="", speaker="customer", text="중도해지이율이 뭐예요?", t_ms=100),
            Utterance(
                utterance_id="",
                speaker="teller",
                text="네, 만기 전에 찾으시면 처음 약속한 이자보다 적게 받으신다는 뜻입니다.",
                t_ms=200,
            ),
        ],
    )
    assert [a["assist"].get("outcome") for a in assists] == [None, "adopted"]
    assert assists[1]["supersedes"] == assists[0]["event_id"]
    assert [m["ver"] for m in sent] == [1, 2]


@pytest.mark.anyio
async def test_a_nudge_card_is_adopted_when_the_teller_meets_that_item():
    met = VerdictPayload(item_code="DEP-INT-002", axis="omission", state="met", decided_by="L1")
    assists, _ = await _run(
        [JudgeResult(assists=(NUDGE,)), JudgeResult(verdicts=(met,))],
        [
            Utterance(utterance_id="", speaker="teller", text="이자는 그대로예요.", t_ms=100),
            Utterance(
                utterance_id="",
                speaker="teller",
                text="중도해지이율은 약정이율에 차감률을 곱합니다.",
                t_ms=200,
            ),
        ],
    )
    assert [a["assist"].get("outcome") for a in assists] == [None, "adopted"]


@pytest.mark.anyio
async def test_an_unrelated_teller_utterance_adopts_nothing_and_a_card_is_adopted_once():
    partial = VerdictPayload(
        item_code="DEP-INT-002", axis="omission", state="partial", decided_by="L1"
    )
    repeat = Utterance(
        utterance_id="",
        speaker="teller",
        text="만기 전에 찾으면 약속한 이자보다 적게 받습니다.",
        t_ms=300,
    )
    assists, _ = await _run(
        [
            JudgeResult(assists=(REPHRASE, NUDGE)),
            JudgeResult(verdicts=(partial,)),
            JudgeResult(),
            JudgeResult(),
        ],
        [
            Utterance(utterance_id="", speaker="customer", text="그게 뭐예요?", t_ms=100),
            Utterance(utterance_id="", speaker="teller", text="세율은 15.4%입니다.", t_ms=200),
            repeat,
            repeat,
        ],
    )
    outcomes = [(a["assist"]["assist_type"], a["assist"].get("outcome")) for a in assists]
    # partial 은 넛지를 채택하지 않고, 되풀이한 문장은 rephrase 만 한 번 채택한다
    assert outcomes == [("rephrase", None), ("nudge", None), ("rephrase", "adopted")]
