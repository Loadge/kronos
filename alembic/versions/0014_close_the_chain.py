"""Close the chain of accounts: every payout has its legs, and the columns the chain replaced go

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-14

Up, in this order and in one run:

1. A payout with no leg gets its chain by the rule 0013 used: one leg for what arrived (``amount``
   in ``currency``, in its ``account_id`` when that account is in that currency), and before it one
   for what was sent when ``sent_amount`` is set. A side without a usable account takes a made
   account of its currency: one that exists already ("<CUR> account", "<CUR> account 2", ... of
   kind "other", not archived) and that the chain does not hold yet, else a new one. The legs made
   here are ``fixed``. The same row gets the same legs from 0013 and from here.
2. Every payout's ``account_id`` becomes the account of its last leg. Nothing else of a payout row
   is written: ``amount``, ``currency``, ``fx_rate``, ``rate_source``, ``rate_date``, ``note``,
   ``week_start`` and ``source_id`` stay what they were, so no figure of a payout can move.
3. The columns go, with their foreign keys and indexes: ``freelance_payouts.sent_amount``,
   ``sent_currency`` and ``from_account_id``; ``income_sources.default_account_id`` and
   ``default_from_account_id``; ``accounts.role``. By then step 1 has used what they said.

A source's two default accounts are dropped without being read: 0013 already turned them into
chains, so a chain that is empty beside defaults at 0014 is one a person emptied in Settings, and
that is the newer truth (a restore of a version 5 file reads it the same way).

Down puts the columns back and keeps every leg. A payout of two or more legs gets its first leg as
the sent side (amount, the account's currency, the account); one leg stays "as billed". A source
of two or more accounts gets its first as "Paid from" and its last as "Paid into"; a source of
one account gets it as "Paid into". Every account is given the role "both".
What going down cannot restore: which accounts were made by 0013 or 0014 (they stay, nothing
says they were not kept); an account's role or a source's default that a person had set to
something a chain cannot say (a role of "origin" or "destination", a "Paid into" that was not the
last account, a default that was an archived account); and the payouts that were stored without
any sent side but went through two accounts since (they come back with a sent side).

The migration imports nothing from the app, so it keeps working when the app's code has moved on.
Every step looks before it acts, so a run cut short is finished by the next one.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None

_legs = sa.table(
    "freelance_payout_legs",
    sa.column("payout_id", sa.Integer),
    sa.column("position", sa.Integer),
    sa.column("account_id", sa.Integer),
    sa.column("amount", sa.Float),
    sa.column("fixed", sa.Boolean),
)


def _columns(conn, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _is_made_name(name: str, currency: str) -> bool:
    """Whether `name` is "USD account" or "USD account 2" (any case) for `currency`."""
    pattern = re.escape(f"{currency} account".casefold()) + r"( \d+)?"
    return re.fullmatch(pattern, name.casefold()) is not None


class _Accounts:
    """The accounts a leg may land in, and the ones this migration makes when none will do."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.has_role = "role" in _columns(conn, "accounts")
        self.now = datetime.now(UTC).replace(tzinfo=None)

    def currency(self, account_id: int | None) -> str | None:
        if account_id is None:
            return None
        return self.conn.execute(
            sa.text("SELECT currency FROM accounts WHERE id = :i"), {"i": account_id}
        ).scalar()

    def _make(self, currency: str) -> int:
        names = {r[0].casefold() for r in self.conn.execute(sa.text("SELECT name FROM accounts"))}
        base, n = f"{currency} account", 1
        name = base
        while name.casefold() in names:
            n += 1
            name = f"{base} {n}"
        top = self.conn.execute(
            sa.text("SELECT COALESCE(MAX(position), -1) FROM accounts")
        ).scalar_one()
        values = {
            "name": name,
            "currency": currency,
            "kind": "other",
            "is_default": False,
            "archived": False,
            "created_at": self.now,
            "position": top + 1,
        }
        if self.has_role:
            values["role"] = "both"
        columns = ", ".join(values)
        marks = ", ".join(f":{k}" for k in values)
        made = self.conn.execute(
            sa.text(f"INSERT INTO accounts ({columns}) VALUES ({marks})"), values
        )
        return made.lastrowid

    def for_side(self, account_id: int | None, currency: str, taken: tuple[int, ...] = ()) -> int:
        """The account of one side of a payout: its own when it has one in that currency and the
        chain does not hold it yet, else a made one of that currency that the chain does not hold,
        else a new one."""
        if (
            account_id is not None
            and account_id not in taken
            and self.currency(account_id) == currency
        ):
            return account_id
        rows = self.conn.execute(
            sa.text(
                "SELECT id, name FROM accounts"
                " WHERE kind = 'other' AND currency = :c AND NOT archived ORDER BY id"
            ),
            {"c": currency},
        ).all()
        for found_id, name in rows:
            if found_id not in taken and _is_made_name(name, currency):
                return found_id
        return self._make(currency)


