"""Backup fidelity: a backup restored into an empty Kronos must back up identically.

The single strongest guard for the portability promise. Every field that rides in the
file (entries with breaks and partial-day fractions, planner drafts with notes, the
target timeline, the profile, the freelance sources / blocks / tax years and the
projection settings) is exercised, so a field added to the model but forgotten in backup
*or* restore fails here.
"""

from __future__ import annotations


def _populate(client):
    client.put(
        "/api/config/daily-target-schedule",
        json={
            "rows": [
                {"effective_from": "2025-01-01", "hours": 8},
                {"effective_from": "2026-06-01", "hours": 6.5},
            ]
        },
    )
    client.put(
        "/api/config",
        json={
            "cumulative_start_date": "2025-01-01",
            "vacation_budget_days": 22.5,
            "profile_name": "Juan Pérez",
            "profile_employer": "ACME",
            "profile_extra": "nº 4711",
        },
    )
    client.post(
        "/api/entries",
        json={
            "date": "2026-03-02",
            "day_type": "work",
            "start_time": "08:45",
            "end_time": "18:15",
            "notes": "two breaks, one timed",
            "breaks": [{"break_minutes": 45}, {"start_time": "16:00", "end_time": "16:20"}],
        },
    )
    client.post(
        "/api/entries", json={"date": "2026-03-03", "day_type": "holiday", "notes": "fiesta"}
    )
    client.post(
        "/api/entries",
        json={
            "date": "2026-03-04",
            "day_type": "vacation",
            "fraction": 0.375,
            "start_time": "09:00",
            "end_time": "14:00",
        },
    )
    client.post("/api/entries", json={"date": "2026-03-05", "day_type": "flex", "fraction": 0.5})
    client.post(
        "/api/plans",
        json={"dates": ["2026-12-21", "2026-12-22"], "day_type": "vacation", "notes": "Christmas"},
    )
    client.post("/api/plans", json={"dates": ["2026-11-13"], "day_type": "flex", "fraction": 0.5})
    # Freelance: a USD source (default) and an archived EUR one, blocks on both — one with
    # times, one by hours, one with a hand-set rate and exchange rate — and two tax years.
    usd = client.post(
        "/api/freelance/sources",
        json={"name": "Northwind", "hourly_rate": 95, "currency": "USD", "is_default": True},
    ).json()["id"]
    eur = client.post(
        "/api/freelance/sources", json={"name": "Old client", "hourly_rate": 60}
    ).json()["id"]
    client.post(
        "/api/freelance/blocks",
        json={
            "date": "2026-03-02",
            "source_id": usd,
            "start_time": "18:00",
            "end_time": "20:30",
            "fx_rate": 1.1172,
            "notes": "API review",
        },
    )
    client.post(
        "/api/freelance/blocks",
        json={"date": "2026-03-02", "source_id": eur, "hours": 1.25, "rate": 75},
    )
    client.post(
        "/api/freelance/blocks",
        json={"date": "2026-03-07", "source_id": usd, "hours": 3, "fx_rate": 1.12},
    )
    # Payouts: one USD with a hand-set rate and a note, one EUR.
    client.post(
        "/api/freelance/payouts",
        json={
            "source_id": usd,
            "week_start": "2026-03-02",
            "amount": 1200,
            "fx_rate": 1.12,
            "note": "March, week 1",
        },
    )
    client.post(
        "/api/freelance/payouts",
        json={"source_id": eur, "week_start": "2026-03-09", "amount": 450.5},
    )
    client.put(f"/api/freelance/sources/{eur}", json={"archived": True})
    client.put(
        "/api/freelance/tax-years/2026",
        json={
            "year": 2026,
            "salary_annual": 55000,
            "tarifa_plana": False,
            "inicio_actividad": True,
            "set_aside_share": 0.35,
            "gestoria_annual": 600,
            "other_expenses": 120,
        },
    )
    client.put(
        "/api/freelance/tax-years/2027",
        json={"year": 2027, "salary_annual": 58000, "tarifa_plana": True},
    )
    client.put("/api/config", json={"freelance_hours_per_week": 6, "freelance_days_off": 5})


