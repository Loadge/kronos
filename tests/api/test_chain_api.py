# ruff: noqa: E501
"""The API reads and writes a payout as a chain of one to four accounts.

Miguel's week: 22.55 h at $90 = $2,029.50 billed, the ECB at 1.1165 USD per EUR. The ECB and
CoinGecko are stubbed in every test: nothing leaves the process and nothing depends on the day
the suite runs. After every write the invariant is checked on every payout in the database.
"""

from __future__ import annotations

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from app.database import Base, get_session
from app.main import app as fastapi_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RATE = 1.1165  # USD per EUR on every day the ECB document below covers
W45 = "2026-11-02"  # its Sunday, Nov 8, is a weekend: the ECB's last word is Friday's
W44 = "2026-10-26"
W2 = "2026-01-05"  # before the stub's first day: no rate

_DAYS = ("2026-11-06", "2026-11-05", "2026-11-04", "2026-11-03", "2026-11-02", "2026-10-30")
_CUBES = "".join(f'<Cube time="{d}"><Cube currency="USD" rate="{RATE}"/></Cube>' for d in _DAYS)
ECB = f"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>{_CUBES}</Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    fx._reset()
    crypto._reset()
    monkeypatch.setattr(fx, "_fetch", lambda url, timeout=3: ECB.encode())
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    monkeypatch.setenv("KRONOS_CRYPTO_URL", "https://crypto.example.invalid")

    def no_coins(url: str) -> bytes:
        raise AssertionError(f"unexpected CoinGecko request {url}")

    monkeypatch.setattr(crypto, "_fetch", no_coins)
    yield
    fx._reset()
    crypto._reset()


