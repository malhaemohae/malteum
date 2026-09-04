"""화자분리 공급원. "언제 누가 말했나" 만 다룬다.

여기서 나오는 `speaker_id` 는 **번호일 뿐 역할이 아니다.** 어느 번호가 은행원인지
고객인지는 `speaker.py` 의 `RoleMapper` 가 정한다. 화자분리 모델은 목소리 차이로
구간을 가를 뿐이고, 그 번호는 상담마다 달라지며 실제 사람 수보다 많이 나오기도 한다.

공급원을 프로토콜로 둔 이유는 붙일 곳이 셋이기 때문이다.

    TranscriptDiarization   STT 공급자가 전사에 화자 번호를 실어 줄 때 (Deepgram diarize 등)
    ScriptedDiarization     미리 준 구간 목록. 테스트와 시연 재생용
    SortformerDiarization   Sortformer 사이드카(`back/sidecar/diarization/`)에 오디오를
                            흘리고 구간을 받아 오는 클라이언트. 온프레미스 경로다

셋 다 인터페이스가 같다 — "지금까지 확정된 구간을 시간 순서로 돌려준다" 하나뿐이라
스트림이든 조회든 맞출 수 있다. 사이드카만 오디오를 직접 받으므로 `feed`·`aclose` 가
더 있고, `SttSession` 이 그 두 이름이 있는지 보고 같은 PCM 을 나눠 준다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SpeakerSegment:
    """한 화자가 이어서 말한 구간. 시각은 세션 시작을 0 으로 한 밀리초다."""

    start_ms: int
    end_ms: int
    speaker_id: str


class DiarizationSource(Protocol):
    def segments(self) -> Sequence[SpeakerSegment]:
        """지금까지 확정된 구간을 시간 순서로. 아직 없으면 빈 것을 돌려준다.

        발화가 들어올 때마다 불리므로 싸야 한다. 새 구간을 기다리지 않는다 —
        기다리면 발화가 그만큼 붙잡히고, 화자 단계는 발화를 붙잡지 않는 것이 원칙이다.
        """
        ...


class TranscriptDiarization:
    """STT 공급자가 전사에 실어 준 화자 번호를 그대로 쌓는다.

    공급자가 번호를 주지 않으면 구간이 하나도 쌓이지 않고, 그러면 `SpeakerResolver` 가
    화자분리 없음으로 보고 기존 동작(teller 고정 · 신뢰도 None)으로 되돌아간다.
    """

    def __init__(self) -> None:
        self._segments: list[SpeakerSegment] = []

    def note(self, start_ms: int, end_ms: int, speaker_id: str) -> None:
        # 길이를 안 주는 공급자가 있다. 그대로 쌓으면 길이 0 구간이 되어 어떤 발화와도
        # 겹치지 않고, 접착이 `_nearest` 로 내려가 신뢰도가 상한 0.5 에 묶인다.
        # 발화 쪽도 같은 자리에서 최소 1ms 를 잡으므로(`speaker.py` `speaker_of`)
        # 여기서도 그만큼 채워 두면 겹침이 성립한다
        self._segments.append(SpeakerSegment(start_ms, max(end_ms, start_ms + 1), speaker_id))

    def segments(self) -> Sequence[SpeakerSegment]:
        return tuple(self._segments)


class ScriptedDiarization:
    """미리 준 구간 목록을 시각에 따라 내놓는다.

    `now_ms` 를 주면 그 시각까지 시작된 구간만 보인다 — 실제 스트림에서 아직 오지
    않은 구간을 미리 보고 화자를 맞히는 일이 없게 한다. 주지 않으면 전부 보인다.
    """

    def __init__(
        self,
        segments: Iterable[SpeakerSegment],
        *,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._segments = tuple(sorted(segments, key=lambda s: (s.start_ms, s.end_ms)))
        self._now_ms = now_ms

    @classmethod
    def from_lines(
        cls, lines: Iterable[str], *, now_ms: Callable[[], int] | None = None
    ) -> ScriptedDiarization:
        """`"3.040 4.160 speaker_0"` 꼴의 문자열 목록에서 만든다.

        Sortformer 실행 결과(`scripts/experiments/stt/sortformer/streaming_out.json`)가
        구간을 이 형식으로 낸다. 초 단위 실수라 밀리초로 바꾼다.
        """
        segments = []
        for line in lines:
            start, end, speaker_id = line.split()
            segments.append(
                SpeakerSegment(round(float(start) * 1000), round(float(end) * 1000), speaker_id)
            )
        return cls(segments, now_ms=now_ms)

    def segments(self) -> Sequence[SpeakerSegment]:
        if self._now_ms is None:
            return self._segments
        now = self._now_ms()
        return tuple(s for s in self._segments if s.start_ms <= now)


class SortformerDiarization:
    """Sortformer 사이드카 클라이언트. 오디오를 흘려보내고 받은 구간을 쌓는다.

    사이드카는 NeMo 를 얹은 별도 프로세스다(`back/sidecar/diarization/`). 서버의
    `.venv` 와 분리한 이유는 NeMo 의존성이 서버보다 크기 때문이고, 그래서 경계가
    프로세스 사이의 WebSocket 하나다 — 16kHz mono PCM16 을 보내면 청크마다 갱신된
    구간 목록 `{"segments": [{"start_ms", "end_ms", "speaker_id"}, ...]}` 이 온다.

    시각은 세션 시작을 0 으로 한 밀리초다. `SttSession` 이 전사 어댑터와 이 클라이언트에
    같은 PCM 을 처음부터 주므로 전사의 `start_ms` 와 같은 시계 위에 있다.
    """

    def __init__(self, url: str, *, connect_timeout_s: float = 5.0) -> None:
        self.url = url
        self.connect_timeout_s = connect_timeout_s
        self._segments: tuple[SpeakerSegment, ...] = ()
        # 이 구간 목록이 어디까지의 오디오를 보고 나온 값인가. 라벨 지연을 재는 쪽이 쓴다
        self.covered_ms = 0
        self._ws = None
        self._reader: asyncio.Task | None = None
        # ponytail: 한 번 실패하면 다시 붙지 않는다. 화자 분리가 없으면 예전 동작(teller
        # 고정)으로 내려앉을 뿐 상담은 이어지므로, 매 오디오 조각마다 재접속을 시도해
        # 오디오 경로를 붙잡는 것보다 낫다. 재접속이 필요해지면 여기에 백오프를 둔다
        self._unreachable = False

    def segments(self) -> Sequence[SpeakerSegment]:
        return self._segments

    async def feed(self, pcm: bytes) -> None:
        """오디오 한 조각. 사이드카가 없으면 조용히 버린다 — 상담을 끊지 않는다."""
        ws = await self._socket()
        if ws is None:
            return
        try:
            await ws.send(pcm)
        except Exception as e:  # noqa: BLE001  사이드카 장애가 상담을 끊지 않게 한다
            log.warning("화자 분리 사이드카에 오디오를 못 보냈습니다: %s: %s", type(e).__name__, e)
            self._unreachable = True
            # 다시 붙지 않기로 했으므로 읽기 태스크와 소켓도 여기서 거둔다. 참조만
            # 버리면 상담이 끝날 때까지 태스크 하나와 소켓 하나가 그대로 남는다
            await self.aclose()

    async def aclose(self) -> None:
        reader, ws, self._reader, self._ws = self._reader, self._ws, None, None
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if ws is not None:
            try:
                await ws.close()
            except Exception as e:  # noqa: BLE001  닫는 실패는 상담과 무관하다
                log.warning("화자 분리 사이드카를 닫지 못했습니다: %s", e)

    async def _socket(self):
        if self._ws is not None or self._unreachable:
            return self._ws
        import websockets

        try:
            self._ws = await websockets.connect(
                self.url, open_timeout=self.connect_timeout_s, max_size=None
            )
        except Exception as e:  # noqa: BLE001  사이드카가 없어도 서버는 뜬다
            self._unreachable = True
            log.warning("화자 분리 사이드카에 붙지 못했습니다 (%s): %s", self.url, e)
            return None
        self._reader = asyncio.create_task(self._read(self._ws))
        return self._ws

    async def _read(self, ws) -> None:
        """청크마다 오는 구간 목록으로 통째로 갈아 끼운다. 부분 갱신이 아니다.

        Sortformer 는 뒤 오디오를 보고 앞 구간을 고쳐 잡으므로(`RESULT.md` 되돌림),
        누적해서 이어 붙이면 고쳐진 구간과 옛 구간이 함께 남는다.
        """
        try:
            async for message in ws:
                payload = json.loads(message)
                self._segments = tuple(
                    SpeakerSegment(int(s["start_ms"]), int(s["end_ms"]), str(s["speaker_id"]))
                    for s in payload.get("segments", ())
                )
                self.covered_ms = int(payload.get("covered_ms", self.covered_ms))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  수신이 끊겨도 지금까지의 구간은 쓴다
            log.warning("화자 분리 사이드카 수신이 끊겼습니다: %s: %s", type(e).__name__, e)
