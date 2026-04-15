"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import date as date_
from enum import Enum

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class DayType(str, Enum):
    WORK = "work"
    VACATION = "vacation"
    SICK = "sick"
    HOLIDAY = "holiday"

    @property
    def is_work(self) -> bool:
        return self is DayType.WORK


class WorkEntry(Base):
    __tablename__ = "work_entries"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    day_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DayType.WORK.value
    )
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    breaks: Mapped[list["Break"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="Break.id",
        lazy="selectin",
    )

    @property
    def total_break_minutes(self) -> int:
        return sum(b.break_minutes for b in self.breaks)


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

    entry: Mapped[WorkEntry] = relationship(back_populates="breaks")


class Setting(Base):
    """Key-value configuration editable through the API."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
