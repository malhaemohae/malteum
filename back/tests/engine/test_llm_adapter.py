"""LiteLlmJudge 의 응답 처리. litellm.completion 을 바꿔 끼워 네트워크 없이 검사한다."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from contracts.engine_contract import ItemState, JudgePrompt
from engine.adapters.llm import litellm as adapter
from engine.errors import LlmUnavailable
from engine.pack.loader import load_pack
from engine.tiers.l3 import tools
from tests.engine.conftest import PACK_VERSION
from tests.engine.fakes import FakePackSource


def _prompt(pack_json) -> JudgePrompt:
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    items = (pack.item("DEP-INT-002"), pack.item("DEP-BAN-001"))
    states = (ItemState("DEP-INT-002", "omission", "unmet", "L1", 0),)
    return JudgePrompt(
        "중도해지하시면 이자가 좀 줄어듭니다.", "teller", (), items, states, "general", "k"
    )


def _response(args: dict | str, name: str = tools.TOOL_NAME):
    payload = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=payload))
    msg = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=42)
    )


def test_tool_schema_enums_come_from_candidates(pack_json):
    tool = tools.judge_tool(_prompt(pack_json))
    props = tool["function"]["parameters"]["properties"]["verdicts"]["items"]["properties"]
    assert props["item_code"]["enum"] == ["DEP-INT-002", "DEP-BAN-001"]
    assert "차감률 또는 산출식" in props["stated_elements"]["items"]["enum"]
    assert "waived" not in props["state"]["enum"]
    params = tool["function"]["parameters"]
    # 생성 순서 = 판정 순서: 주제 → 후보별 관계 → 판정
    assert list(params["properties"])[:3] == ["utterance_topic", "topic_relations", "verdicts"]
    assert params["properties"]["topic_relations"]["items"]["properties"]["item_code"]["enum"] == [
        "DEP-INT-002",
        "DEP-BAN-001",
    ]


def test_decide_parses_forced_tool_call(pack_json, monkeypatch):
    seen = {}

    def fake_completion(**kw):
        seen.update(kw)
        return _response(
            {
                "utterance_topic": "중도해지 시 이자 감소",
                "topic_relations": [
                    {"item_code": "DEP-INT-002", "relation": "explains_item"},
                    {"item_code": "DEP-BAN-001", "relation": "unrelated"},
                ],
                "verdicts": [
                    {
                        "item_code": "DEP-INT-002",
                        "axis": "omission",
                        "state": "met",  # 모델의 state 는 무시하고 stated_elements 로 계산한다
                        "stated_elements": ["만기 전 해지 시 불이익"],
                        "confidence": 0.8,
                    }
                ],
            }
        )

    monkeypatch.setattr(adapter.litellm, "completion", fake_completion)
    d = adapter.LiteLlmJudge("x", provider="openrouter", api_key="k").decide(_prompt(pack_json))
    assert seen["model"] == "openrouter/x"
    assert seen["tool_choice"]["function"]["name"] == tools.TOOL_NAME
    assert seen["messages"][0]["role"] == "system"
    body = json.loads(seen["messages"][1]["content"])
    assert body["speaker"] == "teller" and list(body)[-1] == "utterance"  # 발화는 본문 마지막
    assert d.tokens == 42
    (v,) = d.verdicts
    assert (v.item_code, v.state, v.decided_by) == ("DEP-INT-002", "partial", "L3")
    assert v.missing_elements == ("적용 이율", "차감률 또는 산출식")


def test_decide_retries_once_on_schema_violation_then_gives_up(pack_json, monkeypatch):
    calls = []

    def fake_completion(**kw):
        calls.append(kw["messages"])
        return _response(
            {
                "utterance_topic": "t",
                "topic_relations": [],
                "verdicts": [{"item_code": "NOPE", "axis": "omission", "state": "met"}],
            }
        )

    monkeypatch.setattr(adapter.litellm, "completion", fake_completion)
    with pytest.raises(LlmUnavailable, match="재시도 소진"):
        adapter.LiteLlmJudge("openrouter/x").decide(_prompt(pack_json))
    assert len(calls) == 2
    assert "형식 오류" in calls[1][-1]["content"]


def test_decide_retry_can_succeed(pack_json, monkeypatch):
    answers = iter(
        [
            _response("not json"),
            _response({"utterance_topic": "t", "topic_relations": [], "verdicts": []}),
        ]
    )
    monkeypatch.setattr(adapter.litellm, "completion", lambda **kw: next(answers))
    d = adapter.LiteLlmJudge("openrouter/x").decide(_prompt(pack_json))
    assert d.verdicts == ()


def test_transport_error_becomes_llm_unavailable(pack_json, monkeypatch):
    def boom(**kw):
        raise ConnectionError("down")

    monkeypatch.setattr(adapter.litellm, "completion", boom)
    with pytest.raises(LlmUnavailable, match="ConnectionError"):
        adapter.LiteLlmJudge("openrouter/x").decide(_prompt(pack_json))


def test_parser_drops_missing_elements_outside_omission(pack_json):
    from contracts.engine_contract import JudgeDecision, Utterance, VerdictPayload
    from engine.tiers.l3 import decision_parser
    from engine.types import SessionState

    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    state = SessionState("S", PACK_VERSION, "text")
    utt = Utterance("U1", "teller", "무조건 이득이에요.", 1)
    d = JudgeDecision(
        verdicts=(
            VerdictPayload(
                "DEP-BAN-001", "commission", "violated", "L3", missing_elements=("단정",)
            ),
        )
    )
    (v,), _, _, rejected = decision_parser.parse(d, pack, state, utt)
    assert v.state == "violated" and v.missing_elements == () and rejected == []


def test_other_topic_relation_drops_the_verdict(pack_json, monkeypatch):
    """주제가 다른 항목(연체이자 → 기한이익상실)이면 verdict 를 내도 버린다."""

    def fake_completion(**kw):
        body = json.loads(kw["messages"][1]["content"])
        assert "세금" in body["other_items"] and "중도해지 이자율" not in body["other_items"]
        return _response(
            {
                "utterance_topic": "세금 공제",
                "topic_relations": [{"item_code": "DEP-INT-002", "relation": "other_topic"}],
                "verdicts": [
                    {
                        "item_code": "DEP-INT-002",
                        "axis": "omission",
                        "state": "partial",
                        "stated_elements": ["만기 전 해지 시 불이익"],
                    }
                ],
            }
        )

    monkeypatch.setattr(adapter.litellm, "completion", fake_completion)
    pack = load_pack(FakePackSource(pack_json), PACK_VERSION)
    from engine.tiers.l3 import prompt_builder
    from engine.types import SessionState

    prompt = prompt_builder.build(
        "세금 뗀 금액이 입금됩니다",
        pack,
        SessionState("S", PACK_VERSION, "text"),
        ["DEP-INT-002"],
        "x",
        "teller",
    )
    d = adapter.LiteLlmJudge("x", provider="openrouter", api_key="k").decide(prompt)
    assert d.verdicts == ()
