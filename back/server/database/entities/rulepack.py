"""규정 팩과 그 임베딩.

`rule_packs.doc` JSONB 한 칸이 정본이다. 나머지 컬럼은 조회용으로 doc 에서 복사한 값이다.
정규화하지 않는 이유 둘: engine 이 server 를 import 할 수 없어 `SELECT doc` 한 줄이어야 하고,
팩 스키마가 계속 늘어나기 때문이다 (db/SCHEMA.md 2절).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.database.base import Base


class RulePack(Base):
    """불변 발행물. 고칠 일이 생기면 UPDATE 하지 않고 새 pack_version 을 낸다."""

    __tablename__ = "rule_packs"

    pack_version: Mapped[str] = mapped_column(Text, primary_key=True)
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    product_category: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_by: Mapped[str | None] = mapped_column(Text)
    # 차원을 팩에 묶는다. 모델을 바꾸면 팩을 재발행한다 (rulepack.schema.json)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    doc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 정본
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 자식을 선언해 두면 SQLAlchemy 가 삽입 순서를 스스로 잡고, 팩을 지울 때
    # 임베딩도 함께 간다. passive_deletes 는 자식을 하나씩 SELECT 해서 지우는
    # 대신 DB 의 ON DELETE CASCADE 에 맡긴다.
    embeddings: Mapped[list[PackEmbedding]] = relationship(
        back_populates="pack", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("product_category IN ('deposit', 'loan')", name="ck_rule_packs_category"),
    )


class PackEmbedding(Base):
    """L2 의 검색면. 항목뿐 아니라 금지·위험 예시와 쉬운 말도 각각 한 행이 된다.

    벡터 컬럼에 차원을 박지 않는다(D1). 규모가 팩당 25행 안팎이라 인덱스 이득이 없고,
    e5-small(384) → bge-m3(1024) 교체기에 두 차원이 한동안 함께 존재하기 때문이다.
    """

    __tablename__ = "pack_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pack_version: Mapped[str] = mapped_column(
        Text, ForeignKey("rule_packs.pack_version", ondelete="CASCADE"), nullable=False
    )
    item_code: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_id: Mapped[str | None] = mapped_column(Text)  # 팩의 item.embedding_id (있으면)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)  # 임베딩 원문
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)

    pack: Mapped[RulePack] = relationship(back_populates="embeddings")

    __table_args__ = (
        CheckConstraint(
            "source IN ('item', 'forbidden_example', 'risk_example', "
            "'plain_language', 'jargon_term')",
            name="ck_pack_embeddings_source",
        ),
        UniqueConstraint(
            "pack_version", "item_code", "source", "ordinal", name="uq_pack_embeddings_slot"
        ),
    )
