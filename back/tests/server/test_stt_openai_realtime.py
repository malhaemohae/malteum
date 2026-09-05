"""OpenAI Realtime 전사 어댑터 (`services/stt/openai_realtime.py`).

이 규격은 화자를 안 준다. 화자는 Sortformer 사이드카가 구간으로 주고 `speaker.py` 가
**발화 구간과 화자 구간의 겹침**으로 번호를 고른다. 그래서 이 어댑터가 지켜야 할 것은
전사 문장 자체보다 **시각을 정확히 채우는 것**이다 — 밀리면 옆 화자의 구간에 붙고,
그러면 위험 신호가 은행원 발화로 기록되어 경보가 사라진다. 화면에는 아무 오류도 안 뜬다.

시각의 유일한 출처가 서버 VAD 의 `speech_started`·`speech_stopped` 라, 그 둘을 전사와
`item_id` 로 맞붙이는 자리를 여기서 잠근다.
"""

import base64
import json

import pytest

from server.services.stt.openai_realtime import (
    COMPLETED,
    DELTA,
    FAILED,
    MODEL,
    SPEECH_STARTED,
    SPEECH_STOPPED,
    OpenAiRealtimeAdapter,
    OpenAiRealtimeStream,
)


class FakeWs:
    def __init__(self, incoming=()):
        self.sent: list[str] = []
        self._incoming = list(incoming)
        self.closed = False

    async def send(self, body):
        self.sent.append(body)

    async def recv(self):
        if self._incoming:
            return json.dumps(self._incoming.pop(0))
        raise ConnectionResetError  # 더 올 것이 없다. _read 가 조용히 끝난다

    async def close(self):
        self.closed = True

    def messages(self, kind: str) -> list[dict]:
        return [m for b in self.sent if (m := json.loads(b)).get("type") == kind]


def collector():
    got = []

    async def on_transcript(t):
        got.append(t)

    return got, on_transcript


async def _run(events):
    got, on_transcript = collector()
    ws = FakeWs(events)
    await OpenAiRealtimeStream(ws, on_transcript).reader
    return got, ws


def _speech(item: str, start: int, end: int) -> list[dict]:
    return [
        {"type": SPEECH_STARTED, "item_id": item, "audio_start_ms": start},
        {"type": SPEECH_STOPPED, "item_id": item, "audio_end_ms": end},
    ]


# --- 세션 설정 -------------------------------------------------------------


def test_the_session_matches_the_transcription_spec():
    session = OpenAiRealtimeAdapter()._session(())["session"]
    assert session["type"] == "transcription"
    audio = session["audio"]["input"]
    assert audio["transcription"]["model"] == MODEL
    # 규격이 단수 `language` 가 아니라 복수를 받는다. 단수로 보내면 무시된다
    assert audio["transcription"]["languages"] == ["ko"]


def test_server_vad_is_on_because_it_is_the_only_source_of_timing():
    """끄면 전사는 와도 `speech_started` 가 안 온다 — 화자 접착에 쓸 시각이 사라진다."""
    vad = OpenAiRealtimeAdapter()._session(())["session"]["audio"]["input"]["turn_detection"]
    assert vad["type"] == "server_vad"


def test_pack_terms_ride_in_the_prompt():
    """`base.py`: 없으면 `만기후이자율` 이 `만기 후 이자율` 로 갈라져 L1 정확 일치가 깨진다."""
    prompt = OpenAiRealtimeAdapter()._session(["만기후이자율", "중도해지이율"])["session"]["audio"][
        "input"
    ]["transcription"]["prompt"]
    assert "만기후이자율" in prompt and "중도해지이율" in prompt


def test_the_prompt_survives_a_pack_with_no_terms():
    prompt = OpenAiRealtimeAdapter()._session(())["session"]["audio"]["input"]["transcription"][
        "prompt"
    ]
    assert prompt and "상담" in prompt


# --- 시각 (화자 접착의 전제) ------------------------------------------------


@pytest.mark.anyio
async def test_vad_offsets_land_on_the_transcript():
    """`speaker.py` 가 이 값으로 화자 구간과의 겹침을 잰다."""
    got, _ = await _run(
        [
            *_speech("a", 17000, 29000),
            {"type": COMPLETED, "item_id": "a", "transcript": "우대이자율은 적용이 안 됩니다."},
        ]
    )
    (final,) = [t for t in got if t.final]
    assert final.start_ms == 17000
    assert final.duration_ms == 12000


