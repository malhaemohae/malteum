"""OpenAI 규격 발화 단위 전사 어댑터. 온프레미스 Qwen3-ASR(vLLM) 경로다.

Deepgram 은 오디오를 계속 밀어 넣으면 전사를 이어서 준다. Qwen3-ASR 은 그렇지 않다 —
공식 문서가 스트리밍 상태를 "발화 하나" 단위로 규정했고, 실측에서도 147초 파일을
자르지 않고 연속으로 넣으면 CER 이 31 %까지 무너졌다(CTX-004 4절). 그래서 **어디서
끊을지를 화자 분리 구간이 정하고**, 끊긴 구간 하나를 WAV 로 싸서 파일 전사 엔드포인트
(`POST {base_url}/v1/audio/transcriptions`)에 한 번 보낸다.

    구간이 닫히는 조건   화자가 바뀌거나, `end_ms` 뒤 무음이 SEGMENT_GAP_MS 이상

발화 안의 중간 결과는 내지 않는다(DEC-5). 청크를 줄이면 되돌림이 급증하는데다
(2초 청크에서도 발화당 13 %) 이 어댑터는 발화가 끝난 뒤에야 보내므로 낼 것이 없다.
최종 확정만 `final=True` 로 나가고, 화면의 "듣고 있음" 표시는 화자 분리 쪽이 맡는다.

HTTP 왕복이 오디오 경로를 붙잡지 않게 태스크 하나가 큐를 앞에서부터 비운다 — 발화가
뒤바뀌면 리포트의 시간 순서가 무너진다.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from collections.abc import Sequence

from server.services.stt.base import OnTranscript, Transcript
from server.services.stt.diarization import DiarizationSource, SpeakerSegment

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
BYTES_PER_MS = SAMPLE_RATE * BYTES_PER_SAMPLE // 1000
# 구간이 끝난 뒤 이만큼 새 구간이 없으면 발화가 닫힌 것으로 본다. 대본이 화자가 바뀌는
# 자리마다 무음을 1초 이상 두므로(SCRIPT.md `audio.min_gap_ms`) 그 절반쯤에서 끊으면
# 다음 발화를 기다리지 않고 보낼 수 있다
SEGMENT_GAP_MS = 600
# 이보다 짧은 구간은 보내지 않는다. Sortformer 가 기침·맞장구에 남기는 조각이라
# 전사해도 문장이 안 되고 왕복만 늘어난다
MIN_SEGMENT_MS = 300


class SegmentedFileSttAdapter:
    """화자 분리 구간마다 WAV 하나를 OpenAI 규격 전사 엔드포인트에 보낸다."""

    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        api_key: str | None = None,
        language: str = "ko",
        segment_gap_ms: int = SEGMENT_GAP_MS,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.language = language
        self.segment_gap_ms = segment_gap_ms
        self.timeout_s = timeout_s

    @property
    def url(self) -> str:
        return f"{self.base_url}/v1/audio/transcriptions"

    async def open(
        self,
        on_transcript: OnTranscript,
        keyterms: Sequence[str] = (),
        *,
        diarization: DiarizationSource | None = None,
    ) -> SegmentedFileSttStream:
        if diarization is None:
            # 어디서 끊을지를 모르면 발화를 만들 수 없다. 여는 데 실패해야 ws 가
            # stt_unavailable 로 바꾸고 프런트가 text 모드를 제안한다(3층 폴백)
            raise RuntimeError(
                "발화 단위 전사 어댑터는 화자 분리 공급원이 있어야 합니다 "
                "(APP_DIARIZATION_URL 을 설정하십시오)."
            )
        import httpx

        client = httpx.AsyncClient(timeout=self.timeout_s)
        return SegmentedFileSttStream(self, client, on_transcript, diarization, keyterms)


class SegmentedFileSttStream:
    """상담 하나. PCM 을 쌓아 두고 닫힌 구간만 잘라 보낸다."""

    def __init__(
        self,
        adapter: SegmentedFileSttAdapter,
        client,
        on_transcript: OnTranscript,
        diarization: DiarizationSource,
        keyterms: Sequence[str] = (),
    ) -> None:
        self.adapter = adapter
        self.client = client
        self.on_transcript = on_transcript
        self.diarization = diarization
        # 팩의 jargon_terms 를 prompt 로 넘긴다. Qwen3-ASR 은 keyterm 파라미터가 없고
        # OpenAI 규격의 prompt 가 그 자리다 — 없으면 `만기후이자율` 이 갈라진다
        self.prompt = " ".join(keyterms)
        self._pcm = bytearray()
        self._closed_ms = 0  # 여기까지는 이미 보냈다
        self._queue: asyncio.Queue[SpeakerSegment | None] = asyncio.Queue()
        self._worker = asyncio.create_task(self._transcribe_queued())

    async def send(self, pcm: bytes) -> None:
        self._pcm += pcm
        self._enqueue_closed(self.received_ms)

    @property
    def received_ms(self) -> int:
        return len(self._pcm) // BYTES_PER_MS

    async def aclose(self) -> None:
        # 마지막 구간은 뒤에 무음이 오지 않아 스스로 닫히지 않는다. 여기서 닫아야
        # 마지막 발화가 사라지지 않는다
        self._enqueue_closed(self.received_ms, final=True)
        await self._queue.put(None)
        await self._worker
        await self.client.aclose()

    def _enqueue_closed(self, now_ms: int, *, final: bool = False) -> None:
        """닫힌 구간을 큐에 넣는다. 같은 화자가 이어 말한 구간은 하나로 합친다."""
        for run in _runs(self.diarization.segments(), self.adapter.segment_gap_ms):
            if run.start_ms < self._closed_ms or run.end_ms - run.start_ms < MIN_SEGMENT_MS:
                continue
            closed = final or now_ms - run.end_ms >= self.adapter.segment_gap_ms
            if not closed:
                # 시간 순서로 보고 있으므로 여기서 멈춘다. 뒤 구간이 먼저 닫혀도
                # 앞 구간을 앞지르면 리포트의 순서가 뒤집힌다
                break
            if run.end_ms > now_ms:
                break  # 아직 그 오디오를 다 받지 못했다
            self._closed_ms = run.end_ms
            self._queue.put_nowait(run)

    async def _transcribe_queued(self) -> None:
        while (run := await self._queue.get()) is not None:
            try:
                text = await self._transcribe(run)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  전사 하나가 상담을 끊지 않게 한다
                log.warning(
                    "발화 전사 실패 (%d~%d ms): %s: %s",
                    run.start_ms,
                    run.end_ms,
                    type(e).__name__,
                    e,
                )
                continue
            if not text:
                continue
            await self.on_transcript(
                Transcript(
                    text=text,
                    final=True,
                    start_ms=run.start_ms,
                    duration_ms=run.end_ms - run.start_ms,
                    speaker_id=run.speaker_id,
                )
            )

    async def _transcribe(self, run: SpeakerSegment) -> str:
        wav = _wav(self._pcm[run.start_ms * BYTES_PER_MS : run.end_ms * BYTES_PER_MS])
        data = {"model": self.adapter.model, "language": self.adapter.language}
        if self.prompt:
            data["prompt"] = self.prompt
        headers = (
            {"Authorization": f"Bearer {self.adapter.api_key}"} if self.adapter.api_key else {}
        )
        response = await self.client.post(
            self.adapter.url,
            files={"file": (f"{run.start_ms}.wav", wav, "audio/wav")},
            data=data,
            headers=headers,
        )
        response.raise_for_status()
        return spoken(str(response.json().get("text", "")))


def spoken(text: str) -> str:
    """모델이 붙인 제어 표지를 벗긴다.

    `qwen-asr-serve` 는 디코딩 결과를 그대로 실어 주므로 `text` 가
    `language Korean<asr_text>네, 중도 해지 기준으로…` 꼴로 온다(실측 2026-09-04).
    이대로 저장하면 L1 정확 일치가 첫 어절부터 어긋나고 리포트에도 그 문자열이 남는다.
    """
    _, marker, rest = text.rpartition("<asr_text>")
    return (rest if marker else text).strip()


def _runs(segments: Sequence[SpeakerSegment], gap_ms: int) -> list[SpeakerSegment]:
    """같은 화자가 이어 말한 구간을 하나로 합친다. 시간 순서로 돌려준다.

    Sortformer 는 숨 쉬는 자리마다 구간을 끊으므로, 그대로 보내면 한 문장이 대여섯
    조각으로 갈라져 전사가 문장이 되지 못한다. 화자가 바뀌거나 무음이 `gap_ms` 이상
    이어지는 자리에서만 끊는다 — 닫히는 조건과 같은 값이라야, 합쳐 놓고 곧바로 닫는
    구간과 따로 두고 기다리는 구간이 갈리지 않는다.
    """
    runs: list[SpeakerSegment] = []
    for s in sorted(segments, key=lambda s: (s.start_ms, s.end_ms)):
        last = runs[-1] if runs else None
        if (
            last is not None
            and last.speaker_id == s.speaker_id
            and s.start_ms - last.end_ms < gap_ms
        ):
            runs[-1] = SpeakerSegment(last.start_ms, max(last.end_ms, s.end_ms), last.speaker_id)
        else:
            runs.append(s)
    return runs


def _wav(pcm: bytes) -> bytes:
    """16kHz mono PCM16 을 WAV 로 싼다. multipart 로 보낼 것이라 헤더가 필요하다."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(BYTES_PER_SAMPLE)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm)
    return buffer.getvalue()
