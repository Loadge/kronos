"""Populate a throwaway DB with ~22 months of sample data for the README GIF.

Unlike `backend/seed.py` (90 days), this covers 2025-01-01 → 2026-11-02 so the
Analytics tab has a full year-over-year comparison and a well-filled
"Year at a glance" heatmap showing every day type. It also seeds a few fictional
freelance income sources, their hour blocks and one weekly payout for the
Freelance tab.

The dates are fixed (the tour was made on 2026-11-04 and Tue 3 Nov is left empty
for the "Create entry" scene), so the data does not depend on the day it runs.
The server still reads its own clock for "today"; for the exact frames of the
GIF, serve it on 2026-11-04.

NEVER run this against your real data — it deletes all work entries, freelance
blocks, payouts and income sources first.
Point KRONOS_DATA_DIR somewhere disposable:

    KRONOS_DATA_DIR=/tmp/kronos-demo python docs/demo/seed_demo.py
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import DATA_DIR  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Break,
    DayType,
    FreelanceBlock,
    FreelancePayout,
    IncomeSource,
    WorkEntry,
)

RNG = random.Random(42)

START = date(2025, 1, 1)
# Last day with data: Mon 2 Nov 2026. Tue 3 Nov is the day the tour logs live.
LAST_DAY = date(2026, 11, 2)
FL_START = date(2026, 4, 6)

# Spanish national holidays that fall on a weekday in 2025/2026.
HOLIDAYS = {
    date(2025, 1, 1),
    date(2025, 1, 6),
    date(2025, 4, 18),
    date(2025, 5, 1),
    date(2025, 8, 15),
    date(2025, 10, 13),
    date(2025, 12, 8),
    date(2025, 12, 25),
    date(2026, 1, 1),
    date(2026, 1, 6),
    date(2026, 4, 3),
    date(2026, 5, 1),
    date(2026, 8, 15),
    date(2026, 10, 12),
    date(2026, 12, 8),
    date(2026, 12, 25),
}

# (start, end) inclusive vacation blocks.
VACATIONS = [
    (date(2025, 4, 14), date(2025, 4, 17)),
    (date(2025, 8, 4), date(2025, 8, 22)),
    (date(2025, 12, 22), date(2025, 12, 31)),
    (date(2026, 3, 30), date(2026, 4, 2)),
    (date(2026, 6, 15), date(2026, 6, 26)),
]

SICK_DAYS = {
    date(2025, 2, 11),
    date(2025, 11, 5),
    date(2025, 11, 6),
    date(2026, 2, 24),
    date(2026, 5, 12),
}

# Flex days — paid time off charged against the accrued surplus pool.
FLEX_DAYS = {
    date(2025, 5, 2),
    date(2025, 9, 12),
    date(2025, 12, 5),
    date(2026, 1, 2),
    date(2026, 5, 4),
    date(2026, 7, 3),
}


def _fmt(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _workday_times() -> tuple[str, str, list[int]]:
    """Start/end/breaks for a work day, biased slightly above an 8h target."""
    start_min = RNG.randrange(8 * 60, 9 * 60 + 1, 15)
    work_min = RNG.randrange(int(7.25 * 60), int(9.5 * 60) + 1, 15)
    breaks = [RNG.choice([30, 45, 60])]
    if RNG.random() < 0.3:
        breaks.append(RNG.choice([10, 15, 20]))
    end_min = min(start_min + work_min + sum(breaks), 22 * 60 - 15)
    return _fmt(start_min), _fmt(end_min), breaks


def _day_type(d: date) -> DayType:
    if any(a <= d <= b for a, b in VACATIONS):
        return DayType.VACATION
    if d in SICK_DAYS:
        return DayType.SICK
    if d in HOLIDAYS:
        return DayType.HOLIDAY
    if d in FLEX_DAYS:
        return DayType.FLEX
    return DayType.WORK


def build_entries(today: date | None = None) -> list[WorkEntry]:
    today = today or LAST_DAY
    RNG.seed(42)

    entries: list[WorkEntry] = []
    d = START
    while d <= today:
        if d.weekday() >= 5:  # skip weekends
            d += timedelta(days=1)
            continue

        day_type = _day_type(d)
        if day_type is DayType.WORK:
            start, end, break_minutes = _workday_times()
            entry = WorkEntry(date=d, day_type=day_type.value, start_time=start, end_time=end)
            entry.breaks = [Break(break_minutes=m) for m in break_minutes]
        else:
            entry = WorkEntry(date=d, day_type=day_type.value)

        entries.append(entry)
        d += timedelta(days=1)

    return entries


NOTES = [
    "Sprint planning, long one",
    "Release day",
    "Quiet day, caught up on reviews",
    "Client workshop in the morning",
    "Pairing on the importer",
    "Left early for the dentist",
    "Tidied the backlog",
    "Retro and demo",
]


def add_notes(entries: list[WorkEntry]) -> None:
    """A short note on roughly one work day in eight (its own RNG: the hours stay as they were)."""
    rng = random.Random(7)
    for e in entries:
        if e.day_type == DayType.WORK.value and rng.random() < 0.12:
            e.notes = rng.choice(NOTES)


# (name, hourly rate, currency, default)
SOURCES = [
    ("Lumen Studio", 48.0, "EUR", True),
    ("Kestrel Labs", 62.0, "USD", False),
    ("Pine & Quill", 35.0, "EUR", False),
]
FL_NOTES = {
    "Lumen Studio": ["landing page copy", "design review", "component library", "handover notes"],
    "Kestrel Labs": ["API review", "dashboard prototype", "data export", "bug triage"],
    "Pine & Quill": ["newsletter template", "site audit", "content migration"],
}
# The ECB's USD-per-EUR, fixed per month so the demo never calls the network.
FX = {4: 1.09, 5: 1.08, 6: 1.09, 7: 1.10, 8: 1.09, 9: 1.08, 10: 1.07, 11: 1.07}
PAYOUT_WEEK = date(2026, 10, 19)  # Monday; one payout, for Lumen Studio


def _minutes(start: str, end: str) -> int:
    (sh, sm), (eh, em) = (map(int, t.split(":")) for t in (start, end))
    return (eh * 60 + em) - (sh * 60 + sm)


def build_freelance(session) -> tuple[int, int]:
    """Three fictional sources, a rhythm of evening and weekend blocks, one weekly payout."""
    rng = random.Random(2026)
    sources = {}
    for name, rate, currency, default in SOURCES:
        src = IncomeSource(name=name, hourly_rate=rate, currency=currency, is_default=default)
        session.add(src)
        sources[name] = src
    session.flush()

    blocks: list[FreelanceBlock] = []

    def block(day: date, name: str, *, hours: float | None = None, start: str | None = None):
        src = sources[name]
        if start:
            end_min = int(start[:2]) * 60 + int(start[3:]) + int(round((hours or 2) * 60))
            end = _fmt(end_min)
            minutes = _minutes(start, end)
        else:
            end, minutes = None, int(round((hours or 1) * 60))
        blocks.append(
            FreelanceBlock(
                date=day,
                source_id=src.id,
                minutes=minutes,
                start_time=start,
                end_time=end,
                notes=rng.choice(FL_NOTES[name]) if rng.random() < 0.6 else None,
                rate=src.hourly_rate,
                currency=src.currency,
                fx_rate=FX[day.month] if src.currency == "USD" else None,
            )
        )

    monday = FL_START
    while monday <= LAST_DAY:
        week_no = (monday - FL_START).days // 7
        # Summer holiday and the Christmas-ish lull are outside the range; skip one August week.
        if not date(2026, 8, 3) <= monday <= date(2026, 8, 9):
            # Lumen Studio: two evenings a week, with times (always, so the payout week has blocks)
            block(
                monday + timedelta(days=1),
                "Lumen Studio",
                hours=rng.choice([2, 2.5, 3]),
                start="18:30",
            )
            block(
                monday + timedelta(days=3),
                "Lumen Studio",
                hours=rng.choice([1.5, 2, 2.5]),
                start="19:00",
            )
            if week_no % 3 == 0:  # Kestrel Labs: a Saturday morning every third week, by hours
                block(monday + timedelta(days=5), "Kestrel Labs", hours=rng.choice([3, 3.5, 4]))
            if week_no % 3 == 1:  # Pine & Quill: now and then, an hour or two
                block(monday + timedelta(days=2), "Pine & Quill", hours=rng.choice([1, 1.5, 2]))
        monday += timedelta(days=7)
    # The current week starts with an evening for Lumen Studio, so "this week" is not empty.
    block(LAST_DAY, "Lumen Studio", hours=2, start="18:30")
    blocks = [b for b in blocks if b.date <= LAST_DAY]
    session.add_all(blocks)

    # One weekly payout: what Lumen Studio actually paid for the week of 19 Oct (the estimate,
    # rounded to a whole euro).
    estimate = sum(
        b.amount
        for b in blocks
        if b.source_id == sources["Lumen Studio"].id
        and PAYOUT_WEEK <= b.date <= PAYOUT_WEEK + timedelta(days=6)
    )
    session.add(
        FreelancePayout(
            source_id=sources["Lumen Studio"].id,
            week_start=PAYOUT_WEEK,
            amount=float(round(estimate)),
            currency="EUR",
            fx_rate=None,
            note="invoice paid",
        )
    )
    return len(sources), len(blocks)


def main() -> None:
    if not os.getenv("KRONOS_DATA_DIR"):
        sys.exit(
            "Refusing to run: KRONOS_DATA_DIR is unset, so this would wipe the "
            f"default DB at {DATA_DIR}. Point it at a disposable directory."
        )

    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        # Children first: payouts and blocks reference the sources.
        for model in (FreelancePayout, FreelanceBlock, IncomeSource):
            for existing in session.query(model).all():
                session.delete(existing)
        for existing in session.query(WorkEntry).all():
            session.delete(existing)
        session.flush()

        entries = build_entries()
        add_notes(entries)
        session.add_all(entries)
        n_sources, n_blocks = build_freelance(session)
        session.commit()

        counts = {t.value: sum(1 for e in entries if e.day_type == t.value) for t in DayType}

    print(
        f"seeded {len(entries)} entries into {DATA_DIR} "
        f"({entries[0].date} to {entries[-1].date}): "
        + ", ".join(f"{n} {k}" for k, n in counts.items() if n)
        + f"; {n_sources} freelance sources, {n_blocks} blocks, 1 payout"
    )


if __name__ == "__main__":
    main()