@pytest.mark.anyio
async def test_each_utterance_keeps_its_own_span():
    """항목이 겹쳐 와도 `item_id` 로 갈린다. 섞이면 발화가 남의 구간에 붙는다."""
    got, _ = await _run(
        [
            {"type": SPEECH_STARTED, "item_id": "a", "audio_start_ms": 1000},
            {"type": SPEECH_STARTED, "item_id": "b", "audio_start_ms": 5000},
            {"type": SPEECH_STOPPED, "item_id": "b", "audio_end_ms": 7000},
            {"type": SPEECH_STOPPED, "item_id": "a", "audio_end_ms": 3000},
            {"type": COMPLETED, "item_id": "b", "transcript": "두 번째."},
            {"type": COMPLETED, "item_id": "a", "transcript": "첫 번째."},
        ]
    )
    spans = {t.text: (t.start_ms, t.duration_ms) for t in got if t.final}
    assert spans["두 번째."] == (5000, 2000)
    assert spans["첫 번째."] == (1000, 2000)


@pytest.mark.anyio
async def test_a_transcript_with_no_vad_leaves_timing_empty():
    """지어내면 화자 접착이 엉뚱한 구간에 붙는다. 비우면 `session.py` 가 세션 시계로 메운다."""
    got, _ = await _run([{"type": COMPLETED, "item_id": "z", "transcript": "시각 없는 말."}])
    (final,) = got
    assert final.start_ms is None and final.duration_ms is None


@pytest.mark.anyio
async def test_a_missing_stop_still_gives_the_start():
    """시작만 알아도 화자 구간과 맞댈 수 있다. 길이는 모르면 비운다."""
    got, _ = await _run(
        [
            {"type": SPEECH_STARTED, "item_id": "a", "audio_start_ms": 4000},
            {"type": COMPLETED, "item_id": "a", "transcript": "끝을 못 받은 말."},
        ]
    )
    (final,) = got
    assert final.start_ms == 4000 and final.duration_ms is None


# --- 전사 -----------------------------------------------------------------


@pytest.mark.anyio
async def test_deltas_are_partial_and_accumulate():
    """조각으로 오므로 이어 붙여야 화면이 지금까지의 말을 보여준다. 저장은 안 된다(계약)."""
    got, _ = await _run(
        [
            {"type": DELTA, "item_id": "a", "delta": "우대"},
            {"type": DELTA, "item_id": "a", "delta": "이자율은"},
        ]
    )
    assert [t.text for t in got] == ["우대", "우대이자율은"]
    assert not any(t.final for t in got)


@pytest.mark.anyio
async def test_the_adapter_never_invents_a_speaker():
    """이 규격에는 화자가 없다. 채우면 사이드카가 정한 번호를 덮어쓴다."""
    got, _ = await _run(
        [*_speech("a", 0, 1000), {"type": COMPLETED, "item_id": "a", "transcript": "네."}]
    )
    assert got[-1].speaker_id is None


@pytest.mark.anyio
async def test_an_empty_transcript_is_not_stored():
    """빈 확정 전사를 발화로 만들면 리포트 타임라인에 빈 줄이 남는다."""
    got, _ = await _run([{"type": COMPLETED, "item_id": "a", "transcript": "   "}])
    assert got == []


@pytest.mark.anyio
async def test_a_failed_chunk_does_not_end_the_consultation():
    got, _ = await _run(
        [
            {"type": DELTA, "item_id": "a", "delta": "버려질 말"},
            {"type": FAILED, "item_id": "a", "error": "oops"},
            *_speech("b", 100, 900),
            {"type": COMPLETED, "item_id": "b", "transcript": "다음 발화입니다."},
        ]
    )
    assert [t.text for t in got if t.final] == ["다음 발화입니다."]


# --- 오디오·종료 -----------------------------------------------------------


@pytest.mark.anyio
async def test_audio_goes_out_as_base64_pcm_untouched():
    """표본율을 선언해 보내므로 리샘플하지 않는다. 건드리면 VAD 오프셋과 어긋난다."""
    ws = FakeWs()
    stream = OpenAiRealtimeStream(ws, collector()[1])
    stream.reader.cancel()
    pcm = b"\x01\x02" * 1600
    await stream.send(pcm)
    (appended,) = ws.messages("input_audio_buffer.append")
    assert base64.b64decode(appended["audio"]) == pcm


@pytest.mark.anyio
async def test_close_commits_so_the_last_utterance_is_not_lost():
    """그냥 끊으면 마지막 발화가 사라지고, 그것이 리포트의 마지막 항목일 수 있다."""
    ws = FakeWs([{"type": COMPLETED, "item_id": "a", "transcript": "마지막입니다."}])
    stream = OpenAiRealtimeStream(ws, collector()[1])
    await stream.aclose()
    assert ws.messages("input_audio_buffer.commit")
    assert ws.closed
