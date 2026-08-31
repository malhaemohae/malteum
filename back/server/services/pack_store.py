"""발행된 규정 팩 조회.

`rule_packs.doc` 한 칸이 정본이라 상세는 그 값을 그대로 돌려주고, 목록은 거기서 뽑는다.

**세션이 쓰는 팩과 원천이 다를 수 있다.** 실행 중인 세션은 engine 의 PackSource 를 거치고
개발 중에는 그게 파일(`settings.pack_dir`)이다. 이 조회는 DB 를 본다. 그래서
`scripts/load_pack.py` 로 넣어두지 않으면 목록이 비어 보인다.
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from server.database.entities import RulePack


class PackStore(Protocol):
    def list(self, product_code: str | None, latest_only: bool) -> list[dict[str, Any]]: ...
    def get(self, pack_version: str) -> dict[str, Any] | None: ...


class NullPackStore:
    """DB 를 쓰지 않는 모드. 발행된 팩이라는 개념이 없다."""

    def list(self, product_code: str | None, latest_only: bool) -> list[dict[str, Any]]:
        return []

    def get(self, pack_version: str) -> dict[str, Any] | None:
        return None


class PostgresPackStore:
    def __init__(self, sessions: sessionmaker[DbSession]) -> None:
        self._sessions = sessions

    def list(self, product_code: str | None, latest_only: bool) -> list[dict[str, Any]]:
        stmt = select(RulePack).order_by(RulePack.product_code, RulePack.pack_version.desc())
        if product_code:
            stmt = stmt.where(RulePack.product_code == product_code)
        with self._sessions() as db:
            rows = list(db.scalars(stmt))
        if latest_only:  # 상품별 첫 행이 최신이다(pack_version 내림차순)
            seen: set[str] = set()
            rows = [r for r in rows if not (r.product_code in seen or seen.add(r.product_code))]
        return [_summary(r) for r in rows]

    def get(self, pack_version: str) -> dict[str, Any] | None:
        with self._sessions() as db:
            row = db.get(RulePack, pack_version)
            return row.doc if row else None


def _summary(row: RulePack) -> dict[str, Any]:
    doc = row.doc
    return {
        "pack_version": row.pack_version,
        "product": doc["product"],
        "published_at": row.published_at,
        "item_count": len(doc.get("items", ())),
        "embedding": {"model": row.embedding_model, "dim": row.embedding_dim},
        "source_count": len(doc.get("sources", ())),
    }
