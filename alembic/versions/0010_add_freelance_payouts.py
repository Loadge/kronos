"""Add freelance payouts: what a source paid for an ISO week

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "freelance_payouts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("income_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("source_id", "week_start", name="uq_freelance_payouts_source_week"),
    )
    op.create_index("ix_freelance_payouts_source_id", "freelance_payouts", ["source_id"])
    op.create_index("ix_freelance_payouts_week_start", "freelance_payouts", ["week_start"])


def downgrade() -> None:
    op.drop_index("ix_freelance_payouts_week_start", table_name="freelance_payouts")
    op.drop_index("ix_freelance_payouts_source_id", table_name="freelance_payouts")
    op.drop_table("freelance_payouts")
