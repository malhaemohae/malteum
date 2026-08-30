"""append-only 이벤트 저장. 이 표가 정본이고 나머지는 전부 여기서 접어 만든다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from server.database.entities import SessionEvent
from server.generated import events as gen


class EventStore(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...

    def append_many(self, events: list[dict[str, Any]]) -> None:
        """한 판정에서 나온 이벤트들을 한 번에 넣는다. 부분 저장을 막는다."""
        ...

    def of_session(self, session_id: str) -> list[dict[str, Any]]: ...

    def healthy(self) -> bool:
        """저장소가 살아 있는가. /health 의 checks.db 가 쓴다."""
        ...


class MemoryEventStore:
    """개발·테스트용. 재시작하면 사라지므로 trace 재생과 리포트가 불가능하다."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def append(self, event: dict[str, Any]) -> None:
        gen.event_adapter.validate_python(event)  # 저장물은 스키마를 벗어나지 않는다
        self._events.append(event)

    def append_many(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            self.append(event)

    def of_session(self, session_id: str) -> list[dict[str, Any]]:
        return [e for e in self._events if e["session_id"] == session_id]

    def healthy(self) -> bool:
        return True


class PostgresEventStore:
    """봉투는 컬럼으로, 본문은 JSONB 로 나눠 담고 읽을 때 원래 모양으로 되돌린다.

    되돌린 dict 는 `envelope.wrap` 이 만든 것과 같아야 한다. 그래야 fold·summarize 가
    실시간 경로와 저장 경로에서 같은 값을 낸다.
    """

    def __init__(self, sessions: sessionmaker[DbSession]) -> None:
        self._sessions = sessions

    def append(self, event: dict[str, Any]) -> None:
        self.append_many([event])

    def append_many(self, events: list[dict[str, Any]]) -> None:
        rows = [_to_row(e) for e in events]
        with self._sessions.begin() as db:  # 한 트랜잭션. 부분 저장이 남지 않는다
            db.add_all(rows)

    def healthy(self) -> bool:
        try:
            with self._sessions() as db:
                db.execute(select(1))
            return True
        except SQLAlchemyError:
            return False

    def of_session(self, session_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.seq_in_session)
        )
        with self._sessions() as db:
            return [_to_event(r) for r in db.scalars(stmt)]


def _to_row(event: dict[str, Any]) -> SessionEvent:
    gen.event_adapter.validate_python(event)  # 저장물은 스키마를 벗어나지 않는다
    kind = event["kind"]
    return SessionEvent(
        event_id=event["event_id"],
        session_id=event["session_id"],
        seq_in_session=event["seq_in_session"],
        occurred_at=datetime.fromisoformat(event["occurred_at"]),
        pack_version=event["pack_version"],
        kind=kind,
        supersedes=event.get("supersedes"),
        schema_version=event["schema_version"],
        body=event[kind],
    )


def _to_event(row: SessionEvent) -> dict[str, Any]:
    return {
        "schema_version": row.schema_version,
        "event_id": row.event_id,
        "session_id": row.session_id,
        "seq_in_session": row.seq_in_session,
        "occurred_at": row.occurred_at.astimezone(UTC).isoformat(timespec="milliseconds"),
        "pack_version": row.pack_version,
        "kind": row.kind,
        "supersedes": row.supersedes,
        row.kind: row.body,
    }
