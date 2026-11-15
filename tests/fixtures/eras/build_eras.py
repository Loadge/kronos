"""Builds the era fixtures: databases written by the code of three past versions of Kronos.

A migration that touches money is proven on rows the old code really wrote, not on rows a test
imagines. This script runs each old version from a git worktree against one database file, in
order, through its own API:

    v51  payouts before accounts (schema 0010)
    v56  accounts and the rate's provenance (schema 0011)
    v57  what was sent and what arrived (schema 0012)

After v56 and after v57 it keeps the database as SQL (``v56.sql``, ``v57.sql``), what that
version's API answered about it (``v56.json``, ``v57.json``) and the backup that version handed
out (``v56.backup.json``, ``v57.backup.json``). The data is made up; the rates come
from ``ecb.xml``, written here too, and no request leaves the machine.

Run it by hand, only to rebuild the fixtures (the tests never run it):

    git worktree add --detach <dir>/v51 0bbaace^
    git worktree add --detach <dir>/v56 bce7201
    git worktree add --detach <dir>/v57 f356a6d
    python tests/fixtures/eras/build_eras.py <dir>
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = "2026-11-11"
YEAR = 2026
COIN_EUR = {"bitcoin": 81000.0, "usd-coin": 0.92}

# USD per EUR, by the month a day is in: the ECB publishes one rate per working day.
_USD = {2: 1.0850, 3: 1.0850, 4: 1.0950, 5: 1.0950, 6: 1.1020, 7: 1.1020}
_USD |= {8: 1.1100, 9: 1.1100, 10: 1.1140, 11: 1.1165}


def ecb_xml(first: date = date(2026, 2, 2)) -> str:
    """Every working day from ``first`` to 2026-11-06, the newest first as the ECB does. The
    ECB's daily document holds one day only, its history all of them: a stub that answered the
    history for both would make "today's rate" the oldest day, and a figure read through it
    would depend on the day the code runs."""
    day, cubes = date(2026, 11, 6), []
    while day >= first:
        if day.weekday() < 5:
            cubes.append(
                f'<Cube time="{day.isoformat()}"><Cube currency="USD" rate="{_USD[day.month]}"/>'
                "</Cube>"
            )
        day -= timedelta(days=1)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"'
        ' xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">\n'
        "<Cube>\n" + "\n".join(cubes) + "\n</Cube>\n</gesmes:Envelope>\n"
    )


# ---------- the child: one old version, in its own process --------------------------------


class Api:
    def __init__(self, client) -> None:
        self.c = client

    def call(self, method: str, path: str, body: dict | None = None, ok=(200, 201, 204)):
        r = self.c.request(method, path, json=body)
        if r.status_code not in ok:
            raise SystemExit(f"{method} {path} {body} -> {r.status_code} {r.text}")
        return r.json() if r.content else None

    def ids(self, what: str) -> dict[str, int]:
        return {row["name"]: row["id"] for row in self.call("GET", f"/api/freelance/{what}")}

    def source(self, name: str, rate: float, currency: str, **kw) -> None:
        body = {"name": name, "hourly_rate": rate, "currency": currency, **kw}
        self.call("POST", "/api/freelance/sources", body)

    def account(self, name: str, currency: str, **kw) -> None:
        self.call("POST", "/api/freelance/accounts", {"name": name, "currency": currency, **kw})

    def block(self, source: str, day: str, hours: float) -> None:
        body = {"date": day, "source_id": self.ids("sources")[source], "hours": hours}
        self.call("POST", "/api/freelance/blocks", body)

    def payout(self, source: str, week: str, amount: float, **kw) -> None:
        body = {"source_id": self.ids("sources")[source], "week_start": week, "amount": amount}
        self.call("POST", "/api/freelance/payouts", {**body, **kw})


def v51(api: Api) -> None:
    """Before accounts: a payout is an amount in its source's currency."""
    api.source("Northwind Labs", 90, "USD", is_default=True)
    api.source("Local consulting", 60, "EUR")
    api.source("Old client", 75, "USD")
    for name, start, end in (("Office day", "09:00", "17:30"), ("Short Friday", "08:00", "14:00")):
        body = {"name": name, "start_time": start, "end_time": end, "breaks": []}
        api.call("POST", "/api/templates", body)
    api.block("Old client", "2026-01-06", 10)  # before the first rate the ECB document has
    api.block("Northwind Labs", "2026-03-03", 20)
    api.block("Local consulting", "2026-03-04", 8)
    api.block("Northwind Labs", "2026-03-10", 22.5)
    api.block("Old client", "2026-03-11", 10)
    api.payout("Old client", "2026-01-05", 750)  # no rate to be had: saved without one
    api.payout("Northwind Labs", "2026-03-02", 1800)  # the ECB's rate
    api.payout("Local consulting", "2026-03-02", 480)  # euros
    api.payout("Northwind Labs", "2026-03-09", 2000, fx_rate=1.09, note="rate typed by hand")
    api.payout("Old client", "2026-03-09", 700)


