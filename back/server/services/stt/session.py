"""상담 하나의 STT 배선. 오디오를 어댑터에 밀어넣고 전사를 발화로 바꾼다.

    partial   화면에만 흘린다. 계약이 "저장하지 않는다" 고 못박았다
    final     화자 접착 → 마스킹·문장 분리 → `submit_utterance` → 판정·저장

## 화자

마이크 하나·mono 단일 파일이라 채널로는 못 가른다. 그래서 화자 분리가 준 번호를
발화에 붙이고 그 번호를 역할로 옮기는 일을 `stt/speaker.py` 에 맡긴다. 여기서는
전사의 시각을 메우고, 나온 역할대로 발화를 만들어 보낼 뿐이다.

**화자 분리 공급원이 없으면 예전 그대로다** — `teller` 고정에 `speaker_confidence`
계약 기본값 None 을 그대로 싣는다. 0.0 을 실으면 게이트가 은행원 발화를 전부 접어
필수 고지·금지 발언 판정이 사라진다(`speaker.py` NO_DIARIZATION_CONFIDENCE).

## 확정될 때까지 2초까지 붙잡는다 (DEC-7)

새 화자 번호의 발화는 역할이 확정될 때까지 `hold_ms`(기본 2초)만 붙잡았다가 내보낸다.
붙잡는 동안 뒤 발화가 앞 발화를 앞지르면 리포트의 시간 순서가 무너지므로, 큐 하나를
태스크 하나가 앞에서부터 비운다. 붙잡는 일을 전사 콜백 안에서 그냥 기다리면 공급자의
수신 루프가 그만큼 멈춰(`deepgram.py` `_read`) 중간 전사가 화면에 늦게 뜬다.

`other` 로 판정된 번호의 발화는 submit 하지 않는다. 상담 당사자가 아닌 소리를 은행원의
고지나 고객의 위험 신호로 기록하면 증빙이 오염된다. 다만 무엇을 버렸는지는 로그에
남긴다. 중간 전사는 화자를 가리기 전에 나가므로(`speaker="unknown"`) 그 번호의 말도
화면에는 잠깐 스친다 — 저장되지 않으니 증빙은 오염되지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from contracts.engine_contract import Speaker, Utterance
from server.services.session.registry import Session
from server.services.stt.assembler import utterances
from server.services.stt.base import SttAdapter, SttStream, Transcript
from server.services.stt.diarization import DiarizationSource, TranscriptDiarization
from server.services.stt.speaker import SPEAKER_HOLD_MS, SpeakerResolver

log = logging.getLogger(__name__)

Publish = Callable[[dict], Awaitable[None]]
Submit = Callable[[Utterance], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _Held:
    """붙잡아 둔 발화 하나. `speaker_id` 가 None 이면 화자 분리 공급원이 없는 것이다."""

    text: str
    t_ms: int
    duration_ms: int | None
    stt_confidence: float | None
    speaker_id: str | None
    share: float
    # 이 시각(이벤트 루프 시계)까지만 붙잡는다. 발화가 들어온 순간에 정한다
    deadline: float


class SttSession:
    def __init__(
        self,
        session: Session,
        publish: Publish,
        submit: Submit,
        resolver: SpeakerResolver | None = None,
        *,
        diarization: DiarizationSource | None = None,
        hold_ms: int = SPEAKER_HOLD_MS,
    ) -> None:
        self.session = session
        self.publish = publish
        self.submit = submit
        self.stream: SttStream | None = None
        # 화자 분리 공급원. 기본은 공급자가 전사에 실어 준 번호를 쌓는 것이고, 안 주면
        # 비어 있어 resolver 가 화자 분리 없음으로 본다. 사이드카를 쓰면 부팅이 넣는다
        self.diarization = diarization if diarization is not None else TranscriptDiarization()
        self.resolver = resolver if resolver is not None else SpeakerResolver(self.diarization)
        self.hold_ms = hold_ms
        self._held: deque[_Held] = deque()
        self._releasing: asyncio.Task | None = None
        # 사이드카 공급원만 오디오를 직접 받는다. 전사에 실려 오는 공급원은 받을 것이 없다
        self._to_diarization = getattr(self.diarization, "feed", None)

    async def start(self, adapter: SttAdapter, keyterms: Sequence[str] = ()) -> None:
        # 발화 단위로만 전사하는 어댑터는 화자 분리 구간에서 끊을 자리를 찾는다(base.py)
        self.stream = await adapter.open(
            self._on_transcript, keyterms, diarization=self.diarization
        )

    async def feed(self, pcm: bytes) -> None:
        """같은 PCM 을 전사 어댑터와 화자 분리 사이드카 양쪽에 준다."""
        if self._to_diarization is not None:
            await self._to_diarization(pcm)
        if self.stream is not None:
            await self.stream.send(pcm)

    async def aclose(self) -> None:
        if self.stream is not None:
            await self.stream.aclose()
            self.stream = None
        close_diarization = getattr(self.diarization, "aclose", None)
        if close_diarization is not None:
            await close_diarization()
        if self._releasing is not None:
            # 붙잡아 둔 발화를 상한까지 기다렸다가 마저 내보낸다. 여기서 버리면 마지막
            # 발화가 사라지고, 그 발화가 리포트의 마지막 항목일 수 있다
            await self._releasing
            self._releasing = None
        await self.resolver.aclose()

    async def _on_transcript(self, t: Transcript) -> None:
        if not t.final:
            # 계약: 중간 전사는 저장하지 않는다. 시스템이 듣고 있음을 보여주는 용도다.
            # 화자는 unknown — 중간 전사에는 화자 분리 결과가 아직 안 붙는다
            await self.publish({"t": "partial", "text": t.text, "speaker": "unknown"})
            return
        start_ms, duration_ms = self._timing(t)
        if t.speaker_id is not None and isinstance(self.diarization, TranscriptDiarization):
            self.diarization.note(start_ms, start_ms + (duration_ms or 0), t.speaker_id)
        # 붙잡는 동안 세션 시계가 흐르므로 발화 시각은 들어온 순간에 잡는다
        t_ms = self.session.elapsed_ms()
        deadline = asyncio.get_running_loop().time() + self.hold_ms / 1000
        for text in utterances(t.text):
            picked = self.resolver.pick(text, start_ms, duration_ms)
            self._held.append(
                _Held(
                    text=text,
                    t_ms=t_ms,
                    duration_ms=duration_ms,
                    stt_confidence=t.confidence,
                    speaker_id=picked[0] if picked else None,
                    share=picked[1] if picked else 0.0,
                    deadline=deadline,
                )
            )
        if self._held and (self._releasing is None or self._releasing.done()):
            self._releasing = asyncio.create_task(self._release())

    async def _release(self) -> None:
        """붙잡아 둔 발화를 들어온 순서대로 내보낸다. 태스크 하나가 큐를 앞에서부터 비운다."""
        while self._held:
            held = self._held[0]
            left = held.deadline - asyncio.get_running_loop().time()
            speaker = await self.resolver.hold(held.speaker_id, held.share, left)
            self._held.popleft()
            if speaker.role == "other":
                log.info(
                    "상담 당사자가 아닌 화자(%s)의 발화를 버립니다: %.30s",
                    speaker.speaker_id,
                    held.text,
                )
                continue
            try:
                await self.submit(
                    Utterance(
                        utterance_id="",  # submit_utterance 가 저장하며 채운다
                        speaker=_speaker(speaker.role),
                        text=held.text,
                        t_ms=held.t_ms,
                        duration_ms=held.duration_ms,
                        stt_confidence=held.stt_confidence,
                        speaker_confidence=speaker.confidence,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  발화 하나가 남은 큐를 막지 않게 한다
                log.exception("발화를 넘기지 못했습니다: %.30s", held.text)

    def _timing(self, t: Transcript) -> tuple[int, int | None]:
        """전사의 시각과 길이. 공급자가 안 주면 세션 시계로 메운다.

        확정 전사는 말이 끝난 뒤에 오므로, 세션 시계는 시작이 아니라 끝에 가깝다.
        그래서 길이를 아는 만큼 빼서 시작 시각을 잡는다 — 화자 분리 구간과 맞대는 값이라
        여기서 밀리면 옆 화자의 구간에 붙는다.
        """
        if t.start_ms is not None:
            return t.start_ms, t.duration_ms
        now = self.session.elapsed_ms()
        return now - (t.duration_ms or 0), t.duration_ms


def _speaker(role: str) -> Speaker:
    """`other` 는 앞에서 걸러졌다. 남은 것은 계약의 Speaker 와 같은 값이다."""
    return "customer" if role == "customer" else "teller"
