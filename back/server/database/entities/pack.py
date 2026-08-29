"""규정 팩 저장 테이블. M3(rulepack)이 발행한 팩을 담는다.

세 테이블로 나눈 이유
    `pack`           팩 한 벌의 머리. 발행 정보와 임베딩 모델 정보
    `pack_item`      항목. 판정이 실제로 읽는 본문
    `item_embedding` 벡터 본체. 팩 JSON 에 넣으면 파일이 거대해지고 diff 가 무의미해진다

적재는 `scripts/load_pack.py` 가 SQL 로 한다. rulepack 은 server 를 import 할 수
없으므로(import-linter) 이 모델을 가져다 쓰지 않는다. 이 파일은 alembic 이
스키마를 만들 때만 쓰인다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from server.database.base import Base


class Pack(Base):
    """발행된 팩 한 벌. 불변이라 갱신하지 않고 새 `pack_version` 을 넣는다."""

    __tablename__ = "pack"
    __table_args__ = (
        CheckConstraint("product_category in ('deposit','loan')", name="ck_pack_category"),
        CheckConstraint("embedding_dim > 0", name="ck_pack_embedding_dim"),
    )

    pack_version: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)

    # contracts 의 product 객체를 펼친다. 세 필드 고정이고(additionalProperties false)
    # 상품 종류로 거르는 조회가 잦아 JSONB 보다 열로 두는 편이 낫다.
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    product_category: Mapped[str] = mapped_column(Text, nullable=False)

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_by: Mapped[str | None] = mapped_column(Text)

    # 차원을 팩에 묶는다(contracts 지시). 벡터 열에 차원을 박으면 모델 교체 때
    # 마이그레이션이 필요해지므로, 차원은 여기 값으로만 들고 있는다.
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_normalized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    jargon_terms: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class PackItem(Base):
    """팩 항목. `code` 는 팩 버전이 올라가도 유지되므로 버전과 함께 키가 된다."""

    __tablename__ = "pack_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pack_version"], ["pack.pack_version"], ondelete="RESTRICT", name="fk_pack_item_pack"
        ),
        CheckConstraint(
            "type in ('required','forbidden','reference','risk')", name="ck_pack_item_type"
        ),
        CheckConstraint(
            "axis is null or axis in ('omission','commission')", name="ck_pack_item_axis"
        ),
        Index("ix_pack_item_type", "pack_version", "type"),
    )

    pack_version: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    axis: Mapped[str | None] = mapped_column(Text)

    requirement_elements: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    legal_basis: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    # P4 의 관문. 발행된 팩의 항목은 span 이 원문에 실재함이 이미 대조된 것들이다.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    l1_patterns: Mapped[list[Any] | None] = mapped_column(JSONB)
    embedding_id: Mapped[str | None] = mapped_column(Text)
    plain_language: Mapped[list[Any] | None] = mapped_column(JSONB)
    numeric_facts: Mapped[list[Any] | None] = mapped_column(JSONB)
    documents_required: Mapped[list[Any] | None] = mapped_column(JSONB)
    forbidden_examples: Mapped[list[Any] | None] = mapped_column(JSONB)
    risk_examples: Mapped[list[Any] | None] = mapped_column(JSONB)

    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(Text)


class ItemEmbedding(Base):
    """항목 벡터.

    `embedding_id` 는 `e5:<code>` 형태라 팩 버전이 달라도 같은 값이 나온다. 그래서
    버전과 묶어야 서로 다른 팩의 벡터가 덮어써지지 않는다.

    벡터 열에 차원을 박지 않았다. 차원이 다른 모델로 갈아탈 때 팩만 재발행하면
    되고 스키마는 그대로다. 대신 pgvector 인덱스는 차원 고정을 요구하므로 지금은
    인덱스가 없다. 항목이 수천 건대로 늘면 그때 차원별 분리를 다시 본다.
    """

    __tablename__ = "item_embedding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pack_version"],
            ["pack.pack_version"],
            ondelete="RESTRICT",
            name="fk_item_embedding_pack",
        ),
    )

    pack_version: Mapped[str] = mapped_column(Text, primary_key=True)
    embedding_id: Mapped[str] = mapped_column(Text, primary_key=True)
    vector: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