@pytest.fixture(params=["foreign keys off", "foreign keys on"])
def dclient(request):
    """A client on an engine that enforces foreign keys or not: the test suite's engine does not,
    production's does, and a delete that works on one can fail on the other."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    if request.param == "foreign keys on":

        @event.listens_for(engine, "connect")
        def _pragma(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_session] = session
    try:
        with TestClient(fastapi_app) as c:
            c.engine = engine
            c.enforced = request.param == "foreign keys on"
            yield c
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


# ── helpers ───────────────────────────────────────────────────────────────────


def _account(client, name, currency, **kw) -> int:
    r = client.post("/api/freelance/accounts", json={"name": name, "currency": currency, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _source(client, name="Northwind", rate=90, currency="USD", **kw) -> int:
    r = client.post(
        "/api/freelance/sources",
        json={"name": name, "hourly_rate": rate, "currency": currency, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(client, source_id, day="2026-11-03", hours=22.55):
    r = client.post(
        "/api/freelance/blocks",
        json={"date": day, "source_id": source_id, "hours": hours, "fx_rate": RATE},
    )
    assert r.status_code == 201, r.text


def _world(client) -> dict:
    """Northwind at $90/h, one block of 22.55 h in W45, and four accounts that do either."""
    src = _source(client)
    _block(client, src)
    return {
        "src": src,
        "stripe": _account(client, "Stripe", "USD"),
        "wise": _account(client, "Wise", "EUR"),
        "bank": _account(client, "Main bank", "EUR"),
        "mercury": _account(client, "Mercury", "USD"),
    }


def L(account_id, amount=None, fixed=None) -> dict:
    """One leg of the request: the keys the client leaves out are left out."""
    leg: dict = {"account_id": account_id}
    if amount is not None:
        leg["amount"] = amount
    if fixed is not None:
        leg["fixed"] = fixed
    return leg


def _invariant(out: dict) -> None:
    """Every payout has 1 to 4 legs at positions 0..n-1, no account twice, and its last leg is
    the payout's own amount, in the payout's own account and currency."""
    legs = out["legs"]
    assert 1 <= len(legs) <= 4, out
    assert [leg["position"] for leg in legs] == list(range(len(legs)))
    ids = [leg["account_id"] for leg in legs]
    assert len(set(ids)) == len(ids)
    assert legs[-1]["amount"] == out["amount"]
    assert legs[-1]["currency"] == out["currency"]
    assert legs[-1]["account_id"] == out["account_id"]


def _all_hold_the_invariant(client) -> None:
    for out in client.get("/api/freelance/payouts").json():
        _invariant(out)


def _written(client, out: dict) -> None:
    _invariant(out)
    _all_hold_the_invariant(client)


def _payout(client, expect=201, **body) -> dict:
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == expect, r.text
    if expect == 201:
        _written(client, r.json())
    return r.json()


def _put(client, payout_id, expect=200, **body) -> dict:
    r = client.put(f"/api/freelance/payouts/{payout_id}", json=body)
    assert r.status_code == expect, r.text
    if expect == 200:
        _written(client, r.json())
    return r.json()


def _chain_payout(client, w, *legs, week=W45, expect=201, **kw) -> dict:
    return _payout(client, expect, source_id=w["src"], week_start=week, legs=list(legs), **kw)


def _amounts(out) -> list[float]:
    return [leg["amount"] for leg in out["legs"]]


def _fixed(out) -> list[bool]:
    return [leg["fixed"] for leg in out["legs"]]


def _positions(client, table: str, owner: str, owner_id: int) -> list[int]:
    with client.engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT position FROM {table} WHERE {owner} = :i ORDER BY position"),
            {"i": owner_id},
        )
        return [r[0] for r in rows]


# ── the new shape: Miguel's week ──────────────────────────────────────────────


class TestLegsWorkedOut:
    def test_a_dollar_account_then_a_euro_one(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"]))
        assert _amounts(out) == [999.0, 894.76] and _fixed(out) == [True, False]
        assert [leg["account_name"] for leg in out["legs"]] == ["Stripe", "Main bank"]
        assert [leg["currency"] for leg in out["legs"]] == ["USD", "EUR"]
        # the payout is what the last account got, and every old total reads it
        assert (out["amount"], out["currency"], out["amount_eur"]) == (894.76, "EUR", 894.76)
        assert out["fx_cost_eur"] == 922.97
        # the first leg against what the week billed, in dollars
        assert (out["gap"], out["gap_currency"]) == (-1030.5, "USD")
        assert out["account_id"] == w["bank"] and out["account_name"] == "Main bank"

    def test_nothing_typed_follows_what_the_week_billed(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"]), L(w["bank"]))
        assert _amounts(out) == [2029.5, 1817.73] and _fixed(out) == [False, False]
        assert out["amount"] == 1817.73 and out["gap"] == 0.0

    def test_three_accounts_and_the_edits_of_the_middle_one(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["wise"]), L(w["bank"]))
        assert _amounts(out) == [999.0, 894.76, 894.76]
        assert _fixed(out) == [True, False, False]
        # the middle one typed: the last follows it
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 999, True), L(w["wise"], 890, True), L(w["bank"])],
        )
        assert _amounts(out) == [999.0, 890.0, 890.0] and out["amount"] == 890.0
        assert out["gap"] == -1030.5  # from the first leg: the last one would say -1035.81
        # the first changes: the typed one does not move
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 1000, True), L(w["wise"], 890, True), L(w["bank"])],
        )
        assert _amounts(out) == [1000.0, 890.0, 890.0]
        assert out["gap"] == -1029.5
        # the same accounts in another order and one of them gone
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["wise"], 890, True), L(w["stripe"], 1000, True)],
        )
        assert [leg["account_id"] for leg in out["legs"]] == [w["wise"], w["stripe"]]
        assert out["currency"] == "USD" and out["amount"] == 1000.0

    def test_one_account(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["bank"]))
        assert _amounts(out) == [1817.73] and _fixed(out) == [False]
        assert (out["currency"], out["gap"]) == ("EUR", 0.0)
        out = _put(client, out["id"], source_id=w["src"], week_start=W45, legs=[L(w["bank"], 1700)])
        assert _amounts(out) == [1700.0] and _fixed(out) == [True]
        # EUR 1,700 is $1,898.05 at the day's rate: against $2,029.50 billed
        assert (out["gap"], out["gap_currency"]) == (-131.45, "USD")

    def test_a_suggestion_the_client_confirmed_is_stored_as_it_was_shown(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"], 894.76, False))
        assert _amounts(out) == [999.0, 894.76] and _fixed(out) == [True, False]
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 999, True), L(w["bank"], 900, False)],
        )
        assert _amounts(out) == [999.0, 900.0] and _fixed(out) == [True, False]
        assert out["amount"] == 900.0
        got = client.get(f"/api/freelance/payouts/{out['id']}").json()
        assert _amounts(got) == [999.0, 900.0]

    def test_a_first_leg_that_was_not_typed_has_no_gap_whatever_it_converts_to(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["bank"], 1817.72, False))
        assert out["gap"] == 0.0  # EUR 1,817.72 is $2,029.48: not the cent the conversion says
        out = _put(
            client, out["id"], source_id=w["src"], week_start=W45, legs=[L(w["bank"], 1817.72)]
        )
        assert out["gap"] == -0.02  # typed, it is what it converts to

    def test_the_gap_is_none_when_nothing_was_billed_or_the_day_has_no_rate(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["bank"], 100), week=W44)
        assert (out["gap"], out["gap_currency"]) == (None, "USD")  # no blocks that week
        _block(client, w["src"], day="2026-01-06")
        out = _chain_payout(client, w, L(w["bank"], 100), week=W2)
        assert out["gap"] is None  # EUR to USD on a day the ECB has no word for


class TestTheLastAccountGivesTheRate:
    def test_a_dollar_account_gets_the_ecb_rate_of_the_day_or_the_typed_euros(self, client):
        """Replaces the test that compared this with the older request shape: the figures it
        compared are written out (1,900 dollars at 1.1165 are 1,701.75 euros; typed as 1,700
        euros they are a rate of 1900 / 1700)."""
        w = _world(client)
        out = _chain_payout(client, w, L(w["mercury"], 1900, True), paid_on="2026-11-04")
        assert (out["currency"], out["fx_rate"], out["rate_source"]) == ("USD", RATE, "ECB")
        assert (out["rate_date"], out["amount"], out["amount_eur"]) == (
            "2026-11-04",
            1900.0,
            1701.75,
        )
        by_hand = _chain_payout(
            client,
            w,
            L(w["mercury"], 1900, True),
            week=W44,
            paid_on="2026-11-04",
            eur_amount=1700,
        )
        assert (by_hand["currency"], by_hand["rate_source"]) == ("USD", "manual")
        assert (by_hand["rate_date"], by_hand["amount"]) == ("2026-11-04", 1900.0)
        assert (by_hand["fx_rate"], by_hand["amount_eur"]) == (1900 / 1700, 1700.0)

    def test_any_account_can_be_the_last_one(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["bank"], 100), L(w["mercury"], 100))
        assert [leg["account_id"] for leg in out["legs"]] == [w["bank"], w["mercury"]]
        assert out["account_id"] == w["mercury"] and out["currency"] == "USD"


class TestTheDayOfTheRate:
    """A worked-out leg is converted at the rate of `paid_on`, else of the week's Sunday."""

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

        history = [("2026-11-10", 1.25)] + [(d, RATE) for d in _DAYS]  # newest first
        only_newest = document(history[:1])  # the daily document holds one day
        everything = document(history)

        def fetch(url, timeout=3):
            return only_newest if url.endswith("daily.xml") else everything

        fx._reset()
        monkeypatch.setattr(fx, "_fetch", fetch)

    def test_paid_on_picks_the_rate_not_the_sunday(self, client, monkeypatch):
        self._two_rates(monkeypatch)
        w = _world(client)
        legs = [L(w["stripe"], 999, True), L(w["bank"])]
        # no paid_on: the week's Sunday (Nov 8) takes Friday's rate, 999 / 1.1165
        out = _chain_payout(client, w, *legs)
        assert _amounts(out) == [999.0, 894.76]
        body = {"source_id": w["src"], "week_start": W45}
        # paid on Tuesday the 10th: 999 / 1.25
        out = _put(client, out["id"], **body, legs=legs, paid_on="2026-11-10")
        assert _amounts(out) == [999.0, 799.2] and _fixed(out) == [True, False]
        # one account, worked out from the dollars billed: 2029.50 / 1.25
        out = _put(client, out["id"], **body, legs=[L(w["bank"])], paid_on="2026-11-10")
        assert _amounts(out) == [1623.6] and _fixed(out) == [False]