def v56(api: Api) -> None:
    """Accounts: a payout may land in one, in the account's currency."""
    api.account("Main bank", "EUR", is_default=True)
    api.account("Dollar account", "USD")
    api.account("Cold wallet", "BTC", kind="wallet")
    api.account("Closed bank", "EUR")
    acc, src = api.ids("accounts"), api.ids("sources")
    put = "/api/freelance/sources/"
    api.call("PUT", put + str(src["Northwind Labs"]), {"default_account_id": acc["Main bank"]})
    api.call("PUT", put + str(src["Old client"]), {"default_account_id": acc["Closed bank"]})
    for source, day, hours in (
        ("Northwind Labs", "2026-06-02", 20),
        ("Northwind Labs", "2026-06-09", 21),
        ("Northwind Labs", "2026-06-16", 19),
        ("Northwind Labs", "2026-06-23", 20),
        ("Local consulting", "2026-06-03", 10),
        ("Local consulting", "2026-06-10", 12),
        ("Old client", "2026-06-04", 8),
    ):
        api.block(source, day, hours)
    api.payout("Northwind Labs", "2026-06-01", 1650, account_id=acc["Main bank"])
    api.payout("Northwind Labs", "2026-06-08", 1900, account_id=acc["Dollar account"])
    api.payout(
        "Northwind Labs", "2026-06-15", 0.021, account_id=acc["Cold wallet"], eur_amount=1700
    )
    api.payout("Northwind Labs", "2026-06-22", 0.022, account_id=acc["Cold wallet"])
    api.payout("Local consulting", "2026-06-01", 600)  # still without an account
    api.payout(
        "Local consulting", "2026-06-08", 700, account_id=acc["Dollar account"], fx_rate=1.10
    )
    api.payout("Old client", "2026-06-01", 500, account_id=acc["Closed bank"])
    api.call("PUT", f"/api/freelance/accounts/{acc['Closed bank']}", {"archived": True})
    api.call("PUT", put + str(src["Old client"]), {"archived": True})


def v57(api: Api) -> None:
    """Sent and arrived: a payout may say what was sent, from an account or in a bare currency."""
    api.account("Stripe", "USD", role="origin")
    api.account("Wise", "EUR")
    acc, src = api.ids("accounts"), api.ids("sources")
    api.call("PUT", f"/api/freelance/accounts/{acc['Main bank']}", {"role": "destination"})
    put = "/api/freelance/sources/"
    api.call("PUT", put + str(src["Northwind Labs"]), {"default_from_account_id": acc["Stripe"]})
    api.call(
        "PUT",
        put + str(src["Local consulting"]),
        {"default_from_account_id": acc["Wise"], "default_account_id": acc["Wise"]},
    )
    for source, day, hours in (
        ("Northwind Labs", "2026-10-13", 18),
        ("Northwind Labs", "2026-10-20", 20),
        ("Northwind Labs", "2026-10-27", 16),
        ("Northwind Labs", "2026-11-03", 22.55),
        ("Local consulting", "2026-10-28", 6),
        ("Local consulting", "2026-11-04", 9),
    ):
        api.block(source, day, hours)
    main, dollar = acc["Main bank"], acc["Dollar account"]
    api.payout(
        "Northwind Labs",
        "2026-11-02",
        894.76,
        account_id=main,
        sent_amount=999,
        from_account_id=acc["Stripe"],
    )
    api.payout(
        "Northwind Labs",
        "2026-10-26",
        1480,
        account_id=dollar,
        sent_amount=1500,
        sent_currency="USD",
    )
    api.payout(
        "Northwind Labs",
        "2026-10-19",
        1190,
        account_id=dollar,
        sent_amount=1200,
        from_account_id=dollar,
    )
    api.payout("Northwind Labs", "2026-10-12", 1500, account_id=main)  # as billed
    api.payout("Local consulting", "2026-11-02", 495, sent_amount=500)  # no account either side
    api.payout("Local consulting", "2026-10-26", 300, sent_amount=300, from_account_id=acc["Wise"])


