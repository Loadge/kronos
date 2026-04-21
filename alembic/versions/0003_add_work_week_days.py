"""Add work_week_days setting

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )
    op.bulk_insert(settings_table, [{"key": "work_week_days", "value": "0,1,2,3,4"}])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'work_week_days'")
