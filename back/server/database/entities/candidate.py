"""후보 승인 기록.

계약 `POST /documents/{doc_id}/candidates/{candidate_id}/approve` 가 남기는 것. 후보
자체는 저장하지 않는다 — 후보는 M3 규칙에서 매번 다시 뜨는 파생물이고, 사람이 누른
결정만이 다시 만들 수 없는 원본이다 (AGENTS.md 원칙 3).

`candidate_id` 는 `{doc_id}:{code}` 로 결정되므로(services/candidates.py) 파이프라인을
다시 돌려도 어제 승인한 후보가 오늘 다른 후보가 되지 않는다.

승인은 한 번이다. 같은 후보를 두 번 누르면 먼저 누른 기록이 남는다 — 누가 언제 승인했는지가
증빙이라 뒤에 누른 사람으로 조용히 바뀌면 안 된다. 고칠 일이 생기면 승인을 취소하고 다시
누르는 것이 맞고, 그 경로는 계약에 아직 없다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from server.database.base import Base


class CandidateApproval(Base):
    __tablename__ = "candidate_approvals"

    candidate_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text, nullable=False)
    # 승인 시점의 항목 코드. 규칙이 바뀌어 코드가 갈려도 무엇을 승인했는지가 남는다
    suggested_code: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str] = mapped_column(Text, nullable=False)
    # 검수자가 고친 내용. 계약이 name·requirement_elements·l1_patterns·plain_language 를 받는다
    edits: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
