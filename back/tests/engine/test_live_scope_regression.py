"""OpenRouter Qwen3-8B 의미 귀속 회귀. 캐시 없이 각 사례를 3회 호출한다.

MALTEUM_LIVE_REGRESSION=1 uv run pytest tests/engine/test_live_scope_regression.py -s
MALTEUM_SCOPE_REPEATS=1 이면 1회만 호출한다(선별용). 보고에는 3회 결과를 쓴다.
호출 실패·시간 초과는 음성 사례의 성공으로 세지 않는다. 3초 예산은 A 음성 E2E로 검증한다.
"""

import json
import os
import time
from pathlib import Path

import pytest

from contracts.engine_contract import ItemState, Utterance
from engine.adapters.llm.litellm import LiteLlmJudge
from engine.pack.loader import load_pack
from engine.tiers.l3 import decision_parser, prompt_builder
from engine.types import SessionState
from server.bootstrap.settings import Settings
from tests.engine.conftest import FIX
from tests.engine.fakes import FakePackSource

pytestmark = pytest.mark.skipif(
    os.getenv("MALTEUM_LIVE_REGRESSION") != "1", reason="OpenRouter 반복 검증 명시 실행만 허용"
)

REPEATS = range(1, 1 + int(os.getenv("MALTEUM_SCOPE_REPEATS", "3")))
# MALTEUM_SCOPE_UNSEEN: 1 둘 다(기본) · 0 회귀셋만(선별용) · only 미사용만. 미사용셋은 튜닝 금지
_UNSEEN = os.getenv("MALTEUM_SCOPE_UNSEEN", "1")

RATE_ONLY = "연체하시면 대출이자율에 연체가산이자율 연 3%가 더해진 연체이자율이 적용됩니다."
CASES = [
    ("B13", RATE_ONLY, None, ()),
    ("rate-paraphrase", "납부가 늦어지면 기존 금리에 추가 이자가 붙습니다.", None, ()),
    ("unrelated", "신분증을 준비해 주세요.", None, ()),
    (
        "lapse-cause",
        "이자를 한 달 넘게 밀리면 기한이익을 상실합니다.",
        "partial",
        ("상실 시 불이익",),
    ),
    (
        "lapse-consequence",
        "기한이익을 잃은 경우 남은 원금을 한꺼번에 갚으셔야 합니다.",
        "partial",
        ("기한이익상실 사유",),
    ),
    (
        "lapse-paraphrase",
        "이자를 한 달 넘게 내지 않으시면 만기를 기다릴 수 없고 "
        "빌린 돈을 한 번에 모두 돌려주셔야 합니다.",
        "met",
        (),
    ),
]


@pytest.mark.skipif(_UNSEEN == "only", reason="미사용 검증셋만 실행")
@pytest.mark.parametrize("repeat", REPEATS)
@pytest.mark.parametrize("name,text,expected,missing", CASES, ids=[c[0] for c in CASES])
def test_live_item_scope(name, text, expected, missing, repeat):
    settings = Settings()
    assert settings.llm_api_key, "OpenRouter API 키가 필요합니다"
    raw = json.loads((FIX / "rulepack_LOAN-2026.08-v7.json").read_text(encoding="utf-8"))
    pack = load_pack(FakePackSource(raw), raw["pack_version"])
    state = SessionState(
        "S",
        pack.pack_version,
        "text",
        items=(ItemState("LOAN-EXP-001", "omission", "unmet", "L1", 0),),
    )
    prompt = prompt_builder.build(text, pack, state, ["LOAN-EXP-001"], "qwen/qwen3-8b", "teller")
    model = "qwen/qwen3-8b"
    judge = LiteLlmJudge(
        model,
        provider="openrouter",
        api_key=settings.llm_api_key,
        extra_body={"reasoning": {"enabled": False}},
    )
    started = time.perf_counter()
    decision = judge.decide(prompt)
    print(
        f"\n{model} {name} r{repeat}: {(time.perf_counter() - started) * 1000:.0f}ms "
        f"tokens={decision.tokens} verdicts={decision.verdicts}"
    )
    assert decision.tokens and not decision.from_cache
    verdicts, alerts, assists, rejected = decision_parser.parse(
        decision,
        pack,
        SessionState("S", pack.pack_version, "text"),
        Utterance("U", "teller", text, 0),
    )
    print(f"  accepted={verdicts} rejected={rejected}")
    assert alerts == []
    if expected is None:
        assert verdicts == [] and assists == []
    else:
        (verdict,) = verdicts
        assert verdict.item_code == "LOAN-EXP-001"
        assert verdict.state == expected
        assert set(verdict.missing_elements) == set(missing)


