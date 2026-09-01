"""상담 하나의 STT 배선. 오디오를 어댑터에 밀어넣고 전사를 발화로 바꾼다.

    partial   화면에만 흘린다. 계약이 "저장하지 않는다" 고 못박았다
    final     마스킹·문장 분리를 거쳐 `submit_utterance` 로 간다 → 판정·저장

**화자를 unknown 으로 둔다.** 마이크 하나로는 누가 말했는지 알 수 없고, 리스크 3 이
"라이브는 신뢰도 낮으면 미고지 쪽(P3)" 이라고 정했다. 계약도 partial 의 speaker 에
`unknown` 을 열어 두었다. 확정 발화의 화자는 시연에서 채널 분리 TTS 가 원천 해소하고
(8.1 컷), 라이브는 화자 분리가 붙을 때까지 teller 로 둔다 — 판정 대상이 은행원 발화라
고객 말을 은행원 것으로 보는 쪽이 미고지를 남기는 안전한 방향이다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from contracts.engine_contract import Utterance
from server.services.session.registry import Session
from server.services.stt.assembler import utterances
from server.services.stt.base import SttAdapter, SttStream, Transcript

Publish = Callable[[dict], Awaitable[None]]
Submit = Callable[[Utterance], Awaitable[None]]


class SttSession:
    def __init__(self, session: Session, publish: Publish, submit: Submit) -> None:
        self.session = session
        self.publish = publish
        self.submit = submit
        self.stream: SttStream | None = None

    async def start(self, adapter: SttAdapter, keyterms: Sequence[str] = ()) -> None:
        self.stream = await adapter.open(self._on_transcript, keyterms)

    async def feed(self, pcm: bytes) -> None:
        if self.stream is not None:
            await self.stream.send(pcm)

    async def aclose(self) -> None:
        if self.stream is not None:
            await self.stream.aclose()
            self.stream = None

    async def _on_transcript(self, t: Transcript) -> None:
        if not t.final:
            # 계약: 중간 전사는 저장하지 않는다. 시스템이 듣고 있음을 보여주는 용도다
            await self.publish({"t": "partial", "text": t.text, "speaker": "unknown"})
            return
        for text in utterances(t.text):
            await self.submit(
                Utterance(
                    utterance_id="",  # submit_utterance 가 저장하며 채운다
                    speaker="teller",
                    text=text,
                    t_ms=self.session.elapsed_ms(),
                    duration_ms=t.duration_ms,
                    stt_confidence=t.confidence,
                )
            )
