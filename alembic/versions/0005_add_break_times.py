"""Add start_time and end_time to breaks

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-05

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("breaks", sa.Column("start_time", sa.String(5), nullable=True))
    op.add_column("breaks", sa.Column("end_time", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("breaks", "end_time")
    op.drop_column("breaks", "start_time")