def _cases(name: str) -> list[dict]:
    return json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))["cases"]


# scope_holdout.json 은 결과를 이미 봤으므로 회귀셋이다. scope_holdout2.json 은 주제 귀속 수정
# 뒤에 처음 실행하는 미사용 검증셋이며, 첫 실행 후 기대값을 바꾸지 않는다.
HOLDOUT = [
    *(_cases("scope_holdout.json") if _UNSEEN != "only" else []),
    *(_cases("scope_holdout2.json") if _UNSEEN != "0" else []),
]


@pytest.mark.parametrize("repeat", REPEATS)
@pytest.mark.parametrize("case", HOLDOUT, ids=[c["name"] for c in HOLDOUT])
def test_live_holdout(case, repeat):
    settings = Settings()
    assert settings.llm_api_key, "OpenRouter API 키가 필요합니다"
    raw = json.loads((FIX / f"rulepack_{case['pack']}.json").read_text(encoding="utf-8"))
    pack = load_pack(FakePackSource(raw), raw["pack_version"])
    target = case["target"]
    context = (
        (Utterance("prior", case["context_speaker"], case["context"], 0),)
        if "context" in case
        else ()
    )
    state = SessionState(
        "S",
        pack.pack_version,
        "text",
        items=(
            ItemState(
                target,
                "omission",
                "partial" if "before_missing" in case else "unmet",
                "L3" if "before_missing" in case else "L1",
                0,
                missing_elements=tuple(case.get("before_missing", ())),
            ),
        ),
        recent_utterances=context,
    )
    utterance = Utterance("current", case.get("speaker", "teller"), case["text"], 1)
    candidates = [target, *([case["additional_target"]] if "additional_target" in case else [])]
    prompt = prompt_builder.build(
        utterance.text, pack, state, candidates, "qwen/qwen3-8b", utterance.speaker
    )
    judge = LiteLlmJudge(
        "qwen/qwen3-8b",
        provider="openrouter",
        api_key=settings.llm_api_key,
        extra_body={"reasoning": {"enabled": False}},
    )
    started = time.perf_counter()
    decision = judge.decide(prompt)
    elapsed = (time.perf_counter() - started) * 1000
    assert decision.tokens and not decision.from_cache
    result = decision_parser.parse(decision, pack, state, utterance)

    def outcome(result):
        return [
            {"state": v.state, "missing": sorted(v.missing_elements)}
            for v in result[0]
            if v.item_code == target
        ]

    expected = (
        [{"state": case["expected"], "missing": sorted(case.get("missing", []))}]
        if case["expected"] is not None
        else []
    )
    print(
        "\nHOLDOUT "
        + json.dumps(
            {
                "name": case["name"],
                "repeat": repeat,
                "ms": round(elapsed),
                "tokens": decision.tokens,
                "expected": expected,
                "actual": outcome(result),
                "passed": outcome(result) == expected,
            },
            ensure_ascii=False,
        )
    )
    assert outcome(result) == expected


