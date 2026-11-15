"""The chain of accounts: a payout's legs, a source's usual chain, and a hand-made order

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-11

This migration only adds. No row of ``freelance_payouts`` is updated: ``amount`` / ``currency`` /
``fx_rate`` / ``rate_source`` / ``rate_date`` stay what they were, and they are the figures of the
LAST account of the chain, the ones every total reads. So no figure of an existing payout can move.

What it adds:

* ``freelance_payout_legs``: one row per account the money went through, in order, with the amount
  in that account's currency and whether it was typed (``fixed``). An existing payout gets one leg
  (what arrived) or two (what was sent, then what arrived).
* ``income_source_accounts``: the accounts a source is usually paid through, in order. "Paid from"
  becomes its first, "Paid into" the next; the same account twice becomes one; archived accounts
  are left out.
* ``position`` on accounts, income sources and day templates: the order they are listed in, which
  starts as the order they have today.

A leg needs an account. A side that has none (a payout from before accounts, a sent side in a bare
currency) gets one made here, one per currency: "USD account", "EUR account". A chain never
repeats an account, so a sent side in the same account as the arrival gets another made one.
Going down drops what was added; the accounts made here stay, as nothing says they were not kept.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None

# A real Table, with its key, so an insert says which id it was given.
_accounts = sa.Table(
    "accounts",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String),
    sa.Column("currency", sa.String),
    sa.Column("kind", sa.String),
    sa.Column("is_default", sa.Boolean),
    sa.Column("archived", sa.Boolean),
    sa.Column("role", sa.String),
    sa.Column("created_at", sa.DateTime),
    sa.Column("position", sa.Integer),
)
_legs = sa.table(
    "freelance_payout_legs",
    sa.column("payout_id", sa.Integer),
    sa.column("position", sa.Integer),
    sa.column("account_id", sa.Integer),
    sa.column("amount", sa.Float),
    sa.column("fixed", sa.Boolean),
)
_chain = sa.table(
    "income_source_accounts",
    sa.column("source_id", sa.Integer),
    sa.column("position", sa.Integer),
    sa.column("account_id", sa.Integer),
)


def _tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _index(conn, name: str, table: str, column: str) -> None:
    if name not in {i["name"] for i in sa.inspect(conn).get_indexes(table)}:
        op.create_index(name, table, [column])


def upgrade() -> None:
    """SQLite keeps a table it was told to create even when the rest of the migration fails, so
    a run cut short (a kill, a full disk) leaves the new tables behind with the revision still
    at the old one. Every step here looks before it adds, and the rows are written from scratch,
    so the next start finishes the job instead of failing on "table already exists"."""
    conn = op.get_bind()
    if "freelance_payout_legs" not in _tables(conn):
        _create_legs()
    _index(conn, "ix_freelance_payout_legs_payout_id", "freelance_payout_legs", "payout_id")
    _index(conn, "ix_freelance_payout_legs_account_id", "freelance_payout_legs", "account_id")
    if "income_source_accounts" not in _tables(conn):
        _create_source_chains()
    _index(conn, "ix_income_source_accounts_source_id", "income_source_accounts", "source_id")
    _index(conn, "ix_income_source_accounts_account_id", "income_source_accounts", "account_id")
    for table in ("accounts", "income_sources", "templates"):
        if "position" not in {c["name"] for c in sa.inspect(conn).get_columns(table)}:
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(
                    sa.Column("position", sa.Integer(), nullable=False, server_default="0")
                )

    conn.execute(_legs.delete())
    conn.execute(_chain.delete())
    _keep_todays_order(conn)
    _source_chains(conn)
    _payout_legs(conn)


def _create_legs() -> None:
    op.create_table(
        "freelance_payout_legs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "payout_id",
            sa.Integer(),
            sa.ForeignKey("freelance_payouts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("fixed", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("payout_id", "position", name="uq_freelance_payout_legs_position"),
        sa.UniqueConstraint("payout_id", "account_id", name="uq_freelance_payout_legs_account"),
        sa.CheckConstraint("position BETWEEN 0 AND 3", name="ck_freelance_payout_legs_position"),
    )


def _create_source_chains() -> None:
    op.create_table(
        "income_source_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("income_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("source_id", "position", name="uq_income_source_accounts_position"),
        sa.UniqueConstraint("source_id", "account_id", name="uq_income_source_accounts_account"),
        sa.CheckConstraint("position BETWEEN 0 AND 3", name="ck_income_source_accounts_position"),
    )


def _keep_todays_order(conn) -> None:
    """Each list keeps the order it is shown in today: the default first, then by age."""
    for table, order in (
        ("accounts", "is_default DESC, id"),
        ("income_sources", "is_default DESC, id"),
        ("templates", "id"),
    ):
        ids = [r[0] for r in conn.execute(sa.text(f"SELECT id FROM {table} ORDER BY {order}"))]
        for position, row_id in enumerate(ids):
            conn.execute(
                sa.text(f"UPDATE {table} SET position = :p WHERE id = :i"),
                {"p": position, "i": row_id},
            )


def _source_chains(conn) -> None:
    """ "Paid from", then "Paid into": once if they are the same, never an archived account."""
    usable = {r[0] for r in conn.execute(sa.text("SELECT id FROM accounts WHERE NOT archived"))}
    rows = conn.execute(
        sa.text(
            "SELECT id, default_from_account_id, default_account_id FROM income_sources ORDER BY id"
        )
    ).all()
    for source_id, paid_from, paid_into in rows:
        chain: list[int] = []
        for account_id in (paid_from, paid_into):
            if account_id in usable and account_id not in chain:
                chain.append(account_id)
        for position, account_id in enumerate(chain):
            conn.execute(
                _chain.insert().values(
                    source_id=source_id, position=position, account_id=account_id
                )
            )


class _MadeAccounts:
    """The accounts this migration makes, one per currency, and only when a leg needs one."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.currency_of: dict[int, str] = {
            r[0]: r[1] for r in conn.execute(sa.text("SELECT id, currency FROM accounts"))
        }
        # The app tells two names apart without looking at their case; so does this.
        self.names = {r[0].casefold() for r in conn.execute(sa.text("SELECT name FROM accounts"))}
        self.position = conn.execute(
            sa.text("SELECT COALESCE(MAX(position), -1) FROM accounts")
        ).scalar_one()
        self.made: dict[str, list[int]] = {}
        self.now = datetime.now(UTC).replace(tzinfo=None)

    def _make(self, currency: str) -> int:
        base, n = f"{currency} account", 1
        name = base
        while name.casefold() in self.names:
            n += 1
            name = f"{base} {n}"
        self.names.add(name.casefold())
        self.position += 1
        new_id = self.conn.execute(
            _accounts.insert().values(
                name=name,
                currency=currency,
                kind="other",
                is_default=False,
                archived=False,
                role="both",
                created_at=self.now,
                position=self.position,
            )
        ).inserted_primary_key[0]
        self.currency_of[new_id] = currency
        self.made.setdefault(currency, []).append(new_id)
        return new_id

    def for_side(self, account_id: int | None, currency: str, taken: tuple[int, ...] = ()) -> int:
        """The account of one side of a payout: its own when it has one in that currency and the
        chain does not hold it yet, else a made one of that currency."""
        if (
            account_id is not None
            and self.currency_of.get(account_id) == currency
            and account_id not in taken
        ):
            return account_id
        for made_id in self.made.get(currency, []):
            if made_id not in taken:
                return made_id
        return self._make(currency)


