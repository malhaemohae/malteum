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
    assert "차감률 또는 산출식" in props["missing_elements"]["items"]["enum"]
    assert "waived" not in props["state"]["enum"]


def test_decide_parses_forced_tool_call(pack_json, monkeypatch):
    seen = {}

    def fake_completion(**kw):
        seen.update(kw)
        return _response(
            {
                "verdicts": [
                    {
                        "item_code": "DEP-INT-002",
                        "axis": "omission",
                        "state": "partial",
                        "missing_elements": ["적용 이율", "차감률 또는 산출식"],
                        "confidence": 0.8,
                    }
                ]
            }
        )

    monkeypatch.setattr(adapter.litellm, "completion", fake_completion)
    d = adapter.LiteLlmJudge("x", provider="openrouter", api_key="k").decide(_prompt(pack_json))
    assert seen["model"] == "openrouter/x"
    assert seen["tool_choice"]["function"]["name"] == tools.TOOL_NAME
    assert seen["messages"][0]["role"] == "system"
    assert '"speaker": "teller"' in seen["messages"][1]["content"]
    assert d.tokens == 42
    (v,) = d.verdicts
    assert (v.item_code, v.state, v.decided_by) == ("DEP-INT-002", "partial", "L3")
    assert v.missing_elements == ("적용 이율", "차감률 또는 산출식")


def test_decide_retries_once_on_schema_violation_then_gives_up(pack_json, monkeypatch):
    calls = []

    def fake_completion(**kw):
        calls.append(kw["messages"])
        return _response({"verdicts": [{"item_code": "NOPE", "axis": "omission", "state": "met"}]})

    monkeypatch.setattr(adapter.litellm, "completion", fake_completion)
    with pytest.raises(LlmUnavailable, match="재시도 소진"):
        adapter.LiteLlmJudge("openrouter/x").decide(_prompt(pack_json))
    assert len(calls) == 2
    assert "형식 오류" in calls[1][-1]["content"]


def test_decide_retry_can_succeed(pack_json, monkeypatch):
    answers = iter([_response("not json"), _response({"verdicts": []})])
    monkeypatch.setattr(adapter.litellm, "completion", lambda **kw: next(answers))
    d = adapter.LiteLlmJudge("openrouter/x").decide(_prompt(pack_json))
    assert d.verdicts == ()


def test_transport_error_becomes_llm_unavailable(pack_json, monkeypatch):
    def boom(**kw):
        raise ConnectionError("down")

    monkeypatch.setattr(adapter.litellm, "completion", boom)
    with pytest.raises(LlmUnavailable, match="ConnectionError"):
        adapter.LiteLlmJudge("openrouter/x").decide(_prompt(pack_json))
