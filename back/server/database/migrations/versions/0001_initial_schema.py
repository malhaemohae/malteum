"""초기 스키마 — sessions · session_events · rule_packs · pack_embeddings

근거와 결정은 db/SCHEMA.md.

Revision ID: 0001
Revises:
Create Date: 2026-08-30

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # compose 는 db/init.sql 이 만들지만, 로컬 postgres 에 직접 붙는 경우가 있다
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("pack_version", sa.Text(), nullable=False),
        sa.Column("product_code", sa.Text()),
        sa.Column("product_name", sa.Text()),
        sa.Column("customer_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("met", sa.Integer()),
        sa.Column("items_total", sa.Integer()),
        sa.Column("violations", sa.Integer()),
        sa.Column("source_session_id", sa.Text()),
        sa.Column("preset_id", sa.Text()),
        sa.CheckConstraint("mode IN ('live', 'replay', 'trace', 'text')", name="ck_sessions_mode"),
        sa.CheckConstraint(
            "status IN ('running', 'ended', 'aborted', 'timeout')", name="ck_sessions_status"
        ),
    )
    op.create_index("ix_sessions_cursor", "sessions", ["started_at", "session_id"])
    op.create_index("ix_sessions_mode", "sessions", ["mode"])

    op.create_table(
        "session_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("seq_in_session", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pack_version", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("supersedes", sa.Text()),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["supersedes"], ["session_events.event_id"]),
        sa.CheckConstraint(
            "kind IN ('session_started', 'utterance', 'verdict', 'alert', "
            "'assist', 'session_ended')",
            name="ck_session_events_kind",
        ),
        sa.UniqueConstraint("session_id", "seq_in_session", name="uq_session_events_seq"),
    )
    op.create_index(
        "ix_session_events_session_seq", "session_events", ["session_id", "seq_in_session"]
    )
    op.create_index(
        "ix_session_events_supersedes",
        "session_events",
        ["supersedes"],
        postgresql_where=sa.text("supersedes IS NOT NULL"),
    )

    op.create_table(
        "rule_packs",
        sa.Column("pack_version", sa.Text(), primary_key=True),
        sa.Column("product_code", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("product_category", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.Text()),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("doc", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "product_category IN ('deposit', 'loan')", name="ck_rule_packs_category"
        ),
    )

    op.create_table(
        "pack_embeddings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("pack_version", sa.Text(), nullable=False),
        sa.Column("item_code", sa.Text(), nullable=False),
        sa.Column("embedding_id", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        # 차원을 박지 않는다 (db/SCHEMA.md D1)
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["pack_version"], ["rule_packs.pack_version"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "source IN ('item', 'forbidden_example', 'risk_example', "
            "'plain_language', 'jargon_term')",
            name="ck_pack_embeddings_source",
        ),
        sa.UniqueConstraint(
            "pack_version", "item_code", "source", "ordinal", name="uq_pack_embeddings_slot"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("pack_embeddings")
    op.drop_table("rule_packs")
    op.drop_index("ix_session_events_supersedes", table_name="session_events")
    op.drop_index("ix_session_events_session_seq", table_name="session_events")
    op.drop_table("session_events")
    op.drop_index("ix_sessions_mode", table_name="sessions")
    op.drop_index("ix_sessions_cursor", table_name="sessions")
    op.drop_table("sessions")
