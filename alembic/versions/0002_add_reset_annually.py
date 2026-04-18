"""Add reset_annually setting

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )
    op.bulk_insert(settings_table, [{"key": "reset_annually", "value": "false"}])


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'reset_annually'")
