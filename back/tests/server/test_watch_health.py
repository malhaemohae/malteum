"""외부 감시가 무엇을 이상으로 보는지 (scripts/watch_health.py).

기획 16장 리스크 5 는 **9/7~9/11 접속 불가를 결격**으로 적었고, 이 스크립트가 그 대응책의
"외부 헬스체크 알림" 이다. 판정이 틀리면 나흘 동안 장애를 못 알아챈다 — 특히 **뜨는데
망가진 상태**(db 가 죽어 `status=degraded`)를 정상으로 읽으면 아무도 모른다.

네트워크를 쓰지 않는다. `urlopen` 을 갈아끼워 응답만 흉내 낸다.
"""

import json
import sys
from io import BytesIO
from pathlib import Path

import pytest

_SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import watch_health  # noqa: E402


class _Response:
    def __init__(self, body: dict, status: int = 200) -> None:
        self.status = status
        self._buf = BytesIO(json.dumps(body).encode())

    def read(self, *a):
        return self._buf.read(*a)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _probe_with(monkeypatch, outcome):
    """`outcome` 이 dict 면 그 본문을, 예외면 그것을 던진다."""

    def fake(url, timeout=None):
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(*outcome) if isinstance(outcome, tuple) else _Response(outcome)

    monkeypatch.setattr(watch_health.urllib.request, "urlopen", fake)
    return watch_health.probe("https://example.test", 5)


def test_healthy_server_is_ok(monkeypatch):
    state, why = _probe_with(
        monkeypatch,
        {"status": "ok", "version": "0.1.0", "checks": {"db": "ok", "stt": "unconfigured"}},
    )
    assert state == watch_health.OK
    assert "0.1.0" in why and "db=ok" in why


def test_degraded_is_not_read_as_healthy(monkeypatch):
    """**뜨는데 망가진 상태.** 200 만 보면 통과한다 — 그래서 status·checks 를 본다.

    db 가 죽으면 판정도 저장도 안 되는데 화면은 붙어 있다. 이걸 정상으로 읽는 것이
    이 감시가 막아야 할 가장 나쁜 실패다.
    """
    state, why = _probe_with(
        monkeypatch,
        {"status": "degraded", "version": "0.1.0", "checks": {"db": "fail", "stt": "ok"}},
    )
    assert state == watch_health.DEGRADED
    assert "db" in why


def test_contract_unknown_status_is_treated_as_trouble(monkeypatch):
    """계약 status enum 은 ok·degraded 둘. 모르는 값이면 서버가 계약을 어긴 것이라
    정상으로 넘기지 않는다."""
    state, _ = _probe_with(monkeypatch, {"status": "starting", "checks": {}})
    assert state == watch_health.DEGRADED


@pytest.mark.parametrize(
    "outcome",
    [
        ConnectionRefusedError("죽었거나 회선이 끊김"),
        TimeoutError("응답 없음"),
        ({"status": "ok"}, 503),
        ValueError("JSON 이 아님"),
    ],
    ids=["연결 거부", "타임아웃", "HTTP 503", "본문이 JSON 아님"],
)
def test_anything_that_is_not_a_healthy_answer_is_unreachable(monkeypatch, outcome):
    """감시가 예외로 죽으면 안 된다. 어떤 실패든 판정으로 바꿔 돌려준다."""
    state, why = _probe_with(monkeypatch, outcome)
    assert state == watch_health.UNREACHABLE
    assert why


def test_exit_codes_are_distinct():
    """`--once` 는 cron·uptime 서비스가 종료 코드로 읽는다. 겹치면 구분이 사라진다."""
    assert watch_health.EXIT[watch_health.OK] == 0
    assert len(set(watch_health.EXIT.values())) == 3


def test_alert_failure_does_not_kill_the_watcher(monkeypatch, capsys):
    """알림이 안 가는 것보다 감시가 죽는 것이 나쁘다. 웹훅이 터져도 계속 돌아야 한다."""

    def boom(*a, **kw):
        raise OSError("웹훅 죽음")

    monkeypatch.setattr(watch_health.urllib.request, "urlopen", boom)
    watch_health.notify("접속 불가", "https://hook.test")  # 예외가 새면 여기서 실패한다
    assert "감시는 계속한다" in capsys.readouterr().err
