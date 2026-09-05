"""OpenAI Realtime WebSocket 전사 어댑터 (1차 MVP 합의, `services/stt/README.md`).

`openai_file.py` 와 같은 규격을 말하지만 방식이 반대다. 파일 어댑터는 화자 분리 구간이
정한 자리에서 끊어 한 덩이씩 보내고, 이쪽은 **오디오를 계속 밀어 넣고 서버 VAD 가
끊어 준다.** 그래서 화자 분리 공급원이 없어도 전사 자체는 돈다.

## 화자 접착의 전제: 시각을 채운다

이 규격은 화자 라벨을 주지 않는다. 화자는 Sortformer 사이드카가 구간으로 주고,
`speaker.py` 가 **발화 구간과 화자 구간의 겹침**으로 번호를 고른다. 그 겹침을 재려면
발화의 시각이 있어야 하는데, 전사 완료 이벤트에는 시각이 없다.

서버 VAD 가 그것을 준다 — `speech_started` 의 `audio_start_ms` 와 `speech_stopped` 의
`audio_end_ms` 는 **세션 오디오 시작을 0 으로 한 밀리초**라 사이드카 구간과 같은 시계다.
둘 다 `item_id` 를 실어 오므로 그 값으로 전사와 맞붙인다.

    speech_started  item_id=A  audio_start_ms=17000
    speech_stopped  item_id=A  audio_end_ms=29000
    transcription.completed  item_id=A  "우대이자율은 …"   → start 17000 · duration 12000

시각을 안 채우면 `session.py` 가 세션 시계로 메우는데, 확정 전사는 말이 끝난 뒤에 오므로
그 값은 시작이 아니라 끝에 가깝다. 그만큼 밀리면 **옆 화자의 구간에 붙는다.**

## 용어 힌트

팩의 `jargon_terms` 를 `prompt` 에 넣는다(`base.py` 가 이 인자를 여는 시점에 받는 이유).
끄면 `만기후이자율` 이 `만기 후 이자율` 로 갈라져 L1 정확 일치가 깨진다.

## 중간 전사

델타를 `final=False` 로 흘린다. 계약상 저장되지 않고 화면의 "듣고 있음" 에만 쓰인다 —
파일 어댑터가 낼 것이 없어 화자 분리 쪽에 맡긴 자리를, 이쪽은 직접 낼 수 있다.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Sequence
from contextlib import suppress

from server.services.stt.base import OnTranscript, Transcript
from server.services.stt.diarization import DiarizationSource

log = logging.getLogger(__name__)

ENDPOINT = "wss://api.openai.com/v1/realtime"
MODEL = "gpt-live-transcribe"
SAMPLE_RATE = 16_000  # `audio.py` 가 흘리는 규격. 시연 음원도 이 값으로 굳었다

SPEECH_STARTED = "input_audio_buffer.speech_started"
SPEECH_STOPPED = "input_audio_buffer.speech_stopped"
DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"
FAILED = "conversation.item.input_audio_transcription.failed"


class OpenAiRealtimeAdapter:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = MODEL,
        language: str = "ko",
        base_url: str = ENDPOINT,
        sample_rate: int = SAMPLE_RATE,
        vad_silence_ms: int = 500,
        prompt: str = "은행 창구의 예금·대출 상담. 상품 조건과 이자율을 설명하는 대화다.",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.language = language
        self.base_url = base_url
        self.sample_rate = sample_rate
        self.vad_silence_ms = vad_silence_ms
        self.prompt = prompt

    def _session(self, keyterms: Sequence[str]) -> dict:
        """`session.update` 본문. 규격의 transcription 세션 그대로다.

        `turn_detection` 을 켜야 `speech_started`·`speech_stopped` 가 온다 — 그 둘이
        화자 접착에 쓸 시각의 유일한 출처다. 끄면 전사는 와도 시각이 없다.
        """
        prompt = self.prompt
        if keyterms:
            # 규격의 힌트 자리는 자유 문장이다. 용어를 붙여 주면 그 표기로 받아 적는다
            prompt = f"{prompt} 다음 용어가 그대로 나온다: {', '.join(keyterms)}."
        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": self.sample_rate},
                        "transcription": {
                            "model": self.model,
                            "prompt": prompt,
                            # 규격이 단수 `language` 가 아니라 복수를 받는다
                            "languages": [self.language],
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "silence_duration_ms": self.vad_silence_ms,
                        },
                    }
                },
            },
        }

    async def open(
        self,
        on_transcript: OnTranscript,
        keyterms: Sequence[str] = (),
        *,
        diarization: DiarizationSource | None = None,
    ) -> OpenAiRealtimeStream:
        """스트림을 연다. `diarization` 은 쓰지 않는다 — 끊는 일을 서버 VAD 가 한다.

        화자는 `speaker.py` 가 사이드카 구간과 이 발화의 겹침으로 정하므로, 어댑터는
        시각만 정확히 채우고 `speaker_id` 는 비운다.
        """
        import websockets

        headers = {"OpenAI-Beta": "realtime=v1"}
        if self.api_key:  # 규격을 말하는 로컬 서버는 키가 없거나 더미다
            headers["Authorization"] = f"Bearer {self.api_key}"
        ws = await websockets.connect(
            f"{self.base_url}?intent=transcription",
            additional_headers=headers,
            open_timeout=15,
            max_size=None,
        )
        await ws.send(json.dumps(self._session(keyterms)))
        return OpenAiRealtimeStream(ws, on_transcript)


class OpenAiRealtimeStream:
    """상담 하나에 소켓 하나. 받는 쪽은 배경 태스크로 돈다."""

    def __init__(self, ws, on_transcript: OnTranscript) -> None:
        self.ws = ws
        self.on_transcript = on_transcript
        # item_id → [start_ms, end_ms]. VAD 가 먼저 오고 전사가 뒤에 온다
        self.spans: dict[str, list[int | None]] = {}
        # 중간 전사는 조각으로 온다. 항목마다 이어 붙여 지금까지의 말을 화면에 보낸다
        self.partial: dict[str, str] = {}
        self.reader = asyncio.create_task(self._read())

    async def send(self, pcm: bytes) -> None:
        body = base64.b64encode(pcm).decode()
        await self.ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": body}))

    def _timing(self, item: str) -> tuple[int | None, int | None]:
        """이 항목의 시작과 길이. VAD 를 못 받았으면 비운다 — 지어내지 않는다.

        틀린 시각을 채우면 화자 접착이 **엉뚱한 구간에 붙는다.** 비워 두면
        `session.py` 가 세션 시계로 메우고, 그쪽이 덜 정확해도 덜 위험하다.
        """
        span = self.spans.pop(item, None)
        if span is None or span[0] is None:
            return None, None
        start, end = span
        return start, (end - start) if end is not None and end > start else None

    async def _read(self) -> None:
        # `websockets` 는 하위 모듈을 늦게 올린다. 연결 전에는 `websockets.exceptions` 가 없다
        from websockets.exceptions import ConnectionClosed

        try:
            while True:
                msg = json.loads(await self.ws.recv())
                kind = msg.get("type")
                item = msg.get("item_id") or ""

                if kind == SPEECH_STARTED:
                    self.spans[item] = [msg.get("audio_start_ms"), None]
                elif kind == SPEECH_STOPPED:
                    span = self.spans.setdefault(item, [None, None])
                    span[1] = msg.get("audio_end_ms")
                elif kind == DELTA:
                    text = self.partial.get(item, "") + (msg.get("delta") or "")
                    self.partial[item] = text
                    if text:
                        await self.on_transcript(Transcript(text=text, final=False))
                elif kind == COMPLETED:
                    self.partial.pop(item, None)
                    start_ms, duration_ms = self._timing(item)
                    if text := (msg.get("transcript") or "").strip():
                        await self.on_transcript(
                            Transcript(
                                text=text,
                                final=True,
                                start_ms=start_ms,
                                duration_ms=duration_ms,
                                # 이 규격은 화자를 안 준다. 사이드카 구간이 붙인다
                                speaker_id=None,
                            )
                        )
                elif kind == FAILED:
                    # 한 조각이 실패해도 상담은 이어진다. 그 말만 사라진다
                    self.partial.pop(item, None)
                    self.spans.pop(item, None)
                    log.warning("전사 실패(item %s): %.80s", item, msg.get("error", ""))
        except (asyncio.CancelledError, ConnectionClosed):
            raise
        except Exception:  # noqa: BLE001  전사 하나가 상담을 끊지 않게 한다
            log.exception("전사 수신이 끊겼습니다")
            return

    async def aclose(self) -> None:
        # 남은 소리를 확정시킨다. 그냥 끊으면 마지막 발화가 사라지고, 그 발화가
        # 리포트의 마지막 항목일 수 있다
        with suppress(Exception):
            await self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await asyncio.wait_for(asyncio.shield(self.reader), timeout=3)
        self.reader.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await self.reader
        with suppress(Exception):
            await self.ws.close()
