"""ws 메시지 검증. c2s 는 원본 스키마(jsonschema) → 생성 모델(pydantic) 두 겹으로 본다.

생성 모델은 if/then 의 교차 필드 제약을 못 담으므로 스키마 검증이 앞에 선다.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from server.generated import ws

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "ws_protocol.schema.json"


class InvalidMessage(ValueError):
    pass


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
