"""ws 메시지 검증. c2s 는 원본 스키마(jsonschema) → 생성 모델(pydantic) 두 겹으로 본다.

생성 모델은 if/then 의 교차 필드 제약을 못 담으므로 스키마 검증이 앞에 선다.

오디오는 JSON 이 아니라 바이너리 프레임으로 온다(계약 `$defs/audioFrame`). 그 껍질을
벗기는 것도 여기다. 프레임 조립·문장 분리는 `services/stt/assembler.py` 의 몫이고
여기는 전선 위의 모양만 본다.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from server.generated import ws

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "ws_protocol.schema.json"

# 계약: 앞 4바이트가 빅엔디언 unsigned 시퀀스, 그 뒤가 16kHz mono PCM16 100ms
SEQ_BYTES = 4
FRAME_MS = 100
SAMPLE_RATE = 16_000
PCM_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 3,200
FRAME_BYTES = SEQ_BYTES + PCM_BYTES


class InvalidMessage(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """오디오 업링크 한 조각. `seq` 는 재접속 시 손실 구간 판정에 쓴다(계약)."""

    seq: int
    pcm: bytes


def parse_audio_frame(raw: bytes) -> AudioFrame:
    """바이너리 프레임 → 시퀀스와 PCM.

    길이를 고정으로 본다. 계약이 프레임 크기를 못박아 두었고, 어긋난 길이를 받아 넘기면
    조립기가 표본 경계를 잘못 잡아 소리가 밀린 채로 STT 까지 간다. 여기서 거절하는 편이
    낫다.
    """
    if len(raw) != FRAME_BYTES:
        raise InvalidMessage(
            f"오디오 프레임은 {FRAME_BYTES}바이트여야 합니다 (받은 값 {len(raw)})."
        )
    (seq,) = struct.unpack(">I", raw[:SEQ_BYTES])
    return AudioFrame(seq=seq, pcm=raw[SEQ_BYTES:])


@cache
def _validators() -> tuple[Draft202012Validator, Draft202012Validator]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    c2s = {"$ref": "#/$defs/c2s", "$defs": schema["$defs"]}
    s2c = {"$ref": "#/$defs/s2c", "$defs": schema["$defs"]}
    return Draft202012Validator(c2s), Draft202012Validator(s2c)


def parse_c2s(raw: str | bytes | dict[str, Any]):
    data = json.loads(raw) if not isinstance(raw, dict) else raw
    if not isinstance(data, dict) or data.get("t") not in ws.C2S_TYPES:
        raise InvalidMessage(f"알 수 없는 c2s: {data!r}"[:200])
    errors = list(_validators()[0].iter_errors(data))
    if errors:
        raise InvalidMessage("; ".join(e.message for e in errors)[:300])
    return ws.c2s_adapter.validate_python(data)


def check_s2c(data: dict[str, Any]) -> None:
    """보내는 쪽 자기 검사. 테스트와 디버그에서 쓴다."""
    errors = list(_validators()[1].iter_errors(data))
    if errors:
        raise InvalidMessage("; ".join(e.message for e in errors)[:300])