def upgrade() -> None:
    conn = op.get_bind()
    _payout_legs(conn)
    conn.execute(
        sa.text(
            "UPDATE freelance_payouts SET account_id = ("
            " SELECT l.account_id FROM freelance_payout_legs l"
            " WHERE l.payout_id = freelance_payouts.id ORDER BY l.position DESC LIMIT 1)"
            " WHERE EXISTS (SELECT 1 FROM freelance_payout_legs l"
            " WHERE l.payout_id = freelance_payouts.id)"
        )
    )
    _drop_columns(conn)


def _payout_legs(conn) -> None:
    """One leg for what arrived; before it, one for what was sent when that was recorded."""
    sent = _columns(conn, "freelance_payouts") >= {
        "sent_amount",
        "sent_currency",
        "from_account_id",
    }
    rows = conn.execute(
        sa.text(
            "SELECT p.id, p.amount, p.currency, p.account_id,"
            + (
                " p.sent_amount, p.sent_currency, p.from_account_id,"
                if sent
                else " NULL, NULL, NULL,"
            )
            + " s.currency FROM freelance_payouts p"
            " LEFT JOIN income_sources s ON s.id = p.source_id"
            " WHERE NOT EXISTS (SELECT 1 FROM freelance_payout_legs l WHERE l.payout_id = p.id)"
            " ORDER BY p.id"
        )
    ).all()
    accounts = _Accounts(conn)
    for payout_id, amount, currency, into, sent_amount, sent_currency, sent_from, billed in rows:
        arrived = accounts.for_side(into, currency)
        legs = [(arrived, amount)]
        if sent_amount is not None:
            # What was sent is in its own currency. A row without one (only a restored backup can
            # hold it) is in its account's, else in the source's, else the payout's.
            sent_in = sent_currency or accounts.currency(sent_from) or billed or currency
            legs.insert(0, (accounts.for_side(sent_from, sent_in, taken=(arrived,)), sent_amount))
        for position, (account_id, leg_amount) in enumerate(legs):
            conn.execute(
                _legs.insert().values(
                    payout_id=payout_id,
                    position=position,
                    account_id=account_id,
                    amount=leg_amount,
                    fixed=True,
                )
            )


def _drop_columns(conn) -> None:
    payouts = _columns(conn, "freelance_payouts")
    if "from_account_id" in payouts:
        with op.batch_alter_table("freelance_payouts") as batch_op:
            batch_op.drop_index("ix_freelance_payouts_from_account_id")
            batch_op.drop_constraint("fk_freelance_payouts_from_account_id", type_="foreignkey")
            batch_op.drop_column("from_account_id")
            batch_op.drop_column("sent_currency")
            batch_op.drop_column("sent_amount")
    sources = _columns(conn, "income_sources")
    if "default_account_id" in sources:
        with op.batch_alter_table("income_sources") as batch_op:
            batch_op.drop_constraint(
                "fk_income_sources_default_from_account_id", type_="foreignkey"
            )
            batch_op.drop_constraint("fk_income_sources_default_account_id", type_="foreignkey")
            batch_op.drop_column("default_from_account_id")
            batch_op.drop_column("default_account_id")
    if "role" in _columns(conn, "accounts"):
        with op.batch_alter_table("accounts") as batch_op:
            batch_op.drop_column("role")


def downgrade() -> None:
    conn = op.get_bind()
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("role", sa.String(length=12), nullable=False, server_default="both")
        )
    with op.batch_alter_table("income_sources") as batch_op:
        batch_op.add_column(sa.Column("default_account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("default_from_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_income_sources_default_account_id",
            "accounts",
            ["default_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
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
    # A payout of two or more legs: its first leg as the sent side.
    conn.execute(
        sa.text(
            "UPDATE freelance_payouts SET"
            " sent_amount = (SELECT l.amount FROM freelance_payout_legs l"
            "  WHERE l.payout_id = freelance_payouts.id AND l.position = 0),"
            " sent_currency = (SELECT a.currency FROM freelance_payout_legs l"
            "  JOIN accounts a ON a.id = l.account_id"
            "  WHERE l.payout_id = freelance_payouts.id AND l.position = 0),"
            " from_account_id = (SELECT l.account_id FROM freelance_payout_legs l"
            "  WHERE l.payout_id = freelance_payouts.id AND l.position = 0)"
            " WHERE (SELECT COUNT(*) FROM freelance_payout_legs l"
            "  WHERE l.payout_id = freelance_payouts.id) >= 2"
        )
    )
    # A source: the first account of its chain as "Paid from" when it has two or more, the last
    # (the only one, if there is one) as "Paid into".
    for source_id, count in conn.execute(
        sa.text("SELECT source_id, COUNT(*) FROM income_source_accounts GROUP BY source_id")
    ).all():
        accounts = [
            r[0]
            for r in conn.execute(
                sa.text(
                    "SELECT account_id FROM income_source_accounts"
                    " WHERE source_id = :s ORDER BY position"
                ),
                {"s": source_id},
            )
        ]
        conn.execute(
            sa.text(
                "UPDATE income_sources SET default_from_account_id = :f,"
                " default_account_id = :t WHERE id = :s"
            ),
            {"f": accounts[0] if count >= 2 else None, "t": accounts[-1], "s": source_id},
        )
