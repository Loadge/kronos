"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import date as date_
from enum import StrEnum

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class DayType(StrEnum):
    WORK = "work"
    VACATION = "vacation"
    SICK = "sick"
    HOLIDAY = "holiday"
    FLEX = "flex"

    @property
    def is_work(self) -> bool:
        return self is DayType.WORK

    @property
    def drains_pool(self) -> bool:
        """True for day types that consume accrued surplus hours (flex days)."""
        return self is DayType.FLEX

    @property
    def is_plannable(self) -> bool:
        """Leave you decide in advance: vacation, holiday, flex — not sick, not work."""
        return self in (DayType.VACATION, DayType.HOLIDAY, DayType.FLEX)


class WorkEntry(Base):
    __tablename__ = "work_entries"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    day_type: Mapped[str] = mapped_column(String(16), nullable=False, default=DayType.WORK.value)
    # The share of the day that ``day_type`` covers. 1.0 for every work day and
    # for whole-day leave; 0 < f < 1 for partial leave (3h of vacation on an 8h day is
    # 0.375), in which case start/end/breaks hold the hours worked in the rest of the day.
    # Stored as a fraction rather than hours so a whole day stays whole even if the
    # target timeline is edited later.
    fraction: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    breaks: Mapped[list[Break]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="Break.id",
        lazy="selectin",
    )

    def __init__(self, **kwargs) -> None:
        # Column defaults only apply at INSERT; the computations read ``fraction`` on
        # transient objects too (tests, seed), so make it a float from construction.
        kwargs.setdefault("fraction", 1.0)
        super().__init__(**kwargs)

    @property
    def total_break_minutes(self) -> int:
        return sum(b.break_minutes for b in self.breaks)

    @property
    def is_partial(self) -> bool:
        """True for a leave entry that covers only part of the day (the rest was worked)."""
        return self.day_type != DayType.WORK.value and self.fraction < 1.0


class Break(Base):
    __tablename__ = "breaks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_date: Mapped[date_] = mapped_column(
        Date,
        ForeignKey("work_entries.date", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    break_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)

    entry: Mapped[WorkEntry] = relationship(back_populates="breaks")


class Setting(Base):
    """Key-value configuration editable through the API."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)


class Plan(Base):
    """A drafted (not yet real) leave day for the time-off planner.

    Same shape as the leave part of a WorkEntry so committing is a straight copy. A
    draft never blocks a real entry on its date: the entry wins, the draft is shown as
    "already logged" until dismissed or committed (which just drops it).
    """

    __tablename__ = "plans"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    day_type: Mapped[str] = mapped_column(String(16), nullable=False)
    fraction: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("fraction", 1.0)
        super().__init__(**kwargs)


class Template(Base):
    """Named work-day template (start/end times + breaks). Stored server-side."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    breaks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
