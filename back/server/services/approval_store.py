"""후보 승인 기록 저장. `PackStore` 와 같은 모양(Protocol · Null · Postgres).

후보는 저장하지 않는다. 후보는 M3 규칙에서 매번 다시 뜨는 파생물이고, 사람이 누른 결정만이
다시 만들 수 없는 원본이다 (AGENTS.md 원칙 3: 이벤트가 원본이고 상태는 파생물).

`event_store="memory"` 모드에는 DB 가 없다. 그 모드에서 승인은 프로세스 안에만 남는다 —
재시작하면 사라진다. 팩 저장소가 그 모드에서 `NullPackStore` 로 아무것도 못 하는 것과
달리 여기는 메모리에라도 담는다. 승인은 화면이 누른 직후 다시 읽는 값이라, 못 담으면
"승인했는데 목록이 그대로" 로 보인다. 사라지는 것은 그 다음 문제다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from server.database.entities import CandidateApproval


class ApprovalStore(Protocol):
    def by_document(self, doc_id: str) -> dict[str, dict[str, Any]]:
        """그 문서의 승인 기록. candidate_id → 기록."""
        ...

    def approve(
        self,
        candidate_id: str,
        doc_id: str,
        suggested_code: str,
        approved_by: str,
        edits: dict[str, Any] | None,
    ) -> datetime:
        """승인 시각을 돌려준다.

        **이미 승인돼 있으면 먼저 남은 기록의 시각을 그대로 돌려준다(멱등).** 계약이
        이 경로에 200 과 400 만 두었기 때문이다. 409 를 내면 화면이 계약에 없는 코드로
        분기해야 한다. 덮어쓰지는 않는다 — 누가 언제 승인했는지가 증빙이라, 두 번째
        승인자는 기록되지 않고 첫 기록이 남는다.
        """
        ...


class MemoryApprovalStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def by_document(self, doc_id: str) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self._rows.items() if v["doc_id"] == doc_id}

    def approve(
        self,
        candidate_id: str,
        doc_id: str,
        suggested_code: str,
        approved_by: str,
        edits: dict[str, Any] | None,
    ) -> datetime:
        existing = self._rows.get(candidate_id)
        if existing is not None:
            return existing["approved_at"]  # 덮어쓰지 않는다. 첫 기록이 증빙이다
        at = datetime.now(UTC)
        self._rows[candidate_id] = {
            "candidate_id": candidate_id,
            "doc_id": doc_id,
            "suggested_code": suggested_code,
            "approved_by": approved_by,
            "edits": edits,
            "approved_at": at,
        }
        return at


class PostgresApprovalStore:
    def __init__(self, sessions: sessionmaker[DbSession]) -> None:
        self._sessions = sessions

    def by_document(self, doc_id: str) -> dict[str, dict[str, Any]]:
        with self._sessions() as db:
            rows = db.scalars(
                select(CandidateApproval).where(CandidateApproval.doc_id == doc_id)
            ).all()
            return {
                row.candidate_id: {
                    "candidate_id": row.candidate_id,
                    "doc_id": row.doc_id,
                    "suggested_code": row.suggested_code,
                    "approved_by": row.approved_by,
                    "edits": row.edits,
                    "approved_at": row.approved_at,
                }
                for row in rows
            }

    def approve(
        self,
        candidate_id: str,
        doc_id: str,
        suggested_code: str,
        approved_by: str,
        edits: dict[str, Any] | None,
    ) -> datetime:
        with self._sessions() as db:
            existing = db.get(CandidateApproval, candidate_id)
            if existing is not None:
                return existing.approved_at  # 덮어쓰지 않는다. 첫 기록이 증빙이다
            row = CandidateApproval(
                candidate_id=candidate_id,
                doc_id=doc_id,
                suggested_code=suggested_code,
                approved_by=approved_by,
                edits=edits,
                approved_at=datetime.now(UTC),
            )
            db.add(row)
            db.commit()
            return row.approved_at