class TestAWeekWithNoRate:
    def test_the_leg_that_needs_one_is_refused_and_a_typed_one_is_not(self, client):
        w = _world(client)
        _block(client, w["src"], day="2026-01-06")
        r = client.post(
            "/api/freelance/payouts",
            json={
                "source_id": w["src"],
                "week_start": W2,
                "legs": [L(w["stripe"], 500, True), L(w["bank"])],
            },
        )
        assert r.status_code == 422
        assert "no rate for that day" in r.json()["detail"]
        r = client.post(
            "/api/freelance/payouts",
            json={"source_id": w["src"], "week_start": W2, "legs": [L(w["bank"])]},
        )
        assert r.status_code == 422  # the first leg, from the dollars billed, needs it too
        out = _chain_payout(client, w, L(w["stripe"], 500, True), L(w["bank"], 450, True), week=W2)
        assert _amounts(out) == [500.0, 450.0]
        assert client.get("/api/freelance/payouts").json()[0]["id"] == out["id"]

    def test_a_refused_save_leaves_nothing_behind(self, client):
        w = _world(client)
        _block(client, w["src"], day="2026-01-06")
        client.post(
            "/api/freelance/payouts",
            json={
                "source_id": w["src"],
                "week_start": W2,
                "legs": [L(w["stripe"], 500, True), L(w["bank"])],
            },
        )
        assert client.get("/api/freelance/payouts").json() == []


