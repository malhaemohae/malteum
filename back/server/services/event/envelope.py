"""이벤트 봉투. event_id·seq_in_session·occurred_at·pack_version·supersedes 는 여기서만 찍는다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ulid import ULID

SCHEMA_VERSION = "1"

# events.schema.json $defs/id. ws 쪽 session_id 에는 이 제약이 없어서,
# 짧은 id 로 붙으면 ws 검증은 통과하고 저장에서 터진다. 경계에서 M1 이 막는다
ID_MIN, ID_MAX = 8, 64


def valid_id(value: str) -> bool:
    return ID_MIN <= len(value) <= ID_MAX


def new_id() -> str:
    return str(ULID())


def wrap(
    *,
    session_id: str,
    pack_version: str,
    seq_in_session: int,
    kind: str,
    body: dict[str, Any],
    supersedes: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": new_id(),
        "session_id": session_id,
        "seq_in_session": seq_in_session,
        "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(timespec="milliseconds"),
        "pack_version": pack_version,
        "kind": kind,
        "supersedes": supersedes,
        kind: body,
    }