def _wipe_everything(client):
    client.delete("/api/data")
    for s in client.get("/api/freelance/sources").json():
        client.delete(f"/api/freelance/sources/{s['id']}")
    for a in client.get("/api/freelance/accounts").json():
        client.delete(f"/api/freelance/accounts/{a['id']}")
    for t in client.get("/api/freelance/tax-years").json():
        client.delete(f"/api/freelance/tax-years/{t['year']}")
    client.put("/api/config", json={"freelance_hours_per_week": 0, "freelance_days_off": 0})
    client.put(
        "/api/config/daily-target-schedule",
        json={"rows": [{"effective_from": "2020-01-01", "hours": 7}]},
    )
    client.put(
        "/api/config",
        json={
            "cumulative_start_date": "2020-01-01",
            "vacation_budget_days": 0,
            "profile_name": "",
            "profile_employer": "",
            "profile_extra": "",
        },
    )


def _strip(backup):
    return {k: v for k, v in backup.items() if k != "exported_at"}


class TestBreakTimesSurvive:
    """Found while writing the identity test: the file used to carry only the minutes."""

    def test_timed_break_restores_with_its_range(self, client):
        _populate(client)
        backup = client.get("/api/backup").json()
        timed = backup["entries"][0]["breaks"][1]
        assert (timed["start_time"], timed["end_time"], timed["break_minutes"]) == (
            "16:00",
            "16:20",
            20,
        )
        _wipe_everything(client)
        client.post("/api/restore", json=backup)
        breaks = client.get("/api/entries/2026-03-02").json()["breaks"]
        assert [(b["start_time"], b["end_time"], b["break_minutes"]) for b in breaks] == [
            (None, None, 45),
            ("16:00", "16:20", 20),
        ]

    def test_old_file_with_minutes_only_still_restores(self, client):
        old = {
            "version": 1,
            "entries": [
                {
                    "date": "2026-03-02",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 30}],
                }
            ],
        }
        assert client.post("/api/restore", json=old).status_code == 200
        (b,) = client.get("/api/entries/2026-03-02").json()["breaks"]
        assert (b["break_minutes"], b["start_time"]) == (30, None)