# ── what is refused ───────────────────────────────────────────────────────────


class TestTheRules:
    def _post(self, client, w, **kw):
        body = {"source_id": w["src"], "week_start": W45, **kw}
        return client.post("/api/freelance/payouts", json=body)

    def test_one_to_four_legs(self, client):
        w = _world(client)
        extra = [_account(client, f"Extra {i}", "EUR") for i in range(2)]
        assert self._post(client, w, legs=[]).status_code == 422
        five = [w["stripe"], w["wise"], w["bank"], extra[0], extra[1]]
        assert self._post(client, w, legs=[L(a, 100) for a in five]).status_code == 422
        four = self._post(client, w, legs=[L(a, 100) for a in five[:4]])
        assert four.status_code == 201, four.text
        _invariant(four.json())

    def test_an_unknown_account_and_the_same_account_twice(self, client):
        w = _world(client)
        assert self._post(client, w, legs=[L(999, 100)]).status_code == 422
        r = self._post(client, w, legs=[L(w["bank"], 100), L(w["bank"], 90)])
        assert r.status_code == 422 and "only once" in r.json()["detail"]
        assert client.get("/api/freelance/payouts").json() == []

    def test_an_amount_that_is_not_positive(self, client):
        w = _world(client)
        for amount in (0, -5):
            assert (
                self._post(client, w, legs=[L(w["bank"]) | {"amount": amount}]).status_code == 422
            )

    def test_fixed_needs_its_amount(self, client):
        w = _world(client)
        assert (
            self._post(client, w, legs=[{"account_id": w["bank"], "fixed": True}]).status_code
            == 422
        )
        ok = self._post(client, w, legs=[{"account_id": w["bank"], "fixed": False}])
        assert ok.status_code == 201 and ok.json()["legs"][0]["fixed"] is False

    def test_nothing_billed_and_no_amount_is_a_question_for_the_client(self, client):
        w = _world(client)
        r = self._post(client, w, week_start=W44, legs=[L(w["stripe"]), L(w["bank"])])
        assert r.status_code == 422 and "type the amount" in r.json()["detail"]

    def test_an_archived_account_only_where_the_payout_already_has_it(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999), L(w["bank"], 894.76))
        client.put(f"/api/freelance/accounts/{w['stripe']}", json={"archived": True})
        # the old payout stays editable, with the archived account in it
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 1000), L(w["bank"], 894.76)],
        )
        assert [leg["account_id"] for leg in out["legs"]] == [w["stripe"], w["bank"]]
        # a payout that does not have it yet cannot take it
        r = self._post(client, w, week_start=W44, legs=[L(w["stripe"], 5), L(w["bank"], 4)])
        assert r.status_code == 422 and "archived" in r.json()["detail"]
        # and the same payout moved to another account that is archived is refused too
        client.put(f"/api/freelance/accounts/{w['wise']}", json={"archived": True})
        r = client.put(
            f"/api/freelance/payouts/{out['id']}",
            json={"source_id": w["src"], "week_start": W45, "legs": [L(w["wise"], 5)]},
        )
        assert r.status_code == 422

    def test_legs_are_required_whatever_else_is_sent(self, client):
        """A request without legs is a 422 that names them, for a save and for an update; the
        older fields (an amount, an account, a sent side) do not stand in for them."""
        w = _world(client)
        out = _chain_payout(client, w, L(w["bank"], 100))
        for body in (
            {},
            {"amount": 100},
            {"amount": 100, "account_id": w["bank"]},
            {
                "amount": 894.76,
                "account_id": w["bank"],
                "sent_amount": 999,
                "from_account_id": w["stripe"],
            },
        ):
            post = self._post(client, w, week_start=W44, **body)
            put = client.put(
                f"/api/freelance/payouts/{out['id']}",
                json={"source_id": w["src"], "week_start": W45, **body},
            )
            for r in (post, put):
                assert r.status_code == 422 and "legs" in r.text, body
        assert client.get(f"/api/freelance/payouts/{out['id']}").json() == out
        assert len(client.get("/api/freelance/payouts").json()) == 1

    def test_the_older_fields_beside_legs_change_nothing_and_are_not_stored(self, client):
        w = _world(client)
        plain = _chain_payout(client, w, L(w["bank"], 100), paid_on="2026-11-04", note="x")
        noisy = self._post(
            client,
            w,
            week_start=W44,
            legs=[L(w["bank"], 100)],
            paid_on="2026-11-04",
            note="x",
            amount=5,
            account_id=w["stripe"],
            fx_rate=1.2,
            sent_amount=999,
            sent_currency="USD",
            from_account_id=w["stripe"],
        )
        assert noisy.status_code == 201, noisy.text
        keys = ("amount", "currency", "fx_rate", "amount_eur", "account_id", "note", "legs")
        assert {k: noisy.json()[k] for k in keys} == {k: plain[k] for k in keys}
        stored = client.get(f"/api/freelance/payouts/{noisy.json()['id']}").json()
        assert not {"sent_amount", "sent_currency", "from_account_id", "sent_gap"} & stored.keys()


