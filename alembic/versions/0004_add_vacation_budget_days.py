"""Add vacation_budget_days setting

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )
    op.bulk_insert(settings_table, [{"key": "vacation_budget_days", "value": "0"}])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'vacation_budget_days'")
