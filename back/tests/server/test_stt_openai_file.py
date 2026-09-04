"""발화 단위 전사 어댑터 (`services/stt/openai_file.py`).

Qwen3-ASR 은 자르지 않고 연속으로 넣으면 무너지므로(CTX-004: 147초 파일 CER 31 %)
**어디서 끊을지**가 이 어댑터의 전부다. 그 판단이 틀리면 발화가 반 토막 나거나 두
사람의 말이 한 발화로 붙어, 게이트가 판정 축을 잘못 고른다.

실물 엔드포인트는 부르지 않는다(`test_no_live_adapters.py`). 실물 확인은 vLLM 컨테이너로
따로 했고, 그 확인이 잡아낸 것이 `spoken()` 이 벗기는 제어 표지다.
"""

from __future__ import annotations

import asyncio

from server.services.stt.diarization import ScriptedDiarization, SpeakerSegment
from server.services.stt.openai_file import (
    BYTES_PER_MS,
    SegmentedFileSttAdapter,
    SegmentedFileSttStream,
    spoken,
)

SILENCE = b"\x00\x00"


class _Response:
    def __init__(self, text: str) -> None:
        self._text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"text": self._text}


class _StubClient:
    """보낸 것을 적어 두고 정해진 답을 돌려준다. 왕복 하나가 발화 하나다."""

    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, url, *, files, data, headers) -> _Response:
        self.posts.append({"url": url, "wav": files["file"][1], "data": data, "headers": headers})
        return _Response(f"language Korean<asr_text>{len(self.posts)}번째 발화입니다.")

    async def aclose(self) -> None:
        pass


def _stream(client, segments, *, keyterms=(), gap_ms=600):
    adapter = SegmentedFileSttAdapter(
        "http://asr.test/", model="Qwen/Qwen3-ASR-1.7B", segment_gap_ms=gap_ms
    )
    got: list = []

    async def on_transcript(t):
        got.append(t)

    return (
        adapter,
        got,
        SegmentedFileSttStream(
            adapter, client, on_transcript, ScriptedDiarization(segments), keyterms
        ),
    )


async def _feed(stream, ms: int) -> None:
    """무음을 100ms 씩 민다. 실제 오디오 프레임과 같은 단위다."""
    for _ in range(ms // 100):
        await stream.send(SILENCE * (100 * BYTES_PER_MS // 2))
        await asyncio.sleep(0)


def test_a_segment_is_sent_only_after_the_silence_that_closes_it():
    """구간이 끝나자마자 보내면 아직 이어질 말을 잘라 버린다. 600ms 무음을 기다린다."""
    client = _StubClient()

    async def run():
        _, got, stream = _stream(client, [SpeakerSegment(0, 1_000, "speaker_0")])
        await _feed(stream, 1_400)  # 구간이 끝난 뒤 400ms 뿐이다
        await asyncio.sleep(0)
        early = list(got)
        await _feed(stream, 300)  # 이제 700ms
        await asyncio.sleep(0)
        await stream.aclose()
        return early, got

    early, got = asyncio.run(run())
    assert early == []
    assert len(got) == 1
    assert got[0].final and got[0].speaker_id == "speaker_0"
    assert (got[0].start_ms, got[0].duration_ms) == (0, 1_000)


def test_the_control_marker_the_model_prepends_never_reaches_the_utterance():
    """`language Korean<asr_text>…` 가 그대로 저장되면 L1 정확 일치가 첫 어절부터 어긋난다."""
    client = _StubClient()

    async def run():
        _, got, stream = _stream(client, [SpeakerSegment(0, 1_000, "speaker_0")])
        await _feed(stream, 2_000)
        await stream.aclose()
        return got

    got = asyncio.run(run())
    assert [t.text for t in got] == ["1번째 발화입니다."]
    assert spoken("아무 표지도 없는 문장.") == "아무 표지도 없는 문장."


def test_one_speakers_breaths_are_one_utterance_but_a_speaker_change_is_not():
    """숨 쉬는 자리마다 오는 구간을 그대로 보내면 한 문장이 대여섯 조각으로 갈라진다."""
    client = _StubClient()

    async def run():
        _, got, stream = _stream(
            client,
            [
                SpeakerSegment(0, 1_000, "speaker_0"),
                SpeakerSegment(1_200, 2_000, "speaker_0"),  # 200ms 쉬었을 뿐 같은 사람
                SpeakerSegment(2_100, 3_000, "speaker_1"),  # 화자가 바뀌면 끊는다
            ],
        )
        await _feed(stream, 4_000)
        await stream.aclose()
        return got

    got = asyncio.run(run())
    assert [(t.start_ms, t.duration_ms, t.speaker_id) for t in got] == [
        (0, 2_000, "speaker_0"),
        (2_100, 900, "speaker_1"),
    ]


def test_the_pack_terms_ride_along_as_the_prompt():
    """Qwen3-ASR 에는 keyterm 자리가 없다. OpenAI 규격의 prompt 가 그 자리다."""
    client = _StubClient()

    async def run():
        _, _, stream = _stream(
            client, [SpeakerSegment(0, 1_000, "speaker_0")], keyterms=("만기후이자율", "차감률")
        )
        await _feed(stream, 2_000)
        await stream.aclose()

    asyncio.run(run())
    assert client.posts[0]["url"] == "http://asr.test/v1/audio/transcriptions"
    assert client.posts[0]["data"]["prompt"] == "만기후이자율 차감률"
    assert client.posts[0]["data"]["language"] == "ko"
    assert client.posts[0]["wav"][:4] == b"RIFF"


def test_the_last_segment_goes_out_even_though_no_silence_follows_it():
    """상담이 끝나면 뒤에 무음이 오지 않는다. 여기서 안 닫으면 마지막 발화가 사라진다."""
    client = _StubClient()

    async def run():
        _, got, stream = _stream(client, [SpeakerSegment(0, 1_000, "speaker_0")])
        await _feed(stream, 1_000)  # 무음이 하나도 없다
        await stream.aclose()
        return got

    assert len(asyncio.run(run())) == 1
