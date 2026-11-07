"""Add accounts (where the money lands) and the payout's rate provenance

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-07

Existing payouts keep ``account_id`` NULL, which means "in the source's currency", and no rate
provenance: no figure of an existing row changes. The currency columns are widened from 3 to 8
characters so a coin's code (USDC, USDT) fits where the models say it does.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("income_sources") as batch_op:
        batch_op.alter_column(
            "currency", existing_type=sa.String(length=3), type_=sa.String(length=8)
        )
        batch_op.add_column(sa.Column("default_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_income_sources_default_account_id",
            "accounts",
            ["default_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("freelance_blocks") as batch_op:
        batch_op.alter_column(
            "currency", existing_type=sa.String(length=3), type_=sa.String(length=8)
        )
    with op.batch_alter_table("freelance_payouts") as batch_op:
        batch_op.alter_column(
            "currency", existing_type=sa.String(length=3), type_=sa.String(length=8)
        )
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rate_source", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("rate_date", sa.Date(), nullable=True))
        batch_op.create_foreign_key(
            "fk_freelance_payouts_account_id",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_freelance_payouts_account_id", ["account_id"])


def downgrade() -> None:
    with op.batch_alter_table("freelance_payouts") as batch_op:
        batch_op.drop_index("ix_freelance_payouts_account_id")
        batch_op.drop_constraint("fk_freelance_payouts_account_id", type_="foreignkey")
        batch_op.drop_column("rate_date")
        batch_op.drop_column("rate_source")
        batch_op.drop_column("account_id")
        batch_op.alter_column(
            "currency", existing_type=sa.String(length=8), type_=sa.String(length=3)
        )
    with op.batch_alter_table("freelance_blocks") as batch_op:
        batch_op.alter_column(
            "currency", existing_type=sa.String(length=8), type_=sa.String(length=3)
        )
    with op.batch_alter_table("income_sources") as batch_op:
        batch_op.drop_constraint("fk_income_sources_default_account_id", type_="foreignkey")
        batch_op.drop_column("default_account_id")
        batch_op.alter_column(
            "currency", existing_type=sa.String(length=8), type_=sa.String(length=3)
        )
    op.drop_table("accounts")
