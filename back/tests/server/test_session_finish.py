"""종료는 잔여 전사와 예약된 보정을 끝낸 뒤에 확정된다.

실측(`front/BACKEND_INTEGRATION_FINDINGS_20260905.md` 2절)에서 영구 이벤트가 이렇게
남았다.

    29  session_ended   13:10:25.174
    30  utterance       13:10:26.821
    31  utterance       13:10:26.838
    32  utterance       13:10:26.851

발화 단위 어댑터의 마지막 구간은 뒤에 무음이 오지 않아 `aclose()` 에서만 닫힌다
(`stt/openai_file.py`). 그 `aclose()` 가 `finally` 에 있어 `ended` 를 보낸 뒤에 돌았다.
그래서 프런트는 `ended` 를 받고 리포트로 넘어가 버리고, 마지막 발화는 화면에도 그때
조회한 리포트에도 못 들어간다. 나중에 다시 열면 내용이 달라져 있다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from server.bootstrap.settings import Settings
from server.main import create_app
from server.services.session.pipeline import Pipeline
from server.services.session.refiner import Refiner
from server.services.stt.base import Transcript

LAST_WORDS = "마지막으로 중도해지 시 이자를 안내드립니다."


class _HeldToTheEndStream:
    """마지막 발화를 닫을 때가 되어서야 내주는 스트림.

    발화 단위 어댑터가 실제로 이렇게 돈다. 구간을 닫는 조건이 "뒤에 무음"이라, 상담의
    마지막 구간은 스스로 닫히지 못하고 `aclose()` 를 기다린다.
    """

    def __init__(self, on_transcript) -> None:
        self.on_transcript = on_transcript

    async def send(self, pcm: bytes) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def aclose(self) -> None:
        await self.on_transcript(Transcript(text=LAST_WORDS, final=True))


class _HeldToTheEndAdapter:
    async def open(self, on_transcript, keyterms=(), *, diarization=None):
        return _HeldToTheEndStream(on_transcript)


def _client(finish_budget_s: float = 15.0) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                ws_ping_interval_s=60.0,
                event_store="memory",
                # 역할 붙잡기(DEC-7)는 여기서 보는 것이 아니다. 3초를 그대로 두면
                # 이 테스트가 무엇을 재는지 흐려진다
                speaker_hold_ms=0,
                session_finish_budget_s=finish_budget_s,
            )
        )
    )


def test_the_last_utterance_arrives_before_the_end_is_confirmed():
    """`ended` 앞에 마지막 발화가 온다. 뒤에 오면 프런트는 그것을 볼 기회가 없다."""
    sid = "END-ORDER-TEST-1"
    with _client() as client:
        app = client.app
        app.state.runtime = replace(app.state.runtime, stt=_HeldToTheEndAdapter())
        with client.websocket_connect("/ws") as sock:
            sock.send_json({"t": "hello", "mode": "live", "session_id": sid})
            ready = sock.receive_json()
            assert ready["t"] == "ready", ready

            sock.send_json({"t": "end"})
            seen = []
            while True:
                message = sock.receive_json()
                if message["t"] == "ping":
                    continue
                seen.append(message)
                if message["t"] == "ended":
                    break

        kinds = [m["t"] for m in seen]
        assert "utterance" in kinds, f"마지막 발화가 아예 안 왔습니다: {kinds}"
        assert kinds.index("utterance") < kinds.index("ended"), (
            f"종료가 마지막 발화보다 먼저 왔습니다: {kinds}"
        )
        assert next(m for m in seen if m["t"] == "utterance")["text"] == LAST_WORDS

        # 영구 이벤트도 같은 순서여야 한다. 리포트를 다시 열었을 때 내용이 달라지지
        # 않는다는 것이 승인 조건이다
        stored = [e["kind"] for e in app.state.runtime.event_store.of_session(sid)]
        assert stored[-1] == "session_ended", f"종료 뒤에 이벤트가 붙었습니다: {stored}"
        assert "utterance" in stored[:-1], f"마지막 발화가 저장되지 않았습니다: {stored}"


def test_draining_finishes_the_refinements_already_queued():
    """예약된 L3 보정을 cancel 하면 마지막 발화의 보정 판정이 아예 생기지 않는다.

    `Refiner.aclose()` 는 연결이 끊긴 자리를 위한 것이라 큐를 버린다. 사람이 종료를
    누른 자리는 다르다. 남은 것을 마저 돌려야 리포트가 완성된다.
    """
    done: list[str] = []

    class _Pipeline:
        async def refine(self, session, utterance, publish) -> None:
            await asyncio.sleep(0.01)
            done.append(utterance)

    async def _publish(message: dict) -> None:
        pass

    async def _on_error(problem: Exception) -> None:
        raise AssertionError(problem)

    async def run():
        refiner = Refiner(None, _Pipeline(), _publish, _on_error)
        refiner.schedule("첫 발화")
        refiner.schedule("마지막 발화")
        await refiner.drain(timeout_s=5.0)
        return list(done)

    assert asyncio.run(run()) == ["첫 발화", "마지막 발화"]


def test_draining_gives_up_at_the_budget_instead_of_hanging_the_end():
    """공급자가 늦어도 종료는 끝나야 한다. 끝나지 않는 종료가 늦은 이벤트보다 나쁘다."""

    class _StuckPipeline:
        async def refine(self, session, utterance, publish) -> None:
            await asyncio.sleep(30)

    async def _publish(message: dict) -> None:
        pass

    async def _on_error(problem: Exception) -> None:
        pass

    async def run():
        refiner = Refiner(None, _StuckPipeline(), _publish, _on_error)
        refiner.schedule("끝나지 않는 발화")
        loop = asyncio.get_running_loop()
        started = loop.time()
        await refiner.drain(timeout_s=0.05)
        waited = loop.time() - started
        await refiner.aclose()
        return waited

    assert asyncio.run(run()) < 5.0


LATE_WORDS = "상한을 넘겨 도착한 전사입니다."


class _SlowStream:
    """상한보다 늦게 마지막 전사를 내주는 스트림. 공급자가 늦는 자리다."""

    def __init__(self, on_transcript, delay_s: float) -> None:
        self.on_transcript = on_transcript
        self.delay_s = delay_s

    async def send(self, pcm: bytes) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def aclose(self) -> None:
        await asyncio.sleep(self.delay_s)
        await self.on_transcript(Transcript(text=LATE_WORDS, final=True))


class _SlowAdapter:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    async def open(self, on_transcript, keyterms=(), *, diarization=None):
        return _SlowStream(on_transcript, self.delay_s)


def test_a_slow_provider_neither_hangs_the_end_nor_changes_the_report():
    """상한을 넘기면 종료는 그대로 끝나고, 늦게 온 전사는 리포트를 못 바꾼다.

    끝나지 않는 종료가 늦은 이벤트보다 나쁘다. 그렇다고 늦은 이벤트를 그냥 붙이면
    종료 직후 조회한 리포트와 나중에 다시 연 리포트가 달라진다. 둘 다 막는다.
    """
    sid = "END-BUDGET-TEST-1"
    with _client(finish_budget_s=0.2) as client:
        app = client.app
        app.state.runtime = replace(app.state.runtime, stt=_SlowAdapter(1.0))
        with client.websocket_connect("/ws") as sock:
            sock.send_json({"t": "hello", "mode": "live", "session_id": sid})
            assert sock.receive_json()["t"] == "ready"
            started = time.monotonic()
            sock.send_json({"t": "end"})
            message = sock.receive_json()
            while message["t"] == "ping":
                message = sock.receive_json()
            waited = time.monotonic() - started
        assert message["t"] == "ended"
        assert waited < 0.8, f"상한 0.2초인데 {waited:.2f}초를 기다렸습니다"

        # 배경에 남은 마무리가 끝날 시간을 준다. 끝나도 붙지 않아야 한다
        time.sleep(1.3)
        stored = app.state.runtime.event_store.of_session(sid)
        kinds = [e["kind"] for e in stored]
        assert kinds[-1] == "session_ended", f"종료 뒤에 이벤트가 붙었습니다: {kinds}"
        assert not [e for e in stored if LATE_WORDS in str(e)]


def test_ending_an_already_ended_session_does_not_write_a_second_end():
    """끝난 상담을 되살려 다시 종료해도 종료 이벤트는 하나다.

    둘이 되면 리포트의 요약이 어느 쪽인지 갈리고, 이벤트 순서로 종료를 찾는 쪽이
    나중 것을 집는다.
    """
    sid = "END-TWICE-TEST-1"
    with _client() as client:
        app = client.app
        for _ in range(2):
            with client.websocket_connect("/ws") as sock:
                sock.send_json({"t": "hello", "mode": "text", "session_id": sid})
                assert sock.receive_json()["t"] == "ready"
                sock.send_json({"t": "end"})
                message = sock.receive_json()
                while message["t"] == "ping":
                    message = sock.receive_json()
                assert message["t"] == "ended"
        kinds = [e["kind"] for e in app.state.runtime.event_store.of_session(sid)]
    assert kinds.count("session_ended") == 1, f"종료 이벤트가 둘입니다: {kinds}"


def test_a_closed_session_refuses_every_kind_of_event():
    """가드는 저장 지점 하나가 아니라 봉투를 만드는 자리에 있다. 종류를 안 가린다."""
    from server.services.session.pipeline import SessionClosed

    with _client() as client:
        runtime = client.app.state.runtime
        session = runtime.registry.open("DEP-2026.08-v6", "text", "general", "CLOSED-GUARD-1")
        session.ended = True
        pipeline = Pipeline(runtime.engine, runtime.event_store, runtime.projection)
        for kind in ("utterance", "verdict", "alert", "assist", "session_started"):
            try:
                pipeline._wrap(session, kind, {})
            except SessionClosed:
                continue
            raise AssertionError(f"{kind} 가 닫힌 상담에 들어갔습니다")
        assert session.next_seq == 0, "막힌 이벤트가 seq 를 써 버렸습니다"
