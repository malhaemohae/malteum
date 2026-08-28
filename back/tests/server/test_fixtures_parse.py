"""contracts/fixtures 가 생성 모델(server/generated)로 전부 파싱되는가.

스키마와 fixture 가 함께 바뀌면 이 테스트가 먼저 깨진다.
"""

import json
from pathlib import Path

import pytest

from server.generated import events, ws

FIX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


WS_MESSAGES = _load("ws_messages.json")
EVENTS = _load("events_scenario_a.json")


def test_fixture_counts():
    assert len(WS_MESSAGES) == 26
    assert len(EVENTS) == 31


@pytest.mark.parametrize("msg", WS_MESSAGES, ids=[m["t"] for m in WS_MESSAGES])
def test_ws_message_parses(msg):
    if msg["t"] in ws.C2S_TYPES:
        parsed = ws.c2s_adapter.validate_python(msg)
    else:
        parsed = ws.s2c_adapter.validate_python(msg)
    assert parsed.t == msg["t"]
    assert parsed.model_dump(mode="json", exclude_none=True) == {
        **_defaults(parsed),
        **msg,
    }


@pytest.mark.parametrize("event", EVENTS, ids=[e["event_id"] for e in EVENTS])
def test_event_parses(event):
    parsed = events.event_adapter.validate_python(event)
    assert parsed.kind == event["kind"]
    assert parsed.event_id == event["event_id"]


def test_ws_rejects_unknown_field():
    with pytest.raises(ValueError):
        ws.c2s_adapter.validate_python({"t": "hello", "mode": "live", "bogus": 1})


def test_ws_rejects_missing_required():
    with pytest.raises(ValueError):
        ws.c2s_adapter.validate_python({"t": "resume", "session_id": "FIXT-SESS-0A"})


def _defaults(model) -> dict:
    """fixture 에 없지만 스키마 default 로 채워지는 필드 (예: text_utterance.speaker)."""
    dumped = model.model_dump(mode="json", exclude_none=True)
    return {k: v for k, v in dumped.items() if k not in model.model_fields_set}