def child(era: str, tree: Path, db: Path, out: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
    os.environ["KRONOS_FX_URL"] = "https://fx.example.invalid/daily.xml"
    os.environ["KRONOS_FX_HIST90_URL"] = "https://fx.example.invalid/90d.xml"
    os.environ["KRONOS_FX_HIST_URL"] = "https://fx.example.invalid/all.xml"
    os.environ["KRONOS_CRYPTO_URL"] = "https://crypto.example.invalid"
    sys.path.insert(0, str(tree / "backend"))

    from alembic.config import Config

    from alembic import command

    cfg = Config(str(tree / "alembic.ini"))
    cfg.set_main_option("script_location", str(tree / "alembic"))
    command.upgrade(cfg, "head")

    import app.services.fx as fx

    history = (HERE / "ecb.xml").read_bytes()
    daily = (HERE / "ecb_daily.xml").read_bytes()
    fx._fetch = lambda url, timeout=3: daily if url.endswith("daily.xml") else history
    try:
        import app.services.crypto as crypto
    except ImportError:  # v51 knows no coins
        pass
    else:

        def coin(url: str, timeout: float = 5) -> bytes:
            name = next(n for n in COIN_EUR if f"/{n}/" in url or f"ids={n}" in url)
            if "/history" in url:
                return json.dumps(
                    {"market_data": {"current_price": {"eur": COIN_EUR[name]}}}
                ).encode()
            return json.dumps({name: {"eur": COIN_EUR[name]}}).encode()

        crypto._fetch = coin

    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        api = Api(client)
        {"v51": v51, "v56": v56, "v57": v57}[era](api)
        answers = {
            "sources": api.call("GET", "/api/freelance/sources"),
            "payouts": api.call("GET", "/api/freelance/payouts"),
            "summary": api.call("GET", f"/api/freelance/summary?year={YEAR}&today={TODAY}"),
            "payouts_csv": client.get("/api/freelance/payouts.csv").text,
        }
        if era != "v51":
            answers["accounts"] = api.call("GET", "/api/freelance/accounts")
        backup = api.call("GET", "/api/backup")
    out.write_text(json.dumps(answers, indent=1, sort_keys=True) + "\n", "utf-8", newline="\n")
    # The backup that version would have handed out: what a restore must still read.
    out.with_suffix(".backup.json").write_text(
        json.dumps(backup, indent=1, sort_keys=True) + "\n", "utf-8", newline="\n"
    )


# ---------- the parent --------------------------------------------------------------------


def main(trees: Path) -> None:
    (HERE / "ecb.xml").write_text(ecb_xml(), "utf-8", newline="\n")
    (HERE / "ecb_daily.xml").write_text(ecb_xml(date(2026, 11, 6)), "utf-8", newline="\n")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "eras.db"
        for era in ("v51", "v56", "v57"):
            out = Path(tmp) / f"{era}.json"
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__)),
                    "child",
                    era,
                    str(trees / era),
                    str(db),
                    str(out),
                ],
                check=True,
                cwd=tmp,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            if era == "v51":
                continue
            conn = sqlite3.connect(db)
            dump = "\n".join(conn.iterdump()) + "\n"
            conn.close()
            (HERE / f"{era}.sql").write_text(dump, "utf-8", newline="\n")
            (HERE / f"{era}.json").write_text(out.read_text("utf-8"), "utf-8", newline="\n")
            (HERE / f"{era}.backup.json").write_text(
                out.with_suffix(".backup.json").read_text("utf-8"), "utf-8", newline="\n"
            )
            print(f"{era}: {len(dump.splitlines())} lines of SQL")


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "child":
        child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    elif len(sys.argv) == 2:
        main(Path(sys.argv[1]).resolve())
    else:
        raise SystemExit(__doc__)
