"""Sent and arrived: a payout's two sides, and which accounts send and which receive

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09

``freelance_payouts.amount`` / ``currency`` / ``account_id`` keep meaning what ARRIVED. The new
``sent_amount`` / ``sent_currency`` / ``from_account_id`` say what was SENT; all NULL on every row
that exists (NULL sent_amount means "as billed"), so no figure of an existing row changes. An
account's ``role`` says whether it sends, receives or both (existing accounts: both). A source may
name the account it is usually paid from, beside the one it is paid into.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("role", sa.String(length=12), nullable=False, server_default="both")
        )
    with op.batch_alter_table("income_sources") as batch_op:
        batch_op.add_column(sa.Column("default_from_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_income_sources_default_from_account_id",
            "accounts",
            ["default_from_account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("freelance_payouts") as batch_op:
        batch_op.add_column(sa.Column("sent_amount", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("sent_currency", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("from_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_freelance_payouts_from_account_id",
            "accounts",
            ["from_account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_freelance_payouts_from_account_id", ["from_account_id"])


def downgrade() -> None:
    with op.batch_alter_table("freelance_payouts") as batch_op:
        batch_op.drop_index("ix_freelance_payouts_from_account_id")
        batch_op.drop_constraint("fk_freelance_payouts_from_account_id", type_="foreignkey")
        batch_op.drop_column("from_account_id")
        batch_op.drop_column("sent_currency")
        batch_op.drop_column("sent_amount")
    with op.batch_alter_table("income_sources") as batch_op:
        batch_op.drop_constraint("fk_income_sources_default_from_account_id", type_="foreignkey")
        batch_op.drop_column("default_from_account_id")
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("role")
