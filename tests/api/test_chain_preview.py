# ruff: noqa: E501
"""POST /api/freelance/payouts/preview: a payout's row worked out, never saved.

The preview runs the code of the save, so what the user sees before Confirm is to the cent what
Confirm saves. Same world as test_chain_api.py (Miguel's week: 22.55 h at $90 = $2,029.50, the
ECB at 1.1165 USD per EUR, stubbed: nothing leaves the process and nothing depends on the day).
Every expected figure below is typed by hand from the rule: a rate times an amount, rounded to the
cent.
"""

from __future__ import annotations

import app.services.fx as fx
import pytest
from app.database import Base
from sqlalchemy import text

from .test_chain_api import (  # noqa: F401  (_stubs is an autouse fixture)
    _DAYS,
    RATE,
    W2,
    W44,
    W45,
    L,
    _account,
    _amounts,
    _block,
    _chain_payout,
    _fixed,
    _payout,
    _put,
    _stubs,
    _world,
)
from .test_chain_api import dclient as _dclient

dclient = _dclient  # the engine with foreign keys off and on, as a fixture of this module

PREVIEW = "/api/freelance/payouts/preview"


def _post(client, w, *legs, week=W45, **kw):
    body = {"source_id": w["src"], "week_start": week, "legs": list(legs), **kw}
    return client.post(PREVIEW, json=body)