# ── the money the older request shape used to prove, as a chain ───────────────


class TestTypedLegs:
    def test_a_sent_and_an_arrived_amount_are_two_fixed_legs(self, client):
        """Replaces the older shape's "sent and arrived": Stripe 999 and Main bank 894.76."""
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"], 894.76, True))
        assert [(leg["account_name"], leg["amount"], leg["fixed"]) for leg in out["legs"]] == [
            ("Stripe", 999.0, True),
            ("Main bank", 894.76, True),
        ]
        assert (out["amount"], out["amount_eur"], out["fx_cost_eur"]) == (894.76, 894.76, 922.97)
        assert out["gap"] == -1030.5
        # changing the first leg
        out = _put(
            client,
            out["id"],
            source_id=w["src"],
            week_start=W45,
            legs=[L(w["stripe"], 1000, True), L(w["bank"], 894.76, True)],
        )
        assert _amounts(out) == [1000.0, 894.76]
        # and leaving one
        out = _put(
            client, out["id"], source_id=w["src"], week_start=W45, legs=[L(w["bank"], 894.76, True)]
        )
        assert _amounts(out) == [894.76]

    def test_the_answers_have_none_of_the_dropped_fields(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999, True), L(w["bank"], 894.76, True))
        dropped = {
            "sent_amount",
            "sent_currency",
            "from_account_id",
            "from_account_name",
            "sent_gap",
        }
        assert not dropped & out.keys()
        assert not dropped & client.get(f"/api/freelance/payouts/{out['id']}").json().keys()
        assert not dropped & client.get("/api/freelance/payouts").json()[0].keys()
        (src,) = client.get("/api/freelance/sources").json()
        assert not {"default_account_id", "default_from_account_id"} & src.keys()
        assert "chain" in src
        for account in client.get("/api/freelance/accounts").json():
            assert "role" not in account
        r = client.post(
            "/api/freelance/accounts", json={"name": "Sender", "currency": "USD", "role": "origin"}
        )
        assert r.status_code == 201 and "role" not in r.json()
        r = client.post(
            "/api/freelance/sources",
            json={"name": "X", "hourly_rate": 1, "default_account_id": w["bank"]},
        )
        assert r.status_code == 201 and "default_account_id" not in r.json()
        assert r.json()["chain"] == []  # the default was ignored, not turned into a chain