@pytest.mark.skipif(_UNSEEN == "only", reason="미사용 검증셋만 실행")
def test_live_refine_graph_keeps_other_topic_out_and_reuses_cache():
    """통합 경로: L1 → L2(실물 e5 임베더) 후보 → refine 그래프 → L3 → 캐시.

    집중 검사는 후보를 고정하지만 여기서는 엔진이 후보를 고른다. 연체금리 문장으로 기한이익상실이
    후보에 올라와도 L3 가 판정하지 않아야 하고, 같은 입력의 두 번째 refine 은 캐시를 써야 한다.
    """
    import asyncio

    from engine.adapters.cache.memory import MemoryDecisionCache
    from engine.adapters.embedder.local import LocalStEmbedder
    from engine.adapters.vector_index.memory import MemoryVectorIndex
    from engine.build import build_engine
    from tests.engine.fakes import FakeChunkIndex

    settings = Settings()
    assert settings.llm_api_key, "OpenRouter API 키가 필요합니다"
    raw = json.loads((FIX / "rulepack_LOAN-2026.08-v7.json").read_text(encoding="utf-8"))
    embedder = LocalStEmbedder(settings.embedding_model or "intfloat/multilingual-e5-small")
    engine = build_engine(
        FakePackSource(raw),
        embedder,
        MemoryVectorIndex(),
        FakeChunkIndex([], embedder),
        LiteLlmJudge(
            "qwen/qwen3-8b",
            provider="openrouter",
            api_key=settings.llm_api_key,
            extra_body={"reasoning": {"enabled": False}},
        ),
        MemoryDecisionCache(),
        l3_budget_ms=30_000,  # 품질 검사. 3초 예산 통과는 음성 E2E 에서 따로 본다
    )
    pack = engine.load_pack(raw["pack_version"])
    state = engine.initial_state("S", pack, "text")

    def step(state, uid, text):
        utt = Utterance(uid, "teller", text, int(uid[1:]) * 1000, speaker_confidence=0.95)
        state = engine.observe(state, utt)
        first = engine.judge(utt, pack, state)
        state = engine.apply(state, first)
        second = asyncio.run(engine.refine(utt, pack, state))
        state = engine.apply(state, second)
        print(
            f"\n{uid} l1={[(v.item_code, v.state) for v in first.verdicts]} "
            f"l2_candidates={second.trace.l2_candidates} l3_ms={second.trace.l3_ms:.0f} "
            f"cache_hit={second.trace.cache_hit} "
            f"l3={[(v.item_code, v.state, v.missing_elements) for v in second.verdicts]}"
        )
        return state, first, second

    # 1) 연체금리만 말했다. 연체이자율은 L1 met, 기한이익상실은 그대로 unmet 이어야 한다
    state, first, second = step(state, "U1", RATE_ONLY)
    assert state.state_of("LOAN-ARR-001").state == "met"
    assert second.trace.l3_called and not second.trace.cache_hit
    assert state.state_of("LOAN-EXP-001").state == "unmet", second.verdicts
    # 같은 입력을 다시 refine 하면 캐시를 쓰고 결과가 같다 (캐시 키에 프롬프트 버전 포함)
    again = asyncio.run(
        engine.refine(
            Utterance("U1", "teller", RATE_ONLY, 1000, speaker_confidence=0.95), pack, state
        )
    )
    assert again.trace.cache_hit and not again.trace.l3_called
    assert engine.apply(state, again) == state

    # 2) 기한이익상실 사유를 말했다. L1 은 요소 하나뿐이라 판정하지 않고 L3 가 partial 로 올린다
    state, first, second = step(state, "U2", "이자를 한 달 넘게 밀리면 기한이익을 상실합니다.")
    assert [(v.item_code, v.state) for v in first.verdicts] == []
    assert second.trace.l3_called
    exp = state.state_of("LOAN-EXP-001")
    assert (exp.state, exp.decided_by, exp.missing_elements) == (
        "partial",
        "L3",
        ("상실 시 불이익",),
    )

    # 3) 이어서 불이익을 말했다. 이전에 채운 사유는 다시 요구하지 않고 met 이 된다.
    #    "한꺼번에 갚" 은 L1 정규식에도 잡히므로 L1 이 먼저 올릴 수 있다. 주체가 아니라 상태를 본다
    state, first, second = step(
        state, "U3", "그 경우에는 남은 대출금을 만기 전에 한꺼번에 갚으셔야 합니다."
    )
    exp = state.state_of("LOAN-EXP-001")
    assert (exp.state, exp.missing_elements) == ("met", ()), (first.verdicts, second.verdicts)
