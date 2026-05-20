"""Add templates table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-20

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("end_time", sa.String(5), nullable=False),
        sa.Column("breaks", sa.Text, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("templates")
