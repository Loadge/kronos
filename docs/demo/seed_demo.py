"""Populate a throwaway DB with ~18 months of sample data for the README GIF.

Unlike `backend/seed.py` (90 days), this covers 2025-01-01 → today so the
Analytics tab has a full year-over-year comparison and a well-filled
"Year at a glance" heatmap showing every day type.

NEVER run this against your real data — it deletes all work entries first.
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
from app.models import Break, DayType, WorkEntry  # noqa: E402

RNG = random.Random(42)

START = date(2025, 1, 1)

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
    today = today or date.today()
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


def main() -> None:
    if not os.getenv("KRONOS_DATA_DIR"):
        sys.exit(
            "Refusing to run: KRONOS_DATA_DIR is unset, so this would wipe the "
            f"default DB at {DATA_DIR}. Point it at a disposable directory."
        )

    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        for existing in session.query(WorkEntry).all():
            session.delete(existing)
        session.flush()

        entries = build_entries()
        session.add_all(entries)
        session.commit()

        counts = {t.value: sum(1 for e in entries if e.day_type == t.value) for t in DayType}

    print(
        f"seeded {len(entries)} entries into {DATA_DIR} "
        f"({entries[0].date} to {entries[-1].date}): "
        + ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    )


if __name__ == "__main__":
    main()
