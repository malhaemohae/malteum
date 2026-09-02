"""테이블 정의. alembic 이 Base.metadata 로 이 모듈들을 본다.

스키마의 근거와 결정은 `db/SCHEMA.md`. 테이블을 바꾸면 그 문서를 같은 커밋에서 함께 고친다.
"""

from __future__ import annotations

from server.database.entities.candidate import CandidateApproval
from server.database.entities.rulepack import (
    EMBEDDING_SOURCES,
    PackEmbedding,
    RulePack,
)
from server.database.entities.session import Session, SessionEvent

__all__ = [
    "EMBEDDING_SOURCES",
    "CandidateApproval",
    "PackEmbedding",
    "RulePack",
    "Session",
    "SessionEvent",
]
