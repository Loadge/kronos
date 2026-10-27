"""Add fraction to work_entries (partial-day leave)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Every existing row is a whole day: the server default backfills 1.0.
    op.add_column(
        "work_entries",
        sa.Column("fraction", sa.Float(), nullable=False, server_default="1.0"),
    )


def downgrade() -> None:
    # Loses partial-day information; the hours worked on such days stay on the row but
    # the pre-0007 validators would reject them if re-submitted.
    with op.batch_alter_table("work_entries") as batch_op:
        batch_op.drop_column("fraction")
