"""STT 어댑터 경계. 외부 의존은 어댑터 뒤에 둔다 (P5).

공급자를 갈아끼울 수 있어야 하는 이유가 기획에 적혀 있다 — 리스크 1 이 Deepgram 이
한국어에서 무너질 때의 폴백으로 리턴제로 VITO·네이버 CLOVA 를 두었고, 11.5 는 제품
배치에서 온프렘 STT 가 전제라고 못박았다. 그래서 ws 는 이 Protocol 만 알고 공급자는
`startup.py` 가 고른다.

여기는 전사만 다룬다. 문장 분리·PII 마스킹은 `assembler.py`, 의미 교정은 engine
(judge·refine) 이다 — `server/AGENTS.md` 가 나눠 둔 경계다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Transcript:
    """공급자가 돌려준 한 조각.

    `final` 이 False 면 중간 전사다. 계약상 partial 은 저장하지 않고 화면에만 흘린다.
    """

    text: str
    final: bool
    confidence: float | None = None
    # 말이 시작된 시각과 길이. 공급자가 주면 채우고, 없으면 M1 이 세션 시계로 메운다
    start_ms: int | None = None
    duration_ms: int | None = None


OnTranscript = Callable[[Transcript], Awaitable[None]]


class SttStream(Protocol):
    """상담 하나에 스트림 하나. 오디오를 밀어 넣고 전사를 콜백으로 받는다."""

    async def send(self, pcm: bytes) -> None:
        """16kHz mono PCM16 조각. 계약 audioFrame 의 시퀀스 헤더는 벗겨진 뒤다."""
        ...

    async def aclose(self) -> None:
        """남은 전사를 받고 닫는다. 상담이 끝나거나 소켓이 끊길 때."""
        ...


class SttAdapter(Protocol):
    async def open(self, on_transcript: OnTranscript) -> SttStream:
        """스트림을 연다. 여는 데 실패하면 예외를 올린다 — ws 가 stt_unavailable 로 바꾼다."""
        ...
