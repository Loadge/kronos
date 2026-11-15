"""Accounts, income sources and day templates come back in the order the user set by hand.

Each list has a `position` column; `PUT .../order` takes every id of the list in the wanted order
and numbers them 0..n-1. A new row goes last, a default stays where it is, a delete leaves a gap.
The same story is told for the three lists, so a rule broken in one of them shows by name.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.database import Base, get_session
from app.main import app as fastapi_app
from app.models import Account, FreelancePayout, IncomeSource
from app.services import chains, freelance
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(params=["foreign keys off", "foreign keys on"])
def dclient(request):
    """A client on an engine that enforces foreign keys or not: production's does, and a delete
    that works on one can fail on the other."""
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


# ── the three lists, told the same way ─────────────────────────────────────────


def _make_account(client, name) -> int:
    r = client.post("/api/freelance/accounts", json={"name": name, "currency": "EUR"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_source(client, name) -> int:
    r = client.post(
        "/api/freelance/sources", json={"name": name, "hourly_rate": 50, "currency": "EUR"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_template(client, name) -> int:
    r = client.post(
        "/api/templates", json={"name": name, "start_time": "09:00", "end_time": "17:00"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


LISTS = {
    "accounts": ("/api/freelance/accounts", _make_account, True),
    "sources": ("/api/freelance/sources", _make_source, True),
    "templates": ("/api/templates", _make_template, False),
}
ALL = pytest.mark.parametrize("kind", list(LISTS))
WITH_DEFAULT = pytest.mark.parametrize("kind", ["accounts", "sources"])


def _names(client, kind) -> list[str]:
    return [row["name"] for row in client.get(LISTS[kind][0]).json()]


def _positions(client, kind) -> list[int]:
    return [row["position"] for row in client.get(LISTS[kind][0]).json()]


def _three(client, kind) -> dict[str, int]:
    make = LISTS[kind][1]
    return {name: make(client, name) for name in ("A", "B", "C")}


class TestOrderOfTheList:
    @ALL
    def test_rows_come_back_in_the_order_they_were_made_with_positions_0_1_2(self, dclient, kind):
        _three(dclient, kind)
        assert _names(dclient, kind) == ["A", "B", "C"]
        assert _positions(dclient, kind) == [0, 1, 2]

    @ALL
    def test_putting_an_order_renumbers_the_rows_and_answers_with_the_new_list(self, dclient, kind):
        path, make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        r = dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["A"], ids["B"]]})
        assert r.status_code == 200, r.text
        assert [row["name"] for row in r.json()] == ["C", "A", "B"]
        assert [row["position"] for row in r.json()] == [0, 1, 2]
        assert _names(dclient, kind) == ["C", "A", "B"]
        assert _positions(dclient, kind) == [0, 1, 2]

    @ALL
    def test_a_row_made_after_a_reorder_goes_last(self, dclient, kind):
        path, make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["A"], ids["B"]]})
        make(dclient, "D")
        assert _names(dclient, kind) == ["C", "A", "B", "D"]
        assert _positions(dclient, kind)[-1] == 3

    @WITH_DEFAULT
    def test_making_a_row_the_default_or_archiving_one_moves_nothing(self, dclient, kind):
        path, make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["A"], ids["B"]]})
        make(dclient, "D")
        r = dclient.put(f"{path}/{ids['B']}", json={"is_default": True})
        assert r.status_code == 200, r.text
        assert _names(dclient, kind) == ["C", "A", "B", "D"]
        assert {row["name"]: row["is_default"] for row in dclient.get(path).json()}["B"] is True
        r = dclient.put(f"{path}/{ids['A']}", json={"archived": True})
        assert r.status_code == 200, r.text
        assert _names(dclient, kind) == ["C", "A", "B", "D"]

    @ALL
    def test_a_deleted_row_leaves_a_gap_and_the_next_one_goes_after_the_last(self, dclient, kind):
        path, make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["A"], ids["B"]]})
        d = make(dclient, "D")
        assert dclient.delete(f"{path}/{ids['A']}").status_code == 204
        make(dclient, "E")
        assert _names(dclient, kind) == ["C", "B", "D", "E"]
        positions = _positions(dclient, kind)
        assert positions == sorted(positions)
        assert positions[-1] > {row["id"]: row["position"] for row in dclient.get(path).json()}[d]

    @WITH_DEFAULT
    def test_archived_rows_are_part_of_the_list_and_must_be_in_the_order(self, dclient, kind):
        path, _make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        dclient.put(f"{path}/{ids['A']}", json={"archived": True})
        r = dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["B"]]})
        assert r.status_code == 422
        r = dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["B"], ids["A"]]})
        assert r.status_code == 200, r.text
        assert _names(dclient, kind) == ["C", "B", "A"]


class TestRefusedOrders:
    @ALL
    @pytest.mark.parametrize(
        "make_ids",
        [
            pytest.param(lambda i: [i["B"], i["A"]], id="one id missing"),
            pytest.param(lambda i: [i["B"], i["A"], i["C"], 9999], id="an unknown id"),
            pytest.param(lambda i: [i["B"], i["A"], 9999], id="an unknown id instead of one"),
            pytest.param(lambda i: [i["B"], i["A"], i["C"], i["C"]], id="an id twice"),
            pytest.param(lambda i: [i["B"], i["B"], i["A"]], id="an id twice, another missing"),
            pytest.param(lambda i: [], id="an empty list"),
        ],
    )
    def test_anything_but_exactly_the_ids_is_a_422_and_changes_nothing(
        self, dclient, kind, make_ids
    ):
        path, _make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        before = dclient.get(path).json()
        r = dclient.put(f"{path}/order", json={"ids": make_ids(ids)})
        assert r.status_code == 422, r.text
        assert dclient.get(path).json() == before
        assert _names(dclient, kind) == ["A", "B", "C"]

    @ALL
    def test_order_is_read_as_the_route_not_as_an_id(self, dclient, kind):
        path, _make, _ = LISTS[kind]
        r = dclient.put(f"{path}/order", json={"ids": [4242]})
        assert r.status_code == 422, r.text
        assert r.json()["detail"] != "not found"
        # with nothing in the list the empty order is the exact set of ids
        r = dclient.put(f"{path}/order", json={"ids": []})
        assert r.status_code == 200, r.text
        assert r.json() == []


class TestDefaultSource:
    def test_with_no_default_it_is_the_first_live_source_by_position_not_by_id(self, dclient):
        a = _make_source(dclient, "A")
        b = _make_source(dclient, "B")
        c = _make_source(dclient, "C")
        dclient.put(f"/api/freelance/sources/{a}", json={"is_default": False})
        assert (
            dclient.put("/api/freelance/sources/order", json={"ids": [c, b, a]}).status_code == 200
        )
        with sessionmaker(bind=dclient.engine)() as session:
            assert [s.is_default for s in session.query(IncomeSource)] == [False, False, False]
            assert freelance.default_source(session).id == c
        dclient.put(f"/api/freelance/sources/{c}", json={"archived": True})
        with sessionmaker(bind=dclient.engine)() as session:
            assert freelance.default_source(session).id == b

    def test_a_default_wins_wherever_it_stands(self, dclient):
        a = _make_source(dclient, "A")
        b = _make_source(dclient, "B")
        c = _make_source(dclient, "C")
        dclient.put(f"/api/freelance/sources/{c}", json={"is_default": True})
        dclient.put("/api/freelance/sources/order", json={"ids": [a, b, c]})
        with sessionmaker(bind=dclient.engine)() as session:
            assert freelance.default_source(session).id == c


class TestMadeAccounts:
    def test_an_account_made_for_a_payout_goes_after_every_account_whatever_their_positions(
        self, dclient
    ):
        ids = [_make_account(dclient, n) for n in ("Stripe", "Wise", "Main bank")]
        src = _make_source(dclient, "Northwind")
        with sessionmaker(bind=dclient.engine)() as session:
            for account_id, position in zip(ids, (10, 4, 7), strict=True):
                session.get(Account, account_id).position = position
            session.commit()
            payout = FreelancePayout(
                source_id=src,
                week_start=date(2026, 11, 2),
                amount=100.0,
                currency="USD",
            )
            chains.legs_from_sides(session, payout)
            session.commit()
            made = session.query(Account).filter(Account.name == "USD account").one()
            assert made.position == 11


class TestForeignKeysOn:
    @ALL
    def test_reorder_then_delete_a_row_raises_nothing(self, dclient, kind):
        path, _make, _ = LISTS[kind]
        ids = _three(dclient, kind)
        assert (
            dclient.put(f"{path}/order", json={"ids": [ids["C"], ids["B"], ids["A"]]}).status_code
            == 200
        )
        assert dclient.delete(f"{path}/{ids['B']}").status_code == 204
        assert _names(dclient, kind) == ["C", "A"]
