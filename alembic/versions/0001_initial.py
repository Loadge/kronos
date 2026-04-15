"""initial schema: work_entries, breaks, settings

Revision ID: 0001
Revises:
Create Date: 2026-04-14

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "work_entries",
        sa.Column("date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("day_type", sa.String(length=16), nullable=False, server_default="work"),
        sa.Column("start_time", sa.String(length=5), nullable=True),
        sa.Column("end_time", sa.String(length=5), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "breaks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "entry_date",
            sa.Date(),
            sa.ForeignKey("work_entries.date", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("break_minutes", sa.Integer(), nullable=False),
    )
    op.create_index("ix_breaks_entry_date", "breaks", ["entry_date"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("value", sa.String(length=256), nullable=False),
    )

    # Seed default settings so the app is usable on first launch.
    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )
    op.bulk_insert(
        settings_table,
        [
            {"key": "daily_target_hours", "value": "8.0"},
            {"key": "cumulative_start_date", "value": "2025-01-01"},
        ],
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_breaks_entry_date", table_name="breaks")
    op.drop_table("breaks")
    op.drop_table("work_entries")
