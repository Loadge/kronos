"""The four number formats on the server: reading what a person typed, writing what a sheet prints.

The same table, ``tests/fixtures/number_cases.json``, is checked against the browser's copy of the
rules in ``tests/e2e/test_number_format.py``, so the two cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services import numbers
from app.services.timesheet import fmt_days, fmt_hours, fmt_money, fmt_signed

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "number_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES["parse"], ids=lambda c: f"{c['format']}:{c['text']!r}")
def test_parse_number(case):
    got = numbers.parse_number(case["text"], case["format"])
    if case["value"] is None:
        assert got is None
    else:
        assert got == pytest.approx(case["value"])


@pytest.mark.parametrize(
    "case", CASES["format"], ids=lambda c: f"{c['format']}:{c['value']}:{c['grouping']}"
)
def test_format_number(case):
    got = numbers.format_number(
        case["value"], case["decimals"], grouping=case["grouping"], tag=case["format"]
    )
    assert got == case["text"]


class TestTheNamedRules:
    """The cases the decision names, with their values written out."""

    def test_es_reads_the_spanish_way(self):
        assert numbers.parse_number("1.234,56", "es-ES") == 1234.56
        assert numbers.parse_number("1234,56", "es-ES") == 1234.56
        assert numbers.parse_number("55.000", "es-ES") == 55000

    def test_en_reads_the_english_way(self):
        assert numbers.parse_number("1,234.56", "en-US") == 1234.56
        assert numbers.parse_number("1234.56", "en-US") == 1234.56
        assert numbers.parse_number("55.000", "en-US") == 55

    def test_en_accepts_a_decimal_comma_when_nothing_else_separates(self):
        assert numbers.parse_number("12,5", "en-US") == 12.5
        assert numbers.parse_number("12,50", "en-US") == 12.5
        assert numbers.parse_number("12,500", "en-US") == 12500

    def test_an_unknown_format_reads_as_en_us(self):
        assert numbers.parse_number("1,234.5", "xx-XX") == 1234.5


class TestThePrintedSheetsFollowTheFormat:
    def test_the_default_prints_what_it_always_did(self):
        assert fmt_hours(7.5, "dec") == "7.50"
        assert fmt_signed(-1.25, "dec") == "−1.25"
        assert fmt_days(19.5) == "19.5"
        assert fmt_money(1234.5) == "€1,234.50"
        assert fmt_money(190, "USD") == "$190.00"

    def test_es_es_swaps_the_two_marks(self):
        with numbers.use_format("es-ES"):
            assert fmt_hours(7.5, "dec") == "7,50"
            assert fmt_hours(7.5, "hm") == "7:30"
            assert fmt_signed(-1.25, "dec") == "−1,25"
            assert fmt_days(19.5) == "19,5"
            assert fmt_money(1234.5) == "€1.234,50"
            assert fmt_money(0.01, "BTC") == "BTC 0,01000000"

    def test_the_format_does_not_outlive_its_block(self):
        with numbers.use_format("de-CH"):
            assert fmt_money(1234.5) == "€1’234.50"
        assert fmt_money(1234.5) == "€1,234.50"

    def test_a_format_it_does_not_know_falls_back(self):
        with numbers.use_format("xx"):
            assert fmt_money(1234.5) == "€1,234.50"
