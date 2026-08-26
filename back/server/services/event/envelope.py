"""이벤트 봉투. event_id·seq_in_session·occurred_at·pack_version·supersedes 는 여기서만 찍는다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ulid import ULID

SCHEMA_VERSION = "1"


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
