"""Unit tests for break calculator + time parsing helpers."""

from __future__ import annotations

import pytest

from app.services.computations import (
    minutes_between,
    minutes_of,
    minutes_to_hours_label,
    parse_hhmm,
)


class TestParseHhmm:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("00:00", (0, 0)),
            ("09:05", (9, 5)),
            ("13:30", (13, 30)),
            ("23:59", (23, 59)),
        ],
    )
    def test_valid(self, value, expected):
        assert parse_hhmm(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "9:00",        # single-digit hour
            "09:0",        # single-digit minute
            "24:00",       # hour out of range
            "12:60",       # minute out of range
            "ab:cd",
            "09-00",       # wrong separator
            "  :  ",
            None,
            123,           # not a string
        ],
    )
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            parse_hhmm(value)


class TestMinutesBetween:
    @pytest.mark.parametrize(
        "start,end,expected",
        [
            ("09:00", "17:00", 8 * 60),
            ("13:30", "14:48", 78),
            ("00:00", "00:01", 1),
            ("08:15", "08:45", 30),
        ],
    )
    def test_valid(self, start, end, expected):
        assert minutes_between(start, end) == expected

    @pytest.mark.parametrize(
        "start,end",
        [
            ("09:00", "09:00"),  # equal
            ("10:00", "09:30"),  # end before start
            ("23:00", "00:30"),  # would require overnight; not supported
        ],
    )
    def test_rejects_non_monotonic(self, start, end):
        with pytest.raises(ValueError):
            minutes_between(start, end)


class TestMinutesOf:
    def test_round_trip(self):
        assert minutes_of("00:00") == 0
        assert minutes_of("01:00") == 60
        assert minutes_of("13:45") == 13 * 60 + 45


class TestMinutesToHoursLabel:
    @pytest.mark.parametrize(
        "minutes,label",
        [
            (0, "0min"),
            (1, "1min"),
            (45, "45min"),
            (60, "1h"),
            (61, "1h 1min"),
            (80, "1h 20min"),
            (120, "2h"),
            (600, "10h"),
            (605, "10h 5min"),
        ],
    )
    def test_formats(self, minutes, label):
        assert minutes_to_hours_label(minutes) == label

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            minutes_to_hours_label(-1)