class TestBackupRoundTripIsIdentity:
    def test_backup_restore_backup_is_identical(self, client):
        _populate(client)
        first = client.get("/api/backup").json()
        assert first["version"] == 4
        assert len(first["entries"]) == 4 and len(first["plans"]) == 3
        assert len(first["income_sources"]) == 2 and len(first["freelance_blocks"]) == 3
        assert len(first["freelance_tax_years"]) == 2
        assert len(first["freelance_payouts"]) == 2

        _wipe_everything(client)
        assert client.get("/api/entries").json() == []
        assert client.get("/api/plans").json() == []
        assert client.get("/api/freelance/sources").json() == []
        assert client.get("/api/freelance/blocks").json() == []
        assert client.get("/api/freelance/payouts").json() == []
        assert client.get("/api/freelance/tax-years").json() == []
        assert client.get("/api/config").json()["profile_name"] == ""

        assert client.post("/api/restore", json=first).status_code == 200
        second = client.get("/api/backup").json()
        assert _strip(second) == _strip(first)
        # The blocks found their sources again, with the rates they were saved with.
        blocks = client.get("/api/freelance/blocks").json()
        assert [(b["source_name"], b["rate"], b["currency"], b["fx_rate"]) for b in blocks] == [
            ("Northwind", 95.0, "USD", 1.1172),
            ("Old client", 75.0, "EUR", None),
            ("Northwind", 95.0, "USD", 1.12),
        ]
        # The payouts found their sources again, with the currency and rate they had.
        payouts = client.get("/api/freelance/payouts").json()
        assert [
            (p["source_id"], p["week_start"], p["amount"], p["currency"], p["fx_rate"], p["note"])
            for p in payouts
        ] == [
            (1, "2026-03-02", 1200.0, "USD", 1.12, "March, week 1"),
            (2, "2026-03-09", 450.5, "EUR", None, None),
        ]

    def test_restore_is_idempotent(self, client):
        _populate(client)
        first = client.get("/api/backup").json()
        client.post("/api/restore", json=first)
        client.post("/api/restore", json=first)
        assert _strip(client.get("/api/backup").json()) == _strip(first)
        assert len(client.get("/api/entries").json()) == 4

    def test_every_documented_field_is_in_the_file(self, client):
        """If a new field lands on an entry / plan / setting, it must show up here too."""
        _populate(client)
        backup = client.get("/api/backup").json()
        assert set(backup) == {
            "version",
            "exported_at",
            "settings",
            "entries",
            "plans",
            "accounts",
            "income_sources",
            "freelance_blocks",
            "freelance_tax_years",
            "freelance_payouts",
        }
        assert set(backup["entries"][0]) == {
            "date",
            "day_type",
            "fraction",
            "start_time",
            "end_time",
            "notes",
            "breaks",
        }
        assert set(backup["entries"][0]["breaks"][0]) == {"break_minutes", "start_time", "end_time"}
        assert set(backup["plans"][0]) == {"date", "day_type", "fraction", "notes"}
        assert {
            "daily_target_hours",
            "daily_target_schedule",
            "cumulative_start_date",
            "profile_name",
            "profile_employer",
            "profile_extra",
            "freelance_hours_per_week",
            "freelance_days_off",
        } <= set(backup["settings"])
        assert set(backup["income_sources"][0]) == {
            "id",
            "name",
            "hourly_rate",
            "currency",
            "is_default",
            "archived",
            "default_account_id",
        }
        assert set(backup["freelance_blocks"][0]) == {
            "date",
            "source_id",
            "minutes",
            "start_time",
            "end_time",
            "notes",
            "rate",
            "currency",
            "fx_rate",
        }
        assert set(backup["freelance_payouts"][0]) == {
            "source_id",
            "week_start",
            "amount",
            "currency",
            "fx_rate",
            "note",
            "account_id",
            "rate_source",
            "rate_date",
        }
        assert set(backup["freelance_tax_years"][0]) == {
            "year",
            "salary_annual",
            "tarifa_plana",
            "inicio_actividad",
            "set_aside_share",
            "gestoria_annual",
            "other_expenses",
        }

    def test_a_version_2_file_leaves_the_freelance_side_alone(self, client):
        """An older file knows nothing of sources or blocks: restoring it must not wipe them."""
        _populate(client)
        old = client.get("/api/backup").json()
        for key in (
            "income_sources",
            "freelance_blocks",
            "freelance_tax_years",
            "freelance_payouts",
        ):
            del old[key]
        old["version"] = 2
        assert client.post("/api/restore", json=old).status_code == 200
        assert len(client.get("/api/freelance/sources").json()) == 2
        assert len(client.get("/api/freelance/tax-years").json()) == 2
        assert client.get("/api/freelance/blocks").json() == []  # blocks are data: wiped


