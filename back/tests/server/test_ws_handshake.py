"""hello → ready, ping → pong, end → ended. ws_protocol 스키마 기준."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app
from server.ws.protocol import FRAME_BYTES, PCM_BYTES, check_s2c

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

        # replay 는 ready 직후 서버가 스스로 시작한다(계약). STT 가 없어 못 하는 사정을
        # 먼저 보내오므로 그것을 지나 하트비트를 본다
        autostart = sock.receive_json()
        check_s2c(autostart)
        assert autostart["t"] == "error" and autostart["code"] == "stt_unavailable"

        ping = sock.receive_json()
        check_s2c(ping)
        assert ping == {"t": "ping", "seq": 2}
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


def test_audio_frame_answers_stt_unavailable_once_and_keeps_socket():
    """마이크를 켜면 100ms 마다 바이너리가 온다. 소켓이 죽지 않아야 하고,
    조각마다 답하면 화면이 오류로 뒤덮이므로 한 번만 알린다."""
    frame = (1).to_bytes(4, "big") + b"\x00" * PCM_BYTES
    with _client() as client, client.websocket_connect("/ws") as sock:
        sock.send_json({"t": "hello", "mode": "live"})
        assert sock.receive_json()["t"] == "ready"

        sock.send_bytes(frame)
        err = sock.receive_json()
        check_s2c(err)
        # 계약: 이 코드를 받으면 프런트가 text 모드 전환을 제안한다 (3층 폴백)
        assert err["code"] == "stt_unavailable" and err["retryable"] is True

        sock.send_bytes((2).to_bytes(4, "big") + b"\x00" * PCM_BYTES)
        sock.send_json({"t": "end"})  # 두 번째 조각에는 답이 없어야 한다
        got = sock.receive_json()
        while got["t"] == "ping":
            got = sock.receive_json()
        assert got["t"] == "ended"


def test_replay_autostarts_and_says_why_it_cannot():
    """계약: replay·trace 는 ready 직후 서버가 스스로 시작한다. 시작 메시지는 없다.

    STT 가 없어 replay 를 못 흘리더라도 침묵하면 안 된다. 화면이 영원히 기다린다.
    """
    with _client() as client, client.websocket_connect("/ws") as sock:
        sock.send_json({"t": "hello", "mode": "replay", "session_id": "FIXT-SESS-0A"})
        assert sock.receive_json()["t"] == "ready"
        got = sock.receive_json()
        while got["t"] == "ping":
            got = sock.receive_json()
        check_s2c(got)
        assert got["t"] == "error" and got["code"] == "stt_unavailable"


def test_ask_and_assist_request_answer_instead_of_hanging():
    """계약 c2s 10종이 모두 답을 받는다. 엔진의 assist 가 아직 없어도 침묵하면 안 된다.

    은행원이 버튼을 눌렀는데 아무 일도 안 일어나면 고장인지 근거가 없는 것인지
    구분할 수 없다.
    """
    with _client() as client, client.websocket_connect("/ws") as sock:
        sock.send_json({"t": "hello", "mode": "text", "session_id": "SMOKE-ASSIST-01"})
        assert sock.receive_json()["t"] == "ready"

        for msg in (
            {"t": "ask", "question": "중도해지하면 이자가 어떻게 되나요?"},
            {"t": "assist_request", "assist_type": "briefing"},
            {"t": "assist_request", "assist_type": "documents"},
        ):
            sock.send_json(msg)
            got = sock.receive_json()
            while got["t"] == "ping":
                got = sock.receive_json()
            check_s2c(got)
            # 지금 엔진은 NotImplementedError 를 던진다. 붙으면 assist 가 온다
            assert got["t"] in ("assist", "error")

        # rephrase 는 다시 말할 직전 발화가 있어야 한다
        sock.send_json({"t": "assist_request", "assist_type": "rephrase"})
        got = sock.receive_json()
        while got["t"] == "ping":
            got = sock.receive_json()
        assert got["t"] == "error" and "직전 발화" in got["message"]


def test_malformed_audio_frame_is_rejected_every_time():
    """길이가 어긋난 프레임은 프런트가 잘못 만들고 있다는 뜻이라 매번 알린다.
    조용히 버리면 마이크가 안 되는 이유를 아무도 못 찾는다."""
    with _client() as client, client.websocket_connect("/ws") as sock:
        sock.send_json({"t": "hello", "mode": "live"})
        assert sock.receive_json()["t"] == "ready"
        for _ in range(2):
            sock.send_bytes(b"\x00" * 10)
            err = sock.receive_json()
            assert err["t"] == "error" and err["code"] == "invalid_message"
            assert str(FRAME_BYTES) in err["message"]
