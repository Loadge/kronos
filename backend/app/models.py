"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


# ---------- freelance ------------------------------------------------------


class Account(Base):
    """Where the money lands: a bank account, a wallet, cash. Each has one currency.

    A payout paid into an account is in the account's currency, whatever its source bills in.
    At most one account is the default; one with payouts cannot be deleted (it is archived) nor
    change currency.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="bank")
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Which side of a payout it may be: "origin" sends, "destination" receives, "both" either.
    role: Mapped[str] = mapped_column(
        String(12), nullable=False, default="both", server_default="both"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    payouts: Mapped[list[FreelancePayout]] = relationship(
        back_populates="account", foreign_keys="FreelancePayout.account_id"
    )
    sent_payouts: Mapped[list[FreelancePayout]] = relationship(
        back_populates="from_account", foreign_keys="FreelancePayout.from_account_id"
    )


class IncomeSource(Base):
    """A client or activity freelance hours are billed to: a name, an hourly rate and a currency.

    One source is the default the Log form preselects. A source with blocks cannot be deleted
    (its blocks would lose their label): it is archived instead, which only hides it from the
    picker. Blocks snapshot the rate and currency when they are saved, so editing a source
    never rewrites the past.
    """

    __tablename__ = "income_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    hourly_rate: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # The account the Payout form preselects for this source (None: none).
    default_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    # The account it is usually paid from ("Paid from", beside "Paid into"; None: as billed).
    default_from_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )

    blocks: Mapped[list[FreelanceBlock]] = relationship(back_populates="source")
    payouts: Mapped[list[FreelancePayout]] = relationship(back_populates="source")


class FreelanceBlock(Base):
    """Hours worked as a freelancer: several per day if need be, each billed to one source.

    Independent of ``work_entries`` on purpose: a block never touches the employee's target,
    balance, streaks or the printable timesheet, and a Saturday of freelance work needs no
    employee entry. ``minutes`` is the duration (exact, unlike a float of hours); a block
    entered as a start and an end keeps them too. ``rate`` / ``currency`` are the source's
    at save time; ``fx_rate`` is the ECB's USD per EUR on the block's date (None for EUR, or
    when no rate was available), taken once and never fetched again.
    """

    __tablename__ = "freelance_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("income_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[IncomeSource] = relationship(back_populates="blocks", lazy="joined")

    @property
    def hours(self) -> float:
        return round(self.minutes / 60.0, 4)

    @property
    def amount(self) -> float:
        """What the block bills, in its own currency (unrounded)."""
        return self.rate * self.minutes / 60.0

    @property
    def amount_eur(self) -> float | None:
        """The block in euros: as is for EUR, divided by the day's USD-per-EUR rate for USD;
        None for a USD block without a rate (the summaries count it as missing)."""
        if self.currency == "EUR":
            return self.amount
        if self.fx_rate:
            return self.amount / self.fx_rate
        return None


class FreelancePayout(Base):
    """What one source actually paid for one ISO week.

    ``week_start`` is the Monday. ``currency`` is the account's when the payout went into one,
    else the source's (``account_id`` None: a row from before accounts, in the source's
    currency). ``fx_rate`` is units of that currency per EUR on the day the money landed (None
    for EUR, or when no rate was available), taken once and never fetched again; ``rate_source``
    says whose (ECB, CoinGecko, manual) and ``rate_date`` which day it is of. At most one payout
    per source and week.
    """

    __tablename__ = "freelance_payouts"
    __table_args__ = (
        UniqueConstraint("source_id", "week_start", name="uq_freelance_payouts_source_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("income_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    week_start: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rate_source: Mapped[str | None] = mapped_column(String(12), nullable=True)
    rate_date: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    # What was SENT (``amount``/``currency``/``account_id`` are what ARRIVED). ``sent_amount``
    # None means "as billed": a payout from before this was recorded, read as it always was.
    sent_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    sent_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    from_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    source: Mapped[IncomeSource] = relationship(back_populates="payouts", lazy="joined")
    account: Mapped[Account | None] = relationship(
        back_populates="payouts", lazy="joined", foreign_keys=[account_id]
    )
    from_account: Mapped[Account | None] = relationship(
        back_populates="sent_payouts", lazy="joined", foreign_keys=[from_account_id]
    )

    @property
    def amount_eur(self) -> float | None:
        """The payout in euros: as is for EUR, divided by its units-per-EUR rate otherwise;
        None for a payout in another currency without a rate."""
        if self.currency == "EUR":
            return self.amount
        if self.fx_rate:
            return self.amount / self.fx_rate
        return None


class FreelanceTaxYear(Base):
    """The tax inputs of one year (Freelance → Taxes). A year without a row of its own uses
    the latest earlier one; with no rows at all the defaults apply.

    Column names match ``tax.TaxParams``' fields (hours per day is a calculator assumption,
    taken from the request). ``set_aside_share`` is the part of every payment put by for
    the tax office (0.40).
    """

    __tablename__ = "freelance_tax_years"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    salary_annual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tarifa_plana: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    inicio_actividad: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    set_aside_share: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.4, server_default="0.4"
    )
    gestoria_annual: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    other_expenses: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
