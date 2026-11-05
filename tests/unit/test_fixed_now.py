"""KRONOS_NOW freezes the app's clock for a disposable instance, and only then."""

from __future__ import annotations

from datetime import date, datetime

from app.services import clock


def test_a_fixed_instant_is_read_in_the_configured_zone(monkeypatch):
    # 23:30 UTC on the 3rd is already the 4th in Madrid: "today" must follow the zone
    monkeypatch.setattr(clock, "FIXED_NOW", "2026-11-03T23:30:00+00:00")
    monkeypatch.setattr(clock, "TIMEZONE", "Europe/Madrid")
    assert clock.local_today() == date(2026, 11, 4)
    assert clock.local_hhmm() == "00:30"


def test_without_it_the_clock_runs(monkeypatch):
    monkeypatch.setattr(clock, "FIXED_NOW", "")
    assert abs(clock.local_now().timestamp() - datetime.now().timestamp()) < 5
