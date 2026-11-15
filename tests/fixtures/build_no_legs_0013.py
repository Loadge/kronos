"""Builds ``no_legs_0013.sql``: a database at migration 0013 whose payouts have no legs.

How it was made: the rows below (written by hand, each one a case of the rule that gives a payout
its legs) are put into a database at 0012, which is migrated to 0013; then the legs, the sources'
chains and the accounts that 0013 made are removed, which leaves what a payout saved by the old
request shape after 0013 looks like: a row in the old columns and no leg. The result is dumped.

``python tests/fixtures/build_no_legs_0013.py`` rewrites the file; a test checks that it is what
this script makes. ``ROWS`` is also run through 0013 on its own (from 0012) to see which legs 0013
gives the same rows.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

_AT = "'2026-11-01 10:00:00'"

# Schema 0012. One line each; the comment says what the case is.
ROWS = [
    # accounts: Stripe (USD), Main bank (EUR, default), Wise (EUR), Old pot (EUR, archived)
    f"INSERT INTO accounts (id, name, currency, kind, is_default, archived, role, created_at)"
    f" VALUES (1, 'Stripe', 'USD', 'bank', 0, 0, 'origin', {_AT}),"
    f" (2, 'Main bank', 'EUR', 'bank', 1, 0, 'destination', {_AT}),"
    f" (3, 'Wise', 'EUR', 'bank', 0, 0, 'both', {_AT}),"
    f" (4, 'Old pot', 'EUR', 'bank', 0, 1, 'both', {_AT})",
    # sources: both defaults / only "into" / the same account twice / an archived default / none
    "INSERT INTO income_sources (id, name, hourly_rate, currency, is_default, archived,"
    " default_account_id, default_from_account_id) VALUES"
    " (1, 'Northwind', 90, 'USD', 1, 0, 2, 1),"
    " (2, 'Local', 60, 'EUR', 0, 0, 3, NULL),"
    " (3, 'Same', 60, 'EUR', 0, 0, 3, 3),"
    " (4, 'Shelved', 50, 'USD', 0, 0, 4, NULL),"
    " (5, 'Plain', 40, 'EUR', 0, 0, NULL, NULL)",
    # payouts: id, source, week, amount, currency, fx_rate, rate_source, account, sent amount,
    # sent currency, from account
    "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency, fx_rate, note,"
    " account_id, rate_source, rate_date, sent_amount, sent_currency, from_account_id) VALUES"
    # 1: dollars, no account at all
    " (1, 1, '2026-10-05', 1900, 'USD', 1.1165, 'no account', NULL, 'manual', '2026-10-11',"
    " NULL, NULL, NULL),"
    # 2: euros into Main bank, sent as a bare currency
    " (2, 1, '2026-10-12', 894.76, 'EUR', NULL, NULL, 2, NULL, '2026-10-18', 999, 'USD', NULL),"
    # 3: sent from and arrived in the same account
    " (3, 2, '2026-10-12', 900, 'EUR', NULL, NULL, 3, NULL, '2026-10-18', 900, 'EUR', 3),"
    # 4: both accounts
    " (4, 1, '2026-10-19', 894.76, 'EUR', NULL, NULL, 2, NULL, '2026-10-25', 999, 'USD', 1),"
    # 5: euros, no account at all
    " (5, 2, '2026-10-19', 450, 'EUR', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),"
    # 6: euros into an account, nothing sent
    " (6, 5, '2026-10-26', 300, 'EUR', NULL, NULL, 3, NULL, '2026-11-01', NULL, NULL, NULL),"
    # 7: dollars into a euro account (no version writes this: the payout's currency wins)
    " (7, 1, '2026-11-02', 1000, 'USD', NULL, NULL, 2, NULL, NULL, NULL, NULL, NULL),"
    # 8: a sent amount with no currency and no account: the source's currency
    " (8, 1, '2026-11-09', 880, 'EUR', NULL, NULL, 2, NULL, '2026-11-15', 990, NULL, NULL)",
]


def _alembic(db: Path, revision: str):
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    sys.path.insert(0, str(REPO / "backend"))
    import os

    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
    # the app's config reads the environment once, so run it in a child when it matters
    command.upgrade(cfg, revision)


def rows_at_0012(conn: sqlite3.Connection) -> None:
    for sql in ROWS:
        conn.execute(sql)
    conn.commit()


def build(tmp: Path) -> str:
    db = tmp / "no_legs.db"
    _alembic(db, "0012")
    conn = sqlite3.connect(db)
    rows_at_0012(conn)
    conn.close()
    _alembic(db, "0013")
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM freelance_payout_legs")
    conn.execute("DELETE FROM income_source_accounts")
    conn.execute("DELETE FROM accounts WHERE id > 4")  # the ones 0013 made
    conn.commit()
    dump = "\n".join(conn.iterdump()) + "\n"
    conn.close()
    return dump


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        text = build(Path(tmp))
    if "--check" in sys.argv:  # what the file should hold, to compare with what it holds
        sys.stdout.write("CHECK-BEGIN\n" + text)
    else:
        (HERE / "no_legs_0013.sql").write_text(text, "utf-8", newline="\n")
        print(f"no_legs_0013.sql: {len(text.splitlines())} lines")