# ── a source's usual chain ────────────────────────────────────────────────────


class TestSourceChains:
    def test_a_chain_round_trips_in_order(self, client, db_engine):
        client.engine = db_engine
        w = _world(client)
        src = _source(client, "Other", chain=[w["bank"], w["stripe"], w["wise"]])
        row = {s["id"]: s for s in client.get("/api/freelance/sources").json()}[src]
        assert row["chain"] == [w["bank"], w["stripe"], w["wise"]]
        r = client.put(f"/api/freelance/sources/{src}", json={"chain": [w["stripe"], w["bank"]]})
        assert r.status_code == 200 and r.json()["chain"] == [w["stripe"], w["bank"]]
        assert _positions(client, "income_source_accounts", "source_id", src) == [0, 1]

    def test_empty_omitted_and_a_source_with_none(self, client, db_engine):
        client.engine = db_engine
        w = _world(client)
        assert client.get("/api/freelance/sources").json()[0]["chain"] == []
        r = client.put(f"/api/freelance/sources/{w['src']}", json={"chain": [w["bank"]]})
        assert r.json()["chain"] == [w["bank"]]
        r = client.put(f"/api/freelance/sources/{w['src']}", json={"name": "Renamed"})
        assert r.json()["chain"] == [w["bank"]]  # left out: kept
        r = client.put(f"/api/freelance/sources/{w['src']}", json={"chain": []})
        assert r.json()["chain"] == []  # [] empties it
        assert _positions(client, "income_source_accounts", "source_id", w["src"]) == []

    def test_what_is_refused(self, client):
        w = _world(client)
        extra = [_account(client, f"Extra {i}", "EUR") for i in range(2)]
        five = [w["stripe"], w["wise"], w["bank"], extra[0], extra[1]]
        client.put(f"/api/freelance/accounts/{extra[1]}", json={"archived": True})
        bad = {
            "more than four": five,
            "unknown account": [w["bank"], 999],
            "a repeat": [w["bank"], w["stripe"], w["bank"]],
            "an archived account": [w["bank"], extra[1]],
        }
        for what, chain in bad.items():
            put = client.put(f"/api/freelance/sources/{w['src']}", json={"chain": chain})
            post = client.post(
                "/api/freelance/sources",
                json={"name": "N", "hourly_rate": 1, "currency": "EUR", "chain": chain},
            )
            assert (put.status_code, post.status_code) == (422, 422), what
        assert client.get("/api/freelance/sources").json()[0]["chain"] == []
        assert len(client.get("/api/freelance/sources").json()) == 1

    def test_a_first_save_with_one_leg_becomes_the_chain_of_a_source_without_one(self, client):
        w = _world(client)
        _chain_payout(client, w, L(w["bank"]))
        assert client.get("/api/freelance/sources").json()[0]["chain"] == [w["bank"]]

    def test_a_chain_that_exists_is_left_alone(self, client):
        w = _world(client)
        client.put(f"/api/freelance/sources/{w['src']}", json={"chain": [w["stripe"], w["wise"]]})
        _chain_payout(client, w, L(w["bank"]))
        assert client.get("/api/freelance/sources").json()[0]["chain"] == [w["stripe"], w["wise"]]

    def test_two_legs_never_set_it(self, client):
        w = _world(client)
        _chain_payout(client, w, L(w["stripe"], 999), L(w["bank"]))
        _chain_payout(client, w, L(w["stripe"], 5), L(w["bank"], 4), week=W44)
        assert client.get("/api/freelance/sources").json()[0]["chain"] == []

    def test_one_leg_on_an_update_counts_as_a_save_too(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999), L(w["bank"]))
        _put(client, out["id"], source_id=w["src"], week_start=W45, legs=[L(w["wise"], 5)])
        assert client.get("/api/freelance/sources").json()[0]["chain"] == [w["wise"]]

    def test_changing_a_chain_never_touches_a_saved_payout(self, client):
        w = _world(client)
        out = _chain_payout(client, w, L(w["stripe"], 999), L(w["wise"]), L(w["bank"]))
        client.put(f"/api/freelance/sources/{w['src']}", json={"chain": [w["mercury"]]})
        client.put(f"/api/freelance/sources/{w['src']}", json={"chain": []})
        client.put(f"/api/freelance/sources/{w['src']}", json={"chain": [w["bank"], w["stripe"]]})
        assert client.get(f"/api/freelance/payouts/{out['id']}").json() == out