def _payout_legs(conn) -> None:
    """One leg for what arrived; before it, one for what was sent when that was recorded."""
    made = _MadeAccounts(conn)
    rows = conn.execute(
        sa.text(
            "SELECT p.id, p.amount, p.currency, p.account_id,"
            " p.sent_amount, p.sent_currency, p.from_account_id, s.currency"
            " FROM freelance_payouts p LEFT JOIN income_sources s ON s.id = p.source_id"
            " ORDER BY p.id"
        )
    ).all()
    for payout_id, amount, currency, into, sent_amount, sent_currency, sent_from, billed in rows:
        arrived = made.for_side(into, currency)
        legs = [(arrived, amount)]
        if sent_amount is not None:
            # What was sent is in its own currency. A row without one (only a restored backup
            # can hold it) is in its account's, else in the source's: the rule the API saves by.
            sent_in = sent_currency or made.currency_of.get(sent_from) or billed or currency
            legs.insert(0, (made.for_side(sent_from, sent_in, taken=(arrived,)), sent_amount))
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


def downgrade() -> None:
    for table in ("templates", "income_sources", "accounts"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("position")
    op.drop_index("ix_income_source_accounts_account_id", table_name="income_source_accounts")
    op.drop_index("ix_income_source_accounts_source_id", table_name="income_source_accounts")
    op.drop_table("income_source_accounts")
    op.drop_index("ix_freelance_payout_legs_account_id", table_name="freelance_payout_legs")
    op.drop_index("ix_freelance_payout_legs_payout_id", table_name="freelance_payout_legs")
    op.drop_table("freelance_payout_legs")
