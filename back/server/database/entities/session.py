"""세션과 세션 이벤트.

`session_events` 가 정본이다. append-only 이며 갱신은 새 행 + `supersedes` 로 한다.
`sessions` 는 이벤트를 접으면 다시 만들 수 있는 파생 투영이고, `/sessions` 목록의
mode 필터와 커서 페이지네이션 때문에만 존재한다 (db/SCHEMA.md 2절).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from server.database.base import Base

MODES = ("live", "replay", "trace", "text")
STATUSES = ("running", "ended", "aborted", "timeout")
EVENT_KINDS = (
    "session_started",
    "utterance",
    "verdict",
    "alert",
    "assist",
    "session_ended",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class Session(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    # 팩을 파일에서 읽는 경로(FilePackSource)가 있어 FK 를 걸지 않는다 (db/SCHEMA.md 2절)
    pack_version: Mapped[str] = mapped_column(Text, nullable=False)
    product_code: Mapped[str | None] = mapped_column(Text)
    product_name: Mapped[str | None] = mapped_column(Text)
    customer_type: Mapped[str] = mapped_column(Text, nullable=False, default="general")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # 이벤트를 접은 집계. 목록 조회용이며 정본이 아니다
    met: Mapped[int | None] = mapped_column(Integer)
    items_total: Mapped[int | None] = mapped_column(Integer)
    violations: Mapped[int | None] = mapped_column(Integer)
    source_session_id: Mapped[str | None] = mapped_column(Text)  # mode=trace 재생 대상
    preset_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("mode", MODES), name="ck_sessions_mode"),
        CheckConstraint(_in("status", STATUSES), name="ck_sessions_status"),
        Index("ix_sessions_cursor", "started_at", "session_id"),  # 커서 페이지네이션
        Index("ix_sessions_mode", "mode"),
    )


class SessionEvent(Base):
    """정본. 화면·리포트·trace 재생·감사가 전부 여기서 나온다."""

    __tablename__ = "session_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)  # ULID. envelope 가 찍는다
    # sessions 는 이벤트를 접어 만든 파생 투영이다. 정본이 파생물에 FK 로 매이면
    # 투영을 지울 때 정본이 함께 사라진다. FK 를 걸지 않는다 (db/SCHEMA.md D5)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    seq_in_session: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 이벤트는 낱개로 해석돼야 하므로 모든 행에 둔다 (contracts/README.md)
    pack_version: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes: Mapped[str | None] = mapped_column(Text, ForeignKey("session_events.event_id"))
    schema_version: Mapped[str] = mapped_column(Text, nullable=False, default="1")
    # event[kind] 본문. 계약이 "필드 추가는 안전" 이라 컬럼으로 펼치지 않는다 (db/SCHEMA.md 2절)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("kind", EVENT_KINDS), name="ck_session_events_kind"),
        UniqueConstraint("session_id", "seq_in_session", name="uq_session_events_seq"),
        Index("ix_session_events_session_seq", "session_id", "seq_in_session"),
        Index(
            "ix_session_events_supersedes",
            "supersedes",
            postgresql_where=text("supersedes IS NOT NULL"),
        ),
    )