def _populate_accounts(client, monkeypatch):
    """Two accounts and three payouts into them with every new field set, no network."""
    monkeypatch.setenv("KRONOS_FX_URL", "")
    monkeypatch.setenv("KRONOS_CRYPTO_URL", "")
    bank = client.post(
        "/api/freelance/accounts",
        json={"name": "Deutsche Bank", "currency": "EUR", "kind": "bank", "is_default": True},
    ).json()["id"]
    wallet = client.post(
        "/api/freelance/accounts",
        json={"name": "Cold wallet", "currency": "BTC", "kind": "wallet"},
    ).json()["id"]
    usd = client.post(
        "/api/freelance/sources",
        json={
            "name": "Northwind",
            "hourly_rate": 95,
            "currency": "USD",
            "is_default": True,
            "default_account_id": bank,
        },
    ).json()["id"]
    client.post(
        "/api/freelance/blocks",
        json={"date": "2026-10-27", "source_id": usd, "hours": 4, "fx_rate": 1.1172},
    )
    for week, body in (
        ("2026-10-26", {"account_id": bank, "amount": 877.94, "paid_on": "2026-11-02"}),
        ("2026-11-02", {"account_id": wallet, "amount": 0.01234567, "eur_amount": 700.5}),
        ("2026-11-09", {"account_id": bank, "amount": 100.0, "note": "late"}),
    ):
        r = client.post(
            "/api/freelance/payouts", json={"source_id": usd, "week_start": week, **body}
        )
        assert r.status_code == 201, r.text
    return bank, wallet


class TestAccountsSurviveTheRoundTrip:
    def test_backup_restore_backup_is_identical_with_accounts(self, client, monkeypatch):
        bank, wallet = _populate_accounts(client, monkeypatch)
        first = client.get("/api/backup").json()
        assert [a["name"] for a in first["accounts"]] == ["Deutsche Bank", "Cold wallet"]
        assert set(first["accounts"][0]) == {
            "id",
            "name",
            "currency",
            "kind",
            "is_default",
            "archived",
            "created_at",
        }
        assert first["income_sources"][0]["default_account_id"] == bank
        p0, p1, p2 = first["freelance_payouts"]
        assert (p0["account_id"], p0["currency"], p0["rate_date"]) == (bank, "EUR", "2026-11-02")
        assert (p1["account_id"], p1["currency"], p1["rate_source"]) == (wallet, "BTC", "manual")
        assert p1["rate_date"] == "2026-11-08"  # the week's Sunday: no paid_on was given
        assert p1["amount"] == 0.01234567 and p1["fx_rate"] == 0.01234567 / 700.5
        assert p2["note"] == "late"

        _wipe_everything(client)
        assert client.get("/api/freelance/accounts").json() == []
        assert client.post("/api/restore", json=first).status_code == 200
        second = client.get("/api/backup").json()
        assert _strip(second) == _strip(first)
        payouts = client.get("/api/freelance/payouts").json()
        assert [(p["account_name"], p["currency"], p["amount_eur"]) for p in payouts] == [
            ("Deutsche Bank", "EUR", 877.94),
            ("Cold wallet", "BTC", 700.5),
            ("Deutsche Bank", "EUR", 100.0),
        ]

    def test_a_file_from_before_accounts_restores_every_payout_as_it_was(self, client, monkeypatch):
        """No accounts key, none of the new fields: the payouts come back in the source's
        currency, none lost, and the accounts that exist are left alone."""
        monkeypatch.setenv("KRONOS_FX_URL", "")
        _populate(client)
        before = client.get("/api/freelance/payouts").json()
        old = client.get("/api/backup").json()
        del old["accounts"]
        for s in old["income_sources"]:
            del s["default_account_id"]
        for p in old["freelance_payouts"]:
            for k in ("account_id", "rate_source", "rate_date"):
                del p[k]
        client.post("/api/freelance/accounts", json={"name": "Kept", "currency": "EUR"})
        assert client.delete("/api/data").status_code == 200  # payouts gone; accounts stay
        assert client.post("/api/restore", json=old).status_code == 200
        after = client.get("/api/freelance/payouts").json()
        assert len(after) == len(before) == 2
        assert [(p["amount"], p["currency"], p["fx_rate"], p["amount_eur"]) for p in after] == [
            (p["amount"], p["currency"], p["fx_rate"], p["amount_eur"]) for p in before
        ]
        assert all(p["account_id"] is None for p in after)
        assert [a["name"] for a in client.get("/api/freelance/accounts").json()] == ["Kept"]