def _preview(client, w, *legs, week=W45, **kw) -> dict:
    r = _post(client, w, *legs, week=week, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def _problems(out) -> list[str | None]:
    return [leg["problem"] for leg in out["legs"]]


def _tables(engine) -> dict[str, list[tuple]]:
    """Every row of every table, to compare before and after."""
    rows: dict[str, list[tuple]] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            found = conn.execute(text(f"SELECT * FROM {table.name} ORDER BY 1"))
            rows[table.name] = [tuple(r) for r in found]
    return rows


def _no_totals(out) -> None:
    assert out["amount"] is None and out["amount_eur"] is None
    assert out["fx_cost_eur"] is None and out["effective_rate"] is None


# ── Miguel's week ─────────────────────────────────────────────────────────────


class TestMiguelsWeek:
    def test_a_typed_dollar_leg_and_a_euro_one_worked_out(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        assert _amounts(out) == [999.0, 894.76] and _fixed(out) == [True, False]
        assert _problems(out) == [None, None]
        assert [leg["account_name"] for leg in out["legs"]] == ["Stripe", "Main bank"]
        assert (out["amount"], out["currency"], out["amount_eur"]) == (894.76, "EUR", 894.76)
        assert (out["gap"], out["gap_currency"]) == (-1030.5, "USD")
        assert out["id"] is None

    def test_nothing_typed_follows_what_the_week_billed(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"]), L(w["bank"]))
        assert _amounts(out) == [2029.5, 1817.73] and _fixed(out) == [False, False]
        assert out["gap"] == 0.0 and out["amount"] == 1817.73
        assert (out["blocks"], out["minutes"], out["billed_amount"]) == (1, 1353, 2029.5)

    def test_a_leg_with_an_amount_is_never_a_problem(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"], 999, True), L(w["bank"], 894.76, False))
        assert _amounts(out) == [999.0, 894.76] and _fixed(out) == [True, False]
        assert _problems(out) == [None, None]


class TestThreeAccounts:
    def test_typing_the_second_changes_the_third_and_not_the_first(self, client):
        w = _world(client)
        legs = [L(w["stripe"], 999, True), L(w["wise"]), L(w["bank"])]
        assert _amounts(_preview(client, w, *legs)) == [999.0, 894.76, 894.76]
        legs[1] = L(w["wise"], 890, True)
        out = _preview(client, w, *legs)
        assert _amounts(out) == [999.0, 890.0, 890.0] and _fixed(out) == [True, True, False]
        assert out["amount"] == 890.0

    def test_typing_the_first_does_not_change_a_fixed_second(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"], 1000, True), L(w["wise"], 890, True), L(w["bank"]))
        assert _amounts(out) == [1000.0, 890.0, 890.0]
        assert out["gap"] == -1029.5

    def test_a_second_sent_without_amount_is_worked_out_again_from_the_first(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"], 1000, True), L(w["wise"]), L(w["bank"]))
        # 1000 USD at 1.1165 is 895.66 EUR, and the third follows it
        assert _amounts(out) == [1000.0, 895.66, 895.66] and _fixed(out) == [True, False, False]


class TestTheDayOfTheRate:
    def _two_rates(self, monkeypatch):
        """The ECB at 1.1165 up to Friday 2026-11-06 and at 1.2500 on Tuesday 2026-11-10."""

        def document(days):
            cubes = "".join(
                f'<Cube time="{d}"><Cube currency="USD" rate="{r}"/></Cube>' for d, r in days
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"'
                ' xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
                f"<Cube>{cubes}</Cube></gesmes:Envelope>"
            ).encode()

        history = [("2026-11-10", 1.25)] + [(d, RATE) for d in _DAYS]
        newest, everything = document(history[:1]), document(history)

        def fetch(url, timeout=3):
            return newest if url.endswith("daily.xml") else everything

        fx._reset()
        monkeypatch.setattr(fx, "_fetch", fetch)

    def test_paid_on_picks_the_rate_not_the_sunday(self, client, monkeypatch):
        self._two_rates(monkeypatch)
        w = _world(client)
        legs = [L(w["stripe"], 999, True), L(w["bank"])]
        assert _amounts(_preview(client, w, *legs)) == [999.0, 894.76]  # Friday's rate
        out = _preview(client, w, *legs, paid_on="2026-11-10")  # 999 / 1.25
        assert _amounts(out) == [999.0, 799.2] and out["amount"] == 799.2
        out = _preview(client, w, L(w["bank"]), paid_on="2026-11-10")  # 2029.50 / 1.25
        assert _amounts(out) == [1623.6]


# ── what cannot be worked out ─────────────────────────────────────────────────


class TestADayWithoutARate:
    def _week(self, client):
        w = _world(client)
        _block(client, w["src"], day="2026-01-06")  # W2: $2,029.50 billed, no rate that day
        return w

    def test_the_leg_that_needs_it_has_no_amount_and_the_one_after_it_neither(self, client):
        w = self._week(client)
        out = _preview(client, w, L(w["stripe"], 500, True), L(w["bank"]), L(w["wise"]), week=W2)
        assert _amounts(out) == [500.0, None, None]
        assert _problems(out) == [None, "no rate for that day", "needs the account before it"]
        assert _fixed(out) == [True, False, False]
        _no_totals(out)
        assert out["gap"] == -1529.5  # the first leg is known: 500 - 2029.50

    def test_a_first_leg_that_converts_the_billed_dollars(self, client):
        w = self._week(client)
        out = _preview(client, w, L(w["bank"]), week=W2)
        assert _amounts(out) == [None] and _problems(out) == ["no rate for that day"]
        _no_totals(out)
        assert out["gap"] == 0.0  # not typed: it follows what the week billed

    def test_the_save_of_the_same_body_is_a_422(self, client):
        w = self._week(client)
        legs = [L(w["stripe"], 500, True), L(w["bank"])]
        assert _post(client, w, *legs, week=W2).status_code == 200
        r = client.post(
            "/api/freelance/payouts",
            json={"source_id": w["src"], "week_start": W2, "legs": legs},
        )
        assert r.status_code == 422 and "no rate for that day" in r.json()["detail"]

    def test_a_typed_leg_is_fine_on_that_day(self, client):
        w = self._week(client)
        out = _preview(client, w, L(w["stripe"], 500, True), L(w["bank"], 450, True), week=W2)
        assert _amounts(out) == [500.0, 450.0] and _problems(out) == [None, None]
        assert out["amount"] == 450.0


class TestAWeekWithNoBlocks:
    def test_a_first_leg_without_amount_has_nothing_to_follow(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"]), L(w["bank"]), week=W44)
        assert _amounts(out) == [None, None]
        assert _problems(out) == ["nothing billed that week", "needs the account before it"]
        _no_totals(out)
        assert (out["blocks"], out["gap"]) == (0, None)

    def test_one_leg_without_amount(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["bank"]), week=W44)
        assert _amounts(out) == [None] and _problems(out) == ["nothing billed that week"]

    def test_a_typed_first_leg_works(self, client):
        w = _world(client)
        out = _preview(client, w, L(w["stripe"], 100, True), L(w["bank"]), week=W44)
        assert _amounts(out) == [100.0, 89.57] and _problems(out) == [None, None]  # 100 / 1.1165
        assert out["amount"] == 89.57 and out["gap"] is None


# ── what the save refuses outright ────────────────────────────────────────────


class TestWhatIsStillRefused:
    def test_no_legs_and_too_many(self, client):
        w = _world(client)
        extra = [_account(client, f"Extra {i}", "EUR") for i in range(2)]
        r = _post(client, w)
        assert r.status_code == 422 and "1 to 4 accounts" in r.json()["detail"]
        five = [w["stripe"], w["wise"], w["bank"], extra[0], extra[1]]
        r = _post(client, w, *[L(a, 100) for a in five])
        assert r.status_code == 422 and "1 to 4 accounts" in r.json()["detail"]
        assert _post(client, w, *[L(a, 100) for a in five[:4]]).status_code == 200

    def test_an_account_twice_and_an_unknown_one(self, client):
        w = _world(client)
        r = _post(client, w, L(w["bank"], 100), L(w["bank"], 90))
        assert r.status_code == 422 and "only once" in r.json()["detail"]
        r = _post(client, w, L(999, 100))
        assert r.status_code == 422 and r.json()["detail"] == "unknown account"

    def test_an_archived_account_the_payout_does_not_have(self, client):
        w = _world(client)
        client.put(f"/api/freelance/accounts/{w['stripe']}", json={"archived": True})
        r = _post(client, w, L(w["stripe"], 5), L(w["bank"], 4))
        assert r.status_code == 422 and r.json()["detail"] == "that account is archived"

    def test_an_unknown_source_is_what_the_save_says(self, client):
        w = _world(client)
        body = {"source_id": 999, "week_start": W45, "legs": [L(w["bank"], 100)]}
        saved = client.post("/api/freelance/payouts", json=body)
        r = client.post(PREVIEW, json=body)
        assert (r.status_code, r.json()) == (saved.status_code, saved.json())
        assert r.status_code == 404

    def test_a_week_that_is_not_a_monday(self, client):
        w = _world(client)
        r = _post(client, w, L(w["bank"], 100), week="2026-11-03")
        assert r.status_code == 422 and "week_start must be a Monday" in r.text

    def test_a_request_without_legs_names_them(self, client):
        w = _world(client)
        body = {"source_id": w["src"], "week_start": W45, "amount": 100, "account_id": w["bank"]}
        r = client.post(PREVIEW, json=body)
        assert r.status_code == 422 and "legs" in r.text
        r = client.post(PREVIEW, json={"source_id": w["src"], "week_start": W45})
        assert r.status_code == 422 and "legs" in r.text


# ── nothing is written ────────────────────────────────────────────────────────


class TestNothingIsWritten:
    def _bodies(self, w):
        """One preview of every kind above, and the one-leg preview on a source with no chain."""
        stripe, bank, wise = w["stripe"], w["bank"], w["wise"]
        return [
            {"week_start": W45, "legs": [L(stripe, 999, True), L(bank)]},
            {"week_start": W45, "legs": [L(stripe), L(wise), L(bank)]},
            {"week_start": W45, "legs": [L(bank)]},  # one leg, source chain empty
            {"week_start": W45, "legs": [L(bank, 100, True)]},
            {"week_start": W44, "legs": [L(stripe), L(bank)]},  # nothing billed
            {"week_start": W2, "legs": [L(stripe, 500, True), L(bank)]},  # no rate
            {"week_start": W45, "legs": [L(stripe, 999, True), L(bank)], "paid_on": "2026-11-04"},
        ]

    def test_every_table_is_as_it_was(self, dclient):
        client = dclient
        w = _world(client)
        _block(client, w["src"], day="2026-01-06")
        before = _tables(client.engine)
        assert before["income_source_accounts"] == []  # the source has no chain yet
        for body in self._bodies(w):
            r = client.post(PREVIEW, json={"source_id": w["src"], **body})
            assert r.status_code == 200, r.text
            assert _tables(client.engine) == before, body
        # a saved payout is also left as it was by the preview of its change
        saved = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]), week=W44)
        before = _tables(client.engine)
        for legs in (
            [L(w["stripe"], 1000, True), L(w["bank"])],
            [L(w["wise"], 5, True), L(w["mercury"], 6, True), L(w["bank"])],
            [L(w["bank"])],
        ):
            r = client.post(
                PREVIEW,
                json={
                    "source_id": w["src"],
                    "week_start": W45,
                    "legs": legs,
                    "payout_id": saved["id"],
                },
            )
            assert r.status_code == 200, r.text
            assert _tables(client.engine) == before

    def test_the_comparison_can_see_a_real_save(self, dclient):
        """Positive control: the same one-leg body, saved, does change the tables."""
        client = dclient
        w = _world(client)
        before = _tables(client.engine)
        _preview(client, w, L(w["bank"]))
        assert _tables(client.engine) == before
        _chain_payout(client, w, L(w["bank"]))
        after = _tables(client.engine)
        assert after["freelance_payouts"] != before["freelance_payouts"]
        assert after["freelance_payout_legs"] != before["freelance_payout_legs"]
        assert after["income_source_accounts"] != before["income_source_accounts"]


# ── a saved payout being changed ──────────────────────────────────────────────


class TestPayoutId:
    def test_the_new_figures_come_back_and_the_saved_ones_stay(self, client):
        w = _world(client)
        saved = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        assert _amounts(saved) == [999.0, 894.76]
        out = _preview(client, w, L(w["stripe"], 1000, True), L(w["bank"]), payout_id=saved["id"])
        assert out["id"] == saved["id"]
        assert _amounts(out) == [1000.0, 895.66] and out["amount"] == 895.66
        assert out["gap"] == -1029.5
        listed = client.get("/api/freelance/payouts").json()
        assert [p["id"] for p in listed] == [saved["id"]]
        assert _amounts(listed[0]) == [999.0, 894.76] and listed[0]["amount"] == 894.76

    def test_its_own_week_is_no_conflict(self, client):
        w = _world(client)
        saved = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        out = _preview(client, w, L(w["bank"], 800, True), payout_id=saved["id"])
        assert _amounts(out) == [800.0]

    def test_an_account_archived_after_the_save_is_accepted_for_it_and_not_for_a_new_one(
        self, client
    ):
        w = _world(client)
        saved = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        client.put(f"/api/freelance/accounts/{w['stripe']}", json={"archived": True})
        legs = [L(w["stripe"], 1000, True), L(w["bank"])]
        out = _preview(client, w, *legs, payout_id=saved["id"])
        assert _amounts(out) == [1000.0, 895.66]
        r = _post(client, w, *legs, week=W44)
        assert r.status_code == 422 and r.json()["detail"] == "that account is archived"

    def test_an_unknown_id_is_a_404(self, client):
        w = _world(client)
        r = _post(client, w, L(w["bank"], 100), payout_id=999)
        assert r.status_code == 404 and r.json()["detail"] == "payout not found"

    def test_a_week_with_a_payout_is_previewed_without_the_id(self, client):
        w = _world(client)
        saved = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        out = _preview(client, w, L(w["stripe"], 1000, True), L(w["bank"]))
        assert out["id"] is None and _amounts(out) == [1000.0, 895.66]
        # the save is what refuses
        r = client.post(
            "/api/freelance/payouts",
            json={
                "source_id": w["src"],
                "week_start": W45,
                "legs": [L(w["stripe"], 1000, True), L(w["bank"])],
            },
        )
        assert r.status_code == 409
        assert [p["id"] for p in client.get("/api/freelance/payouts").json()] == [saved["id"]]


# ── the same answer as the save ───────────────────────────────────────────────

SAME = [
    "account_id",
    "currency",
    "amount",
    "fixed",
]
SAME_PAYOUT = [
    "amount",
    "currency",
    "amount_eur",
    "rate_source",
    "rate_date",
    "gap",
    "gap_currency",
    "billed_amount",
    "billed_currency",
    "billed_eur",
    "fx_cost_eur",
    "effective_rate",
    "blocks",
    "minutes",
    "estimate_amount",
    "estimate_eur",
]


class TestTheSameAnswerAsTheSave:
    @pytest.mark.parametrize(
        "make",
        [
            pytest.param(
                lambda w: {"legs": [L(w["stripe"], 999, True)]}, id="one leg, same currency"
            ),
            pytest.param(
                lambda w: {"legs": [L(w["stripe"]), L(w["bank"])]}, id="two legs across currencies"
            ),
            pytest.param(
                lambda w: {
                    "legs": [L(w["stripe"], 999, True), L(w["wise"], 890, True), L(w["bank"])]
                },
                id="three legs with a typed middle",
            ),
            pytest.param(
                lambda w: {
                    "legs": [L(w["stripe"], 999, True), L(w["mercury"], 1000, True)],
                    "eur_amount": 890,
                    "paid_on": "2026-11-04",
                },
                id="eur_amount on a last leg that is not in euros",
            ),
            pytest.param(
                lambda w: {"legs": [L(w["bank"], 1700)], "note": " x "}, id="a note and a euro leg"
            ),
        ],
    )
    def test_the_preview_then_the_save(self, client, make):
        w = _world(client)
        body = {"source_id": w["src"], "week_start": W45, **make(w)}
        r = client.post(PREVIEW, json=body)
        assert r.status_code == 200, r.text
        previewed = r.json()
        saved = _payout(client, **body)
        assert [{k: leg[k] for k in SAME} for leg in previewed["legs"]] == [
            {k: leg[k] for k in SAME} for leg in saved["legs"]
        ]
        assert {k: previewed[k] for k in SAME_PAYOUT} == {k: saved[k] for k in SAME_PAYOUT}
        assert previewed["amount"] is not None and previewed["note"] == saved["note"]


# ── a long chain is only ever written whole ───────────────────────────────────


class TestALongChainIsWrittenWhole:
    def _three(self, client):
        w = _world(client)
        out = _chain_payout(
            client, w, L(w["stripe"], 999, True), L(w["wise"], 890, True), L(w["bank"])
        )
        return w, out

    def test_an_update_without_legs_cannot_drop_a_middle_leg(self, dclient):
        """Replaces the 409 that guarded the older shape: that shape is gone, an update without
        legs is a 422 that names them, and the payout and every table stay as they were."""
        client = dclient
        w, out = self._three(client)
        before = client.get(f"/api/freelance/payouts/{out['id']}").json()
        assert [leg["account_id"] for leg in before["legs"]] == [w["stripe"], w["wise"], w["bank"]]
        tables = _tables(client.engine)
        old = {"source_id": w["src"], "week_start": W45, "amount": 890, "account_id": w["bank"]}
        for body in (old, old | {"sent_amount": 999, "from_account_id": w["stripe"]}):
            r = client.put(f"/api/freelance/payouts/{out['id']}", json=body)
            assert r.status_code == 422 and "legs" in r.text
            assert client.get(f"/api/freelance/payouts/{out['id']}").json() == before
            assert _tables(client.engine) == tables

    def test_its_legs_can_still_be_sent(self, client):
        w, out = self._three(client)
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 999, True), L(w["wise"], 880, True), L(w["bank"])],
        )
        assert _amounts(out) == [999.0, 880.0, 880.0]

    def test_two_legs_and_one_leg_keep_answering_as_they_did(self, client):
        """Replaces the same figures proved through the older shape (1,000 sent and 894.76
        arrived, both typed; 1,700 in one account, typed)."""
        w = _world(client)
        two = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        out = _put(
            client,
            two["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 1000, True), L(w["bank"], 894.76, True)],
        )
        assert _amounts(out) == [1000.0, 894.76] and _fixed(out) == [True, True]
        one = _chain_payout(client, w, L(w["bank"], 1000, True), week=W44)
        out = _put(
            client, one["id"], source_id=w["src"], week_start=W44, legs=[L(w["bank"], 1700, True)]
        )
        assert _amounts(out) == [1700.0] and _fixed(out) == [True]
