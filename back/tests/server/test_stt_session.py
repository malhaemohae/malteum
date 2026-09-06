"""상담 하나의 STT 배선 (`services/stt/session.py`).

여기서 보는 것은 **오디오가 멈춘 자리**다. 프론트의 녹음 중지는 오디오 프레임을 멈출
뿐이고, WS 계약의 c2s 에는 flush·pause 가 없어(`contracts/ws_protocol.schema.json`)
클라이언트가 멈췄다고 알릴 수단이 없다. 그래서 서버가 오디오가 끊긴 것을 스스로 보고
마지막 구간을 닫는다. 안 닫으면 발화 단위 어댑터는 뒤에 올 무음을 영영 기다린다.
"""

from __future__ import annotations

import asyncio

from server.services.stt.session import SttSession

FRAME = b"\x00" * 3_200  # 계약 audioFrame 의 100ms


class _Session:
    """`SttSession` 이 쓰는 것은 세션 시계뿐이다."""

    def elapsed_ms(self) -> int:
        return 0


class _FakeStream:
    def __init__(self) -> None:
        self.fed = 0
        self.flushes = 0
        self.closed = False

    async def send(self, pcm: bytes) -> None:
        self.fed += len(pcm)

    async def flush(self) -> None:
        self.flushes += 1

    async def aclose(self) -> None:
        self.closed = True


class _FakeAdapter:
    def __init__(self, stream: _FakeStream) -> None:
        self.stream = stream

    async def open(self, on_transcript, keyterms=(), *, diarization=None) -> _FakeStream:
        return self.stream


async def _publish(message: dict) -> None:
    pass


async def _submit(utterance) -> None:
    pass


def test_audio_that_stops_closes_the_last_segment_without_closing_the_stream():
    """녹음 중지. 상담은 이어지므로 스트림을 닫으면 안 되고, 구간은 닫아야 한다."""

    async def run():
        stream = _FakeStream()
        stt = SttSession(_Session(), _publish, _submit, hold_ms=0, idle_flush_ms=50)
        await stt.start(_FakeAdapter(stream))
        await stt.feed(FRAME)
        await asyncio.sleep(0.2)
        after_idle = stream.flushes
        closed_early = stream.closed
        # 잠잠한 동안 같은 자리를 되풀이해 닫으면 빈 왕복만 쌓인다
        await asyncio.sleep(0.2)
        repeated = stream.flushes
        # 녹음을 다시 켠다. 그 뒤 또 멈추면 다시 닫아야 한다
        await stt.feed(FRAME)
        await asyncio.sleep(0.2)
        after_resume = stream.flushes
        await stt.aclose()
        return after_idle, closed_early, repeated, after_resume, stream.closed

    after_idle, closed_early, repeated, after_resume, closed = asyncio.run(run())
    assert after_idle == 1, "오디오가 멈췄는데 마지막 구간을 닫지 않았습니다"
    assert not closed_early, "구간만 닫아야 한다. 스트림을 닫으면 다시 켤 수 없다"
    assert repeated == 1, "오디오가 없는 동안 되풀이해 닫으면 빈 왕복만 쌓인다"
    assert after_resume == 2, "다시 켰다 멈춘 자리도 닫아야 한다"
    assert closed, "상담이 끝나면 스트림도 닫는다"


def test_the_idle_watch_stops_with_the_session():
    """상담이 끝난 뒤에도 감시가 돌면 닫힌 스트림을 계속 두드린다."""

    async def run():
        stream = _FakeStream()
        stt = SttSession(_Session(), _publish, _submit, hold_ms=0, idle_flush_ms=50)
        await stt.start(_FakeAdapter(stream))
        await stt.feed(FRAME)
        await stt.aclose()
        after_close = stream.flushes
        await asyncio.sleep(0.2)
        return after_close, stream.flushes

    after_close, later = asyncio.run(run())
    assert later == after_close, "닫은 뒤에도 유휴 감시가 스트림을 두드렸습니다"


class _FakeDiarization:
    """사이드카 클라이언트와 모양만 같은 가짜. 받은 오디오를 적어 둔다."""

    def __init__(self) -> None:
        self.fed = bytearray()

    async def feed(self, pcm: bytes) -> None:
        self.fed += pcm

    def segments(self):
        return ()


def test_the_seam_gets_silence_so_diarization_can_tell_the_two_apart():
    """중지 전후 목소리가 맞붙어 들리면 화자 번호가 뒤섞인다. 이음매에 무음을 끼운다.

    구간을 닫는 것은 전사 쪽만 가른다. 사이드카는 우리가 준 오디오만 보므로, 몇 분을
    쉬어도 그 자리에 아무 표시가 없으면 두 목소리를 이어진 말로 듣는다.
    """

    async def run():
        stream, diarization = _FakeStream(), _FakeDiarization()
        stt = SttSession(
            _Session(),
            _publish,
            _submit,
            diarization=diarization,
            hold_ms=0,
            idle_flush_ms=50,
            seam_silence_ms=1_000,
        )
        await stt.start(_FakeAdapter(stream))
        await stt.feed(FRAME)
        spoken = (stream.fed, len(diarization.fed))
        await asyncio.sleep(0.2)
        padded = (stream.fed, len(diarization.fed))
        first_round = stream.flushes
        # 우리가 만든 무음이 유휴 감시를 다시 깨우면 닫기와 무음이 끝없이 되풀이된다
        await asyncio.sleep(0.2)
        repeated = stream.flushes
        await stt.aclose()
        return spoken, padded, first_round, repeated

    spoken, padded, first_round, repeated = asyncio.run(run())
    silence = 1_000 * 32  # 1초 × 16kHz mono PCM16
    assert padded[0] - spoken[0] == silence, "전사 어댑터 쪽 이음매에 무음이 없습니다"
    assert padded[1] - spoken[1] == silence, "화자 분리 쪽 이음매에 무음이 없습니다"
    assert first_round == 1
    assert repeated == 1, "끼운 무음이 유휴 감시를 다시 깨웠습니다"
