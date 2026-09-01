"""사전 오디오 찾기와 실시간 속도 흘려보내기. `replay` 가 쓴다.

`replay` 는 "사전 오디오를 실시간 속도로 STT 에" 보내는 모드다(11.4, 기본 시연 경로).
`live` 와 다른 점은 소리를 누가 주느냐뿐이다 — live 는 브라우저가 바이너리 프레임으로
밀어 넣고, replay 는 서버가 파일을 읽어 같은 크기로 흘린다. 그래서 STT 아래 경로는
완전히 같다.

**실시간 속도로 보내는 이유.** 몰아서 보내면 STT 가 partial 을 안 내고 결과가 한꺼번에
온다. 그러면 화면이 "듣고 있음" 을 못 보여주고, 심사위원이 보는 것은 녹화 재생이 아니라
결과 덤프가 된다. 무엇보다 판정이 상담 흐름 순서대로 쌓이지 않는다.
"""

from __future__ import annotations

import asyncio
import wave
from collections.abc import AsyncIterator
from pathlib import Path

FRAME_MS = 100  # 계약 audioFrame 과 같은 크기
SAMPLE_RATE = 16_000


class AudioNotFound(FileNotFoundError):
    pass


def resolve(root: Path, audio_ref: str) -> Path:
    """`audio_ref` → 실제 파일.

    `assets/scenarios/` 아래를 본다(최상위 README 가 시연 자산을 두는 자리로 정한 곳).
    지금 그 폴더가 비어 있어 R5 가 채우면 그대로 붙는다.

    `..` 로 밖을 파고들지 못하게 막는다 — 참조는 심사위원 화면에서 오는 값이다.
    """
    if not audio_ref or "\x00" in audio_ref:
        raise AudioNotFound("audio_ref 가 비었습니다.")
    base = root.resolve()
    target = (base / audio_ref).resolve()
    if not target.is_relative_to(base):
        raise AudioNotFound(f"자산 폴더 밖입니다: {audio_ref}")
    if not target.is_file():
        raise AudioNotFound(f"오디오가 없습니다: {audio_ref}")
    return target


def read_pcm(path: Path) -> bytes:
    """16kHz mono PCM16 만 받는다. 계약 audioFrame 과 같은 규격이라 그대로 흘린다.

    다른 규격을 받아 넘기면 STT 가 소리를 어긋나게 해석해 전사가 비거나 밀린다.
    변환은 자산을 만드는 쪽(R5)이 할 일이지 상담 경로가 할 일이 아니다.
    """
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
            raise AudioNotFound(
                f"16kHz mono PCM16 이 아닙니다: {path.name} "
                f"({w.getnchannels()}ch {w.getsampwidth() * 8}bit {w.getframerate()}Hz)"
            )
        return w.readframes(w.getnframes())


async def stream(pcm: bytes) -> AsyncIterator[bytes]:
    """실시간 속도로 100ms 씩 내보낸다."""
    chunk = SAMPLE_RATE * 2 * FRAME_MS // 1000
    for off in range(0, len(pcm), chunk):
        yield pcm[off : off + chunk]
        await asyncio.sleep(FRAME_MS / 1000)
