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
CHUNK_MS = 960  # 사이드카의 청크 하나 (DEC-6). 구간은 이 단위로 뒤늦게 자란다


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


class _LaggingDiarization:
    """뒤늦게 구간을 내주는 가짜 공급원. 실물 사이드카 클라이언트와 모양이 같다.

    `SortformerDiarization` 처럼 목록을 통째로 갈아 끼우고, 그 목록이 **어디까지의
    오디오를 보고** 나온 값인지를 `covered_ms` 로 알려 준다. 완성된 목록을 처음부터
    주는 `ScriptedDiarization` 으로는 이 어긋남이 드러나지 않는다.
    """

    def __init__(self) -> None:
        self._segments: tuple[SpeakerSegment, ...] = ()
        self.covered_ms = 0

    def saw(self, covered_ms: int, spans) -> None:
        self.covered_ms = covered_ms
        self._segments = tuple(SpeakerSegment(*span) for span in spans)

    def segments(self):
        return self._segments


def _stream(client, segments, *, keyterms=(), gap_ms=600):
    adapter = SegmentedFileSttAdapter(
        "http://asr.test/", model="Qwen/Qwen3-ASR-1.7B", segment_gap_ms=gap_ms
    )
    got: list = []

    async def on_transcript(t):
        got.append(t)

    source = segments if hasattr(segments, "segments") else ScriptedDiarization(segments)
    return (
        adapter,
        got,
        SegmentedFileSttStream(adapter, client, on_transcript, source, keyterms),
    )


async def _feed(stream, ms: int) -> None:
    """무음을 100ms 씩 민다. 실제 오디오 프레임과 같은 단위다."""
    for _ in range(ms // 100):
        await stream.send(SILENCE * (100 * BYTES_PER_MS // 2))
        await asyncio.sleep(0)


async def _feed_lagging(stream, source: _LaggingDiarization, truth, ms: int) -> None:
    """오디오를 밀면서, 청크가 찰 때마다 구간이 그만큼씩 자라게 한다.

    `SttSession.feed()` 와 같은 순서다 — 화자 분리에 먼저 주고 어댑터에 준다.
    """
    for _ in range(ms // 100):
        covered = (stream.received_ms + 100) // CHUNK_MS * CHUNK_MS
        source.saw(covered, [(s, min(e, covered), sid) for s, e, sid in truth if s < covered])
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


def test_a_long_utterance_is_not_cut_short_by_the_lag_of_the_diarization_chunks():
    """긴 발화 하나가 전사 하나로 나간다. 뒷부분이 사라지지 않는다.

    사이드카는 0.96초 청크가 찬 뒤에야 구간을 늘려 주므로, 받은 PCM 길이로 무음을 재면
    화자가 말하는 중인데도 "구간이 끝나고 600ms 지났다" 로 보인다. 그러면 앞 조각만
    전사되고, 이어서 늘어난 같은 구간은 시작이 이미 보낸 자리보다 앞서 통째로 버려진다.
    """
    client = _StubClient()

    async def run():
        source = _LaggingDiarization()
        _, got, stream = _stream(client, source)
        await _feed_lagging(stream, source, [(0, 3_500, "speaker_0")], 6_000)
        await stream.aclose()
        return got

    got = asyncio.run(run())
    assert [(t.start_ms, t.duration_ms, t.speaker_id) for t in got] == [(0, 3_500, "speaker_0")]


def test_a_segment_that_grows_after_it_was_sent_gives_up_only_the_part_already_sent():
    """이미 보낸 앞부분만 잘라 내고 남은 뒤쪽은 보낸다. 통째로 버리면 뒷부분이 사라진다.

    Sortformer 는 뒤 오디오를 보고 앞 구간을 고쳐 잡는다. 늘어난 구간의 시작은 이미
    보낸 자리보다 앞서므로, 이 경우를 버림으로 처리하면 늘어난 만큼이 전사되지 않는다.
    """
    client = _StubClient()

    async def run():
        source = _LaggingDiarization()
        _, got, stream = _stream(client, source)
        source.saw(1_600, [(0, 1_000, "speaker_0")])
        await _feed(stream, 1_600)
        first = list(got)
        source.saw(3_400, [(0, 2_600, "speaker_0")])  # 같은 구간을 뒤로 늘려 잡았다
        await _feed(stream, 1_800)
        await stream.aclose()
        return first, got

    first, got = asyncio.run(run())
    assert [(t.start_ms, t.duration_ms) for t in first] == [(0, 1_000)]
    assert [(t.start_ms, t.duration_ms) for t in got] == [(0, 1_000), (1_000, 1_600)]


def test_the_last_segment_goes_out_even_though_no_silence_follows_it():
    """상담이 끝나면 뒤에 무음이 오지 않는다. 여기서 안 닫으면 마지막 발화가 사라진다."""
    client = _StubClient()

    async def run():
        _, got, stream = _stream(client, [SpeakerSegment(0, 1_000, "speaker_0")])
        await _feed(stream, 1_000)  # 무음이 하나도 없다
        await stream.aclose()
        return got

    assert len(asyncio.run(run())) == 1
