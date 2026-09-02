"""후보 승인 기록 — candidate_approvals

근거와 결정은 db/SCHEMA.md (D3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candidate_approvals",
        sa.Column("candidate_id", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("suggested_code", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=False),
        sa.Column("edits", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    # 화면은 문서 하나의 후보를 한 번에 읽는다(계약 GET /documents/{doc_id}/candidates)
    op.create_index("ix_candidate_approvals_doc", "candidate_approvals", ["doc_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_candidate_approvals_doc", table_name="candidate_approvals")
    op.drop_table("candidate_approvals")
