"""시나리오 A(중도해지 상담) 이벤트 31건을 발화만 뽑아 judge→apply(→refine→apply) 로 다시 돌린다.

engine 이 낸 verdict·alert 가 fixture 의 대체되지 않은 마지막 이벤트와 같아야 하고,
끝난 상태가 fixture 를 fold 한 상태·종료 요약과 같아야 한다.
nudge(missing_item) 는 발화가 아니라 시간·화면 사정으로 M1 이 청하는 것이라 비교하지 않는다.
"""

from __future__ import annotations

import asyncio

import pytest

from contracts.engine_contract import JudgeDecision, Utterance, VerdictPayload
from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakeChunkIndex, FakeEmbedder, FakePackSource, ScriptedLlmJudge

PHRASES = {
    "만기 지나도": "DEP-BAN-001",
    "만기가 지나면": "DEP-INT-003",
    "중간에 깨면": "DEP-INT-002",
    "훨씬 덜 받는다": "DEP-INT-002",
}

SCRIPT = {
    "만기 지나도 지금 금리가 그대로": JudgeDecision(
        verdicts=(VerdictPayload("DEP-BAN-001", "commission", "violated", "L3"),)
    ),
    "중간에 깨면 이자를 훨씬 덜": JudgeDecision(
        verdicts=(VerdictPayload("DEP-INT-002", "comprehension", "confirmed", "L3"),)
    ),
    "만기가 지나면 금리가 내려갑니다": JudgeDecision(
        verdicts=(VerdictPayload("DEP-INT-003", "omission", "met", "L3"),)
    ),
    "한 달 안에": JudgeDecision(
        verdicts=(
            VerdictPayload(
                "DEP-INT-002",
                "omission",
                "partial",
                "L3",
                missing_elements=("차감률 또는 산출식",),
            ),
        )
    ),
}


@pytest.fixture
def engine(pack_json):
    codes = [it["code"] for it in pack_json["items"]]
    embedder = FakeEmbedder(codes, PHRASES)
    return build_engine(
        FakePackSource(pack_json),
        embedder,
        MemoryVectorIndex(),
        FakeChunkIndex([], embedder),
        ScriptedLlmJudge(SCRIPT),
        MemoryDecisionCache(),
    )


def _utterance(e: dict) -> Utterance:
    u = e["utterance"]
    return Utterance(
        utterance_id=e["event_id"],
        speaker=u["speaker"],
        text=u["text"],
        t_ms=u["t_ms"],
        duration_ms=u.get("duration_ms"),
        stt_confidence=u.get("stt_confidence"),
        speaker_confidence=u.get("speaker_confidence"),
    )


def test_scenario_a_replay(engine, scenario_a):
    pack = engine.load_pack(PACK_VERSION)
    started = next(e for e in scenario_a if e["kind"] == "session_started")
    state = engine.initial_state(started["session_id"], pack, started["session_started"]["mode"])
    by_id = {e["event_id"]: e for e in scenario_a}
    # 같은 발화 안에서 대체된 것만 뺀다. 나중 발화가 앞 판정을 대체한 것은 앞 발화 시점에는 유효했다
    superseded = {
        e["supersedes"]
        for e in scenario_a
        if e.get("supersedes") and _ref(e) == _ref(by_id[e["supersedes"]])
    }

    for e in sorted(scenario_a, key=lambda e: e["seq_in_session"]):
        if e["kind"] != "utterance":
            continue
        utt = _utterance(e)
        results = [engine.judge(utt, pack, state)]
        state = engine.apply(state, results[0])
        if results[0].needs_refine:
            results.append(asyncio.run(engine.refine(utt, pack, state)))
            state = engine.apply(state, results[1])
        state = engine.observe(state, utt)

        final = {}
        for r in results:
            for v in r.verdicts:
                final[(v.item_code, v.axis)] = (v.state, v.decided_by)
        expected = {
            (x["verdict"]["item_code"], x["verdict"]["axis"]): (
                x["verdict"]["state"],
                x["verdict"]["decided_by"],
            )
            for x in scenario_a
            if x["kind"] == "verdict"
            and x["verdict"].get("utterance_ref") == e["event_id"]
            and x["event_id"] not in superseded
        }
        assert final == expected, f"{e['event_id']} {utt.text[:30]}…\n기대 {expected}\n실제 {final}"

        alerts = {(a.alert_type, a.item_code) for r in results for a in r.alerts}
        expected_alerts = {
            (x["alert"]["alert_type"], x["alert"].get("item_code"))
            for x in scenario_a
            if x["kind"] == "alert" and x["alert"].get("utterance_ref") == e["event_id"]
        }
        assert alerts == expected_alerts, (
            f"{e['event_id']} alerts 기대 {expected_alerts} 실제 {alerts}"
        )

        rephrases = {a.item_code for r in results for a in r.assists if a.assist_type == "rephrase"}
        expected_rephrases = {
            x["assist"].get("item_code")
            for x in scenario_a
            if x["kind"] == "assist"
            and x["assist"]["assist_type"] == "rephrase"
            and x["assist"].get("source_utterance_ref", e["event_id"]) == e["event_id"]
            and x["event_id"] not in superseded
            and x["assist"].get("outcome") is None
        }
        assert rephrases >= expected_rephrases, (
            f"{e['event_id']} rephrase 기대 {expected_rephrases} 실제 {rephrases}"
        )

    folded = engine.fold(scenario_a)
    mine = {(s.item_code, s.axis): s.state for s in state.items}
    theirs = {(s.item_code, s.axis): s.state for s in folded.items}
    # 초기 상태의 unmet·clean 은 fixture 에 이벤트가 없으니 비교에서 뺀다
    mine_changed = {k: v for k, v in mine.items() if v not in ("unmet", "clean")}
    assert mine_changed == theirs
    ended = next(e for e in scenario_a if e["kind"] == "session_ended")["session_ended"]["summary"]
    summary = engine.summarize(state, pack, scenario_a)
    assert summary == ended, f"요약 기대 {ended} 실제 {summary}"


def _ref(e: dict) -> str | None:
    body = e.get(e["kind"], {})
    return body.get("utterance_ref") or body.get("source_utterance_ref")