# ── accounts ──────────────────────────────────────────────────────────────────


class TestAccountsAndChains:
    def test_the_engine_of_the_fixture_does_what_its_name_says(self, dclient):
        """A positive control: with foreign keys on, the database itself refuses what the code
        must therefore never attempt."""
        w = _world(dclient)
        _chain_payout(dclient, w, L(w["stripe"], 999), L(w["bank"]))
        with dclient.engine.connect() as conn:
            on = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert on == (1 if dclient.enforced else 0)
            if dclient.enforced:
                with pytest.raises(IntegrityError):
                    conn.execute(text("DELETE FROM accounts WHERE name = 'Stripe'"))
            else:
                conn.execute(text("DELETE FROM accounts WHERE name = 'Stripe'"))
            conn.rollback()

    def test_an_account_in_a_legs_cannot_be_deleted_whichever_leg_it_is(self, dclient):
        w = _world(dclient)
        _chain_payout(dclient, w, L(w["stripe"], 999), L(w["wise"]), L(w["bank"]))
        for name in ("stripe", "wise", "bank"):  # the middle one is in no old column
            r = dclient.delete(f"/api/freelance/accounts/{w[name]}")
            assert r.status_code == 409, name
        assert dclient.delete(f"/api/freelance/accounts/{w['mercury']}").status_code == 204

    def test_a_made_account_with_payouts_is_a_409_not_a_500(self, dclient):
        # a restore of a file that gives a payout no legs makes the account it needs
        old_file = {
            "version": 5,
            "income_sources": [
                {"id": 1, "name": "Northwind", "hourly_rate": 90, "currency": "USD"}
            ],
            "freelance_payouts": [
                {
                    "source_id": 1,
                    "week_start": W45,
                    "amount": 1900,
                    "currency": "USD",
                    "fx_rate": RATE,
                }
            ],
        }
        assert dclient.post("/api/restore", json=old_file).status_code == 200
        made = next(a for a in dclient.get("/api/freelance/accounts").json() if a["payouts"] == 1)
        assert made["name"] == "USD account"
        assert dclient.delete(f"/api/freelance/accounts/{made['id']}").status_code == 409

    def test_a_payout_gone_frees_its_accounts(self, dclient):
        w = _world(dclient)
        out = _chain_payout(dclient, w, L(w["stripe"], 999), L(w["bank"]))
        assert dclient.delete(f"/api/freelance/payouts/{out['id']}").status_code == 204
        assert dclient.delete(f"/api/freelance/accounts/{w['stripe']}").status_code == 204
        assert dclient.delete(f"/api/freelance/accounts/{w['bank']}").status_code == 204

    def test_an_account_only_in_chains_is_deleted_and_the_chains_close_up(self, dclient):
        w = _world(dclient)
        a = _source(dclient, "A", chain=[w["stripe"], w["wise"], w["bank"]])
        b = _source(dclient, "B", chain=[w["wise"], w["bank"]])
        assert dclient.delete(f"/api/freelance/accounts/{w['wise']}").status_code == 204
        rows = {s["id"]: s for s in dclient.get("/api/freelance/sources").json()}
        assert rows[a]["chain"] == [w["stripe"], w["bank"]] and rows[b]["chain"] == [w["bank"]]
        assert _positions(dclient, "income_source_accounts", "source_id", a) == [0, 1]
        assert _positions(dclient, "income_source_accounts", "source_id", b) == [0]
        assert [x["id"] for x in dclient.get("/api/freelance/accounts").json()].count(
            w["wise"]
        ) == 0

    def test_the_currency_of_an_account_in_a_leg_is_locked_and_one_in_a_chain_is_not(self, dclient):
        w = _world(dclient)
        _chain_payout(dclient, w, L(w["stripe"], 999), L(w["bank"]))
        r = dclient.put(f"/api/freelance/accounts/{w['stripe']}", json={"currency": "EUR"})
        assert r.status_code == 409
        r = dclient.put(f"/api/freelance/accounts/{w['stripe']}", json={"currency": "USD"})
        assert r.status_code == 200  # not a change
        _source(dclient, "A", chain=[w["wise"]])
        r = dclient.put(f"/api/freelance/accounts/{w['wise']}", json={"currency": "USD"})
        assert r.status_code == 200 and r.json()["currency"] == "USD"

    def test_archiving_takes_an_account_out_of_every_chain_and_leaves_the_legs(self, dclient):
        w = _world(dclient)
        out = _chain_payout(dclient, w, L(w["stripe"], 999), L(w["wise"]), L(w["bank"]))
        a = _source(dclient, "A", chain=[w["stripe"], w["wise"], w["bank"]])
        b = _source(dclient, "B", chain=[w["bank"], w["wise"]])
        r = dclient.put(f"/api/freelance/accounts/{w['wise']}", json={"archived": True})
        assert r.status_code == 200 and r.json()["archived"] is True and r.json()["payouts"] == 1
        rows = {s["id"]: s for s in dclient.get("/api/freelance/sources").json()}
        assert rows[a]["chain"] == [w["stripe"], w["bank"]] and rows[b]["chain"] == [w["bank"]]
        assert _positions(dclient, "income_source_accounts", "source_id", a) == [0, 1]
        assert dclient.get(f"/api/freelance/payouts/{out['id']}").json() == out
        # un-archiving does not put it back
        dclient.put(f"/api/freelance/accounts/{w['wise']}", json={"archived": False})
        rows = {s["id"]: s for s in dclient.get("/api/freelance/sources").json()}
        assert rows[a]["chain"] == [w["stripe"], w["bank"]]

    def test_the_payouts_of_an_account_count_the_legs_it_is_in(self, client):
        w = _world(client)
        _chain_payout(client, w, L(w["stripe"], 999), L(w["wise"]), L(w["bank"]))
        _chain_payout(client, w, L(w["bank"], 100), week=W44)
        counts = {a["name"]: a["payouts"] for a in client.get("/api/freelance/accounts").json()}
        assert counts["Stripe"] == 1 and counts["Wise"] == 1 and counts["Main bank"] == 2
        assert counts["Mercury"] == 0
