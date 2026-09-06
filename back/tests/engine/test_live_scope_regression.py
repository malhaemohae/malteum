"""OpenRouter Qwen3-8B 의미 귀속 회귀. 캐시 없이 각 사례를 3회 호출한다.

MALTEUM_LIVE_REGRESSION=1 uv run pytest tests/engine/test_live_scope_regression.py -s
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


@pytest.mark.parametrize("repeat", range(1, 4))
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


HOLDOUT = json.loads(Path(__file__).with_name("scope_holdout.json").read_text(encoding="utf-8"))[
    "cases"
]


@pytest.mark.parametrize("repeat", range(1, 4))
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
