"""contracts/fixtures/judge_cases.json 15건. M2 의 통과 기준.

어댑터는 전부 fake. 아래 PHRASES·SCRIPT 는 테스트 데이터이지 엔진 로직이 아니다.
max_ms 는 측정해 로그로 남기고, MALTEUM_ENFORCE_BUDGET=1 일 때만 실패로 처리한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from contracts.engine_contract import JudgeDecision, JudgeResult, VerdictPayload
from engine.adapters.cache.memory import MemoryDecisionCache
from engine.adapters.vector_index.memory import MemoryVectorIndex
from engine.build import build_engine
from engine.types import SessionState
from tests.engine.conftest import FIX, PACK_VERSION
from tests.engine.fakes import FakeChunkIndex, FakeEmbedder, FakePackSource, ScriptedLlmJudge

CASES = json.loads((FIX / "judge_cases.json").read_text(encoding="utf-8"))["cases"]

# L2 fake 임베더가 쓰는 문구 → 항목 표. 실물에서는 임베딩 모델이 이 대응을 배운다.
PHRASES = {
    "만기 지나도": "DEP-BAN-002",
    "그대로 계속": "DEP-BAN-002",
    "중간에 깨면": "DEP-INT-002",
    "이자가 좀 줄어": "DEP-INT-002",
    "훨씬 덜 받는다": "DEP-INT-002",
}

# L3 fake 심판 스크립트. 발화 텍스트 → 결정.
SCRIPT = {
    "중도해지하시면 이자가 좀 줄어듭니다.": JudgeDecision(
        verdicts=(
            VerdictPayload(
                item_code="DEP-INT-002",
                axis="omission",
                state="partial",
                decided_by="L3",
                missing_elements=("적용 이율", "차감률 또는 산출식"),
            ),
        )
    ),
    "한 달 안에 해지하시면 연 0.10% 입니다. 그 뒤로는 기본이자율에서 경과기간별 차감률을 빼서 계산하고 최저 연 0.10% 입니다.": JudgeDecision(  # noqa: E501
        verdicts=(
            VerdictPayload(item_code="DEP-INT-002", axis="omission", state="met", decided_by="L3"),
        )
    ),
    "지금 해지 안 하고 두시면 무조건 이득이에요.": JudgeDecision(
        verdicts=(
            VerdictPayload(
                item_code="DEP-BAN-001", axis="commission", state="violated", decided_by="L3"
            ),
        )
    ),
    "그냥 두셔도 돼요. 만기 지나도 지금 금리가 그대로 계속 붙거든요.": JudgeDecision(
        verdicts=(
            VerdictPayload(
                item_code="DEP-BAN-002", axis="commission", state="violated", decided_by="L3"
            ),
        )
    ),
    "아, 중간에 깨면 이자를 훨씬 덜 받는다는 거네요.": JudgeDecision(
        verdicts=(
            VerdictPayload(
                item_code="DEP-INT-002", axis="comprehension", state="confirmed", decided_by="L3"
            ),
        )
    ),
}

AXIS_OF = {
    "unmet": "omission", "partial": "omission", "met": "omission", "waived": "omission",
    "clean": "commission", "suspected": "commission", "violated": "commission",
    "explained": "comprehension", "confirmed": "comprehension",
}  # fmt: skip


def _engine(pack_json):
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


@pytest.fixture(scope="module")
def engine(pack_json):
    return _engine(pack_json)


@pytest.fixture(scope="module")
def pack(engine):
    return engine.load_pack(PACK_VERSION)


def _state_before(engine, pack, before: dict[str, str]) -> SessionState:
    state = engine.initial_state("S-TEST", pack, "text")
    verdicts = tuple(
        VerdictPayload(item_code=code, axis=AXIS_OF[st], state=st, decided_by="L1")
        for code, st in before.items()
        if not (AXIS_OF[st] == "omission" and st == "unmet")
        and not (AXIS_OF[st] == "commission" and st == "clean")
    )
    return engine.apply(state, JudgeResult(verdicts=verdicts))


def _utterance(case):
    u = case["utterance"]
    from contracts.engine_contract import Utterance

    return Utterance(
        utterance_id=f"U-{case['name'][:8]}",
        speaker=u["speaker"],
        text=u["text"],
        t_ms=u["t_ms"],
        speaker_confidence=u.get("speaker_confidence"),
    )


def _matches(actual, expected: dict, keys) -> bool:
    for k in keys:
        if k in expected and getattr(actual, k) != _norm(expected[k]):
            return False
    return True


def _norm(v):
    return tuple(v) if isinstance(v, list) else v


def _run(engine, pack, case):
    state = _state_before(engine, pack, case["state_before"])
    utt = _utterance(case)
    t0 = time.perf_counter()
    first = engine.judge(utt, pack, state)
    judge_ms = (time.perf_counter() - t0) * 1000
    state = engine.apply(state, first)
    results = [first]
    if first.needs_refine and case["expect"]["tier"] == "L3":
        second = asyncio.run(engine.refine(utt, pack, state))
        state = engine.apply(state, second)
        results.append(second)
    return results, state, judge_ms


@pytest.mark.parametrize("case", [c for c in CASES if "utterance" in c], ids=lambda c: c["name"])
def test_judge_case(engine, pack, case):
    results, state, judge_ms = _run(engine, pack, case)
    expect = case["expect"]
    verdicts = [v for r in results for v in r.verdicts]
    alerts = {(a.alert_type, a.item_code): a for r in results for a in r.alerts}
    assists = [a for r in results for a in r.assists]

    for ev in expect["verdicts"]:
        keys = ("item_code", "axis", "state", "decided_by", "missing_elements")
        assert any(_matches(v, ev, keys) for v in verdicts), (
            f"기대 verdict 없음: {ev}\n실제: {verdicts}"
        )
        if "ver" in ev:
            cur = state.state_of(ev["item_code"], ev["axis"])
            assert cur is not None and cur.ver >= ev["ver"], f"ver 기대 {ev['ver']} 실제 {cur}"
    if not expect["verdicts"]:
        assert verdicts == [], f"verdict 가 없어야 함: {verdicts}"
    else:
        touched = {(ev["item_code"], ev["axis"]) for ev in expect["verdicts"]}
        assert {(v.item_code, v.axis) for v in verdicts} <= touched, f"예상 밖 verdict: {verdicts}"

    assert len(alerts) == len(expect["alerts"]), (
        f"alert 수 기대 {expect['alerts']} 실제 {list(alerts.values())}"
    )
    for ea in expect["alerts"]:
        a = alerts.get((ea["alert_type"], ea.get("item_code")))
        assert a is not None, f"기대 alert 없음: {ea}"
        assert a.severity == ea["severity"]
        if ea.get("evidence_required"):
            assert a.evidence is not None
        if "comparison" in ea:
            assert a.comparison is not None
            for k, v in ea["comparison"].items():
                assert getattr(a.comparison, k) == v, (
                    f"comparison.{k}: {getattr(a.comparison, k)} != {v}"
                )
        if a.message:
            assert "잘못" not in a.message and "틀렸" not in a.message  # 비난 없는 문구

    assert len(assists) == len(expect["assists"]), (
        f"assist 수 기대 {expect['assists']} 실제 {assists}"
    )
    for ea in expect["assists"]:
        a = next(
            (x for x in assists if _matches(x, ea, ("assist_type", "item_code", "trigger"))), None
        )
        assert a is not None, f"기대 assist 없음: {ea}"
        if ea.get("source_utterance_ref_required"):
            assert a.source_utterance_ref
        if ea.get("from_plain_language"):
            assert a.text in pack.item(ea["item_code"]).plain_language

    budget = expect["max_ms"]
    print(
        f"[budget] {case['name']}: judge {judge_ms:.2f}ms (tier {expect['tier']}, max {budget}ms)"
    )
    if os.environ.get("MALTEUM_ENFORCE_BUDGET") == "1" and expect["tier"] != "L3":
        assert judge_ms <= budget


def test_l1_met_does_not_need_refine(engine, pack):
    case = next(c for c in CASES if c["name"].startswith("L1 키워드 전부"))
    results, _, _ = _run(engine, pack, case)
    assert results[0].needs_refine is False


def test_ask_without_evidence_returns_none(engine, pack):
    case = next(c for c in CASES if "ask" in c)
    state = engine.initial_state("S-TEST", pack, "text")
    assert engine.answer(case["ask"], pack, state) is None


def test_waived_requires_reason(engine, pack):
    case = next(c for c in CASES if "mark_waived" in c)
    state = _state_before(engine, pack, case["state_before"])
    w = case["mark_waived"]
    bad = JudgeResult(
        verdicts=(
            VerdictPayload(
                item_code=w["item_code"],
                axis="omission",
                state="waived",
                decided_by="human",
                waive_reason=w["reason"],
            ),
        )
    )
    with pytest.raises(ValueError, match="waive_reason"):
        engine.apply(state, bad)
    good = JudgeResult(
        verdicts=(
            VerdictPayload(
                item_code=w["item_code"],
                axis="omission",
                state="waived",
                decided_by="human",
                waive_reason="고객이 이미 보유한 대출로 대안 불필요",
            ),
        )
    )
    assert engine.apply(state, good).state_of(w["item_code"]).state == "waived"


def test_refine_second_call_hits_cache(pack_json):
    engine = _engine(pack_json)
    pack = engine.load_pack(PACK_VERSION)
    case = next(c for c in CASES if c["name"].startswith("요건 요소 일부만"))
    state = _state_before(engine, pack, case["state_before"])
    utt = _utterance(case)
    state = engine.apply(state, engine.judge(utt, pack, state))
    first = asyncio.run(engine.refine(utt, pack, state))
    second = asyncio.run(engine.refine(utt, pack, state))
    assert first.trace.l3_called is True and first.trace.cache_hit is False
    assert second.trace.cache_hit is True and second.trace.l3_called is False
    assert second.verdicts == first.verdicts


def test_answer_from_pack_item_and_rephrase(engine, pack):
    from contracts.engine_contract import Utterance

    state = engine.initial_state("S-TEST", pack, "text")
    a = engine.answer("중간에 깨면 이자가 어떻게 되나요?", pack, state)
    assert a is not None and a.assist_type == "answer" and a.item_code == "DEP-INT-002"
    assert a.evidence is not None and a.text in pack.item("DEP-INT-002").plain_language

    src = Utterance(
        utterance_id="U-T1",
        speaker="teller",
        text="우대이자율은 중도해지하시면 적용이 안 됩니다.",
        t_ms=1,
    )
    r = engine.rephrase(src, pack, state)
    assert r is not None and r.assist_type == "rephrase" and r.item_code == "DEP-INT-004"
    assert r.source_utterance_ref == "U-T1"
    nothing = Utterance(utterance_id="U-T2", speaker="teller", text="잠시만 기다려 주세요.", t_ms=2)
    assert engine.rephrase(nothing, pack, state) is None


def test_briefing_and_documents(engine, pack):
    state = engine.initial_state("S-TEST", pack, "text")
    b = engine.briefing(pack, "general")
    assert b.assist_type == "briefing" and "5개" in b.text
    d = engine.documents(pack, state)
    assert (
        d.assist_type == "documents" and "실명확인증표" in d.text and d.item_code == "DEP-DOC-001"
    )
