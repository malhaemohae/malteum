"""`sessions` 파생 투영.

정본은 `session_events` 다. 이 표는 `/sessions` 목록이 mode 로 거르고 커서로 넘기기 위해
존재하며, 값은 전부 두 이벤트(session_started·session_ended)에서 읽는다. 따로 계산하지
않으므로 집계가 이벤트와 갈라질 일이 없다 (db/SCHEMA.md 2절).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy import tuple_ as sa_tuple
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from server.database.entities import Session as SessionRow

# session_ended.reason → sessions.status
_STATUS = {"normal": "ended", "aborted": "aborted", "timeout": "timeout"}


class SessionProjection(Protocol):
    def opened(self, event: dict[str, Any]) -> None: ...
    def ended(self, event: dict[str, Any]) -> None: ...
    def page(
        self, limit: int, mode: str | None, cursor: tuple[datetime, str] | None
    ) -> list[dict[str, Any]]:
        """started_at 내림차순 한 쪽. `/sessions` 목록이 쓴다."""
        ...


class NullSessionProjection:
    """투영을 두지 않는 모드(테스트·메모리 저장). 이벤트만 쌓인다."""

    def opened(self, event: dict[str, Any]) -> None: ...
    def ended(self, event: dict[str, Any]) -> None: ...

    def page(
        self, limit: int, mode: str | None, cursor: tuple[datetime, str] | None
    ) -> list[dict[str, Any]]:
        return []


class PostgresSessionProjection:
    def __init__(self, sessions: sessionmaker[DbSession]) -> None:
        self._sessions = sessions

    def opened(self, event: dict[str, Any]) -> None:
        body = event["session_started"]
        product = body.get("product") or {}
        row = SessionRow(
            session_id=event["session_id"],
            mode=body["mode"],
            pack_version=event["pack_version"],
            product_code=product.get("code"),
            product_name=product.get("name"),
            customer_type=(body.get("customer_profile") or {}).get("type", "general"),
            status="running",
            started_at=datetime.fromisoformat(event["occurred_at"]),
            items_total=body.get("item_count"),
        )
        with self._sessions.begin() as db:
            db.merge(row)  # 같은 session_id 로 다시 열면 덮어쓴다(재접속·재생)

    def ended(self, event: dict[str, Any]) -> None:
        body = event["session_ended"]
        summary = body.get("summary") or {}
        with self._sessions.begin() as db:
            row = db.get(SessionRow, event["session_id"])
            if row is None:  # 투영이 없으면 만들지 않는다. 정본은 이벤트에 이미 있다
                return
            row.status = _STATUS.get(body["reason"], "ended")
            row.ended_at = datetime.fromisoformat(event["occurred_at"])
            row.duration_ms = body.get("duration_ms")
            row.met = summary.get("met")
            row.items_total = summary.get("items_total", row.items_total)
            row.violations = summary.get("violations")

    def page(
        self, limit: int, mode: str | None, cursor: tuple[datetime, str] | None
    ) -> list[dict[str, Any]]:
        stmt = select(SessionRow).order_by(
            SessionRow.started_at.desc(), SessionRow.session_id.desc()
        )
        if mode:
            stmt = stmt.where(SessionRow.mode == mode)
        if cursor:  # (started_at, session_id) 튜플 비교로 같은 시각도 안 건너뛴다
            started, sid = cursor
            stmt = stmt.where(
                sa_tuple(SessionRow.started_at, SessionRow.session_id) < sa_tuple(started, sid)
            )
        with self._sessions() as db:
            rows = list(db.scalars(stmt.limit(limit)))
        return [_summary(r) for r in rows]


def _summary(row: SessionRow) -> dict[str, Any]:
    return {
        "session_id": row.session_id,
        "mode": row.mode,
        "pack_version": row.pack_version,
        "product_name": row.product_name,
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "status": row.status,
        "met": row.met,
        "items_total": row.items_total,
        "violations": row.violations,
    }
