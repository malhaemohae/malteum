"""hello → ready, ping → pong, end → ended. ws_protocol 스키마 기준."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app
from server.ws.protocol import check_s2c

FIX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def _client() -> TestClient:
    return TestClient(create_app(Settings(ws_ping_interval_s=0.05, event_store="memory")))


def test_hello_ready_ping_pong_end():
    messages = json.loads((FIX / "ws_messages.json").read_text(encoding="utf-8"))
    fixture_ready = next(m for m in messages if m["t"] == "ready")
    with _client() as client, client.websocket_connect("/ws") as sock:
        sock.send_json({"t": "hello", "mode": "replay", "session_id": "FIXT-SESS-0A"})
        ready = sock.receive_json()
        check_s2c(ready)
        assert ready["t"] == "ready" and ready["seq"] == 0
        assert ready["session_id"] == "FIXT-SESS-0A"
        assert ready["pack_version"] == "DEP-2026.08-v4"
        # 초기 체크리스트가 fixture 와 같다. plain_language 는 fixture 가 축약본이라 포함만 본다
        strip = lambda it: {k: v for k, v in it.items() if k != "plain_language"}  # noqa: E731
        assert [strip(i) for i in ready["items"]] == [strip(i) for i in fixture_ready["items"]]
        for ours, theirs in zip(ready["items"], fixture_ready["items"], strict=True):
            for sentence in theirs.get("plain_language", []):
                assert sentence in ours["plain_language"]

        ping = sock.receive_json()
        check_s2c(ping)
        assert ping == {"t": "ping", "seq": 1}
        sock.send_json({"t": "pong"})

        sock.send_json({"t": "end"})
        ended = sock.receive_json()
        while ended["t"] == "ping":  # 하트비트가 끼어들 수 있다
            ended = sock.receive_json()
        check_s2c(ended)
        assert ended["t"] == "ended"
        # 필수 항목 수는 팩에서 센다. 숫자를 박으면 팩이 바뀔 때마다 이 줄만
        # 고치게 되고, 무엇이 왜 달라졌는지가 안 남는다 (2026-08-30).
        required = sum(1 for i in fixture_ready["items"] if i.get("required"))
        assert ended["summary"]["items_total"] == required
        # 발화 없이 끝냈으므로 미충족 수는 필수 항목 전체와 같다
        assert ended["summary"]["unmet"] == required


def test_invalid_message_gets_error_not_disconnect():
    with _client() as client, client.websocket_connect("/ws") as sock:
        sock.send_json({"t": "hello"})  # mode 누락
        err = sock.receive_json()
        assert err["t"] == "error" and err["code"] == "invalid_message"
        sock.send_json({"t": "text_utterance", "text": "안녕"})  # hello 전
        assert sock.receive_json()["code"] == "invalid_message"
