"""Add freelance tables: income sources, hour blocks and per-year tax inputs

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "income_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("hourly_rate", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "freelance_blocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("income_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=True),
        sa.Column("end_time", sa.String(length=5), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate", sa.Float(), nullable=True),
    )
    op.create_index("ix_freelance_blocks_date", "freelance_blocks", ["date"])
    op.create_index("ix_freelance_blocks_source_id", "freelance_blocks", ["source_id"])
    op.create_table(
        "freelance_tax_years",
        sa.Column("year", sa.Integer(), primary_key=True, autoincrement=False, nullable=False),
        sa.Column("salary_annual", sa.Float(), nullable=False),
        sa.Column("tarifa_plana", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("inicio_actividad", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("set_aside_share", sa.Float(), nullable=False, server_default="0.4"),
        sa.Column("gestoria_annual", sa.Float(), nullable=False, server_default="0"),
        sa.Column("other_expenses", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("freelance_tax_years")
    op.drop_index("ix_freelance_blocks_source_id", table_name="freelance_blocks")
    op.drop_index("ix_freelance_blocks_date", table_name="freelance_blocks")
    op.drop_table("freelance_blocks")
    op.drop_table("income_sources")
