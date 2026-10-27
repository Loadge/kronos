"""Add plans table (time-off planner drafts)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("day_type", sa.String(length=16), nullable=False),
        sa.Column("fraction", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("plans")
