"""Unit tests for app.services.tax, the single source of the tax and rate maths.

Every expected number below is worked out by hand in the comment next to it (a calculator, not the
module's own formulas), with the 2026 figures of app/data/fiscal_es.json. The two anchor cases:
$100/h x 2 h/day x 220 days on top of a 55,000 EUR salary (pluriactividad), and
$100/h x 8 h/day x 220 days with no salary, both at 1.1172 USD per EUR (ECB, 2026-10-30), gestoria
600 EUR a year, no other expenses, Andalucia.

Why these numbers matter: a flat model (20% x 1.95, RETA 300/month, $1 = 1 EUR, 261 days)
says $100/h full time is 124,806 EUR net; an honest estimate is ~93,400. A test that cannot
notice the difference between those is not testing anything.
"""

from __future__ import annotations

import ast
import dataclasses
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services import tax

FX = 1.1172  # USD per EUR
SIDE = tax.TaxParams(gestoria_annual=600, other_expenses=0, hours_per_day=2, salary_annual=55000)
FULL = tax.TaxParams(gestoria_annual=600, other_expenses=0, hours_per_day=8)
GROSS_SIDE = 100 * 2 * 220 / FX  # 44,000 USD = 39,384.1747 EUR
GROSS_FULL = 100 * 8 * 220 / FX  # 176,000 USD = 157,536.6989 EUR


def with_(p: tax.TaxParams, **kw) -> tax.TaxParams:
    return dataclasses.replace(p, **kw)


def test_side_job_on_top_of_the_salary():
    f = tax.figures(GROSS_SIDE, SIDE, 2026)
    assert f.gross == pytest.approx(39384.1747, abs=1e-4)
    # RETA: (39384.1747 - 600) * 0.93 / 12 = 36069.2825 / 12 = 3005.7735 EUR/month
    #   -> 2760 < x <= 3190: tramo 11 (general table tramo 8), minimum base 1437.91
    #   -> 1437.91 * 0.315 * 12 = 5435.2998
    assert f.reta_monthly_yield == pytest.approx(3005.7735, abs=1e-4)
    assert (f.reta_tramo, f.reta_base) == (11, 1437.91)
    assert f.reta_annual == pytest.approx(5435.2998, abs=1e-4)
    # activity: 39384.1747 - 600 - 5435.2998 = 33348.8749; 5% hard-to-justify = 1667.4437 (< 2000)
    #   -> net yield 31681.4312
    assert f.hard_to_justify == pytest.approx(1667.4437, abs=1e-4)
    assert f.taxable == pytest.approx(31681.4312, abs=1e-4)
    # salary: 55000 - 55000 * 0.065 (3575) - 2000 = 49425
    assert f.employment_net == pytest.approx(49425, abs=1e-9)
    # tax(49425): state 1182.75 + 930 + 2250 + 14225 * .185 (2631.625) = 6994.375 - 527.25
    #   = 6467.125; Andalucia 1235 + 972 + 2115 + 2631.625 = 6953.625 - 550.05 = 6403.575
    #   -> 12870.70
    # tax(49425 + 31681.4312 = 81106.4312): state 1182.75 + 930 + 2250 + 4588
    #   + 21106.4312 * .225 (4748.9470) = 13699.6970 - 527.25 = 13172.4470; Andalucia 1235 + 972
    #   + 2115 + 4588 + 4748.9470 = 13658.9470 - 550.05 = 13108.8970 -> 26281.3440
    # freelance IRPF = 26281.3440 - 12870.70 = 13410.6440, 42.3% of the net yield: the marginal
    # 37% / 45% on top of the salary, not the 20% the 130 takes
    assert f.irpf == pytest.approx(13410.6440, abs=1e-3)
    assert f.irpf_effective == pytest.approx(0.4233, abs=1e-4)
    # 130: 31681.4312 * 0.20 = 6336.2862; Renta: 13410.6440 - 6336.2862 = 7074.3578
    assert f.pago_fraccionado == pytest.approx(6336.2862, abs=1e-3)
    assert f.renta == pytest.approx(7074.3578, abs=1e-3)
    # net: 39384.1747 - 600 - 5435.2998 - 13410.6440 = 19938.2309
    assert f.net == pytest.approx(19938.2309, abs=1e-3)
    # pluriactividad refund: salary CC 55000 * .283 = 15565; RETA CC 1437.91 * .283 * 12 = 4883.1424
    #   excess over 17323.68 = 3124.4624, half = 1562.2312 (cap: half of 4883.1424 = 2441.57)
    assert f.reintegro == pytest.approx(1562.2312, abs=1e-3)
    assert f.fiscal_year == 2026
    assert f.region == "Andalucía"


def test_full_time_without_salary():
    f = tax.figures(GROSS_FULL, FULL, 2026)
    # RETA: (157536.6989 - 600) * 0.93 / 12 = 12162.5942/month -> last tramo, base 1928.10
    #   -> 1928.10 * 0.315 * 12 = 7288.218
    assert (f.reta_tramo, f.reta_base) == (15, 1928.10)
    assert f.reta_annual == pytest.approx(7288.218, abs=1e-6)
    # 157536.6989 - 600 - 7288.218 = 149648.4809; 5% = 7482.42 -> capped at 2000 -> 147648.4809
    assert f.hard_to_justify == 2000
    assert f.taxable == pytest.approx(147648.4809, abs=1e-3)
    # tax(147648.4809): state 1182.75 + 930 + 2250 + 4588 + 87648.4809 * .225 (19720.9082)
    #   = 28671.6582 - 527.25 = 28144.4082; Andalucia 1235 + 972 + 2115 + 4588 + 19720.9082
    #   = 28630.9082 - 550.05 = 28080.8582 -> 56225.2664
    assert f.employment_net == 0
    assert f.irpf == pytest.approx(56225.2664, abs=1e-3)
    # 130: 147648.4809 * 0.2 = 29529.6962
    assert f.pago_fraccionado == pytest.approx(29529.6962, abs=1e-3)
    # net 157536.6989 - 600 - 7288.218 - 56225.2664 = 93423.2143
    assert f.net == pytest.approx(93423.2143, abs=1e-3)
    assert f.reintegro == 0  # no salary, no pluriactividad


def test_tarifa_plana_replaces_the_tramo_cuota():
    f = tax.figures(GROSS_SIDE, with_(SIDE, tarifa_plana=True), 2026)
    # 88.64 * 12 = 1063.68; the tramo is still worked out (the page shows what comes after)
    assert f.reta_annual == pytest.approx(1063.68, abs=1e-9)
    assert f.reta_tramo == 11
    # no refund estimate under the tarifa plana (its common-contingency part is not published)
    assert f.reintegro == 0
    # net yield: 39384.1747 - 600 - 1063.68 = 37720.4947; 5% = 1886.0247 -> 35834.4700
    assert f.taxable == pytest.approx(35834.4700, abs=1e-3)


def test_startup_reduction_takes_20_percent_off_the_taxable_yield_but_not_off_the_130():
    f = tax.figures(GROSS_FULL, with_(FULL, inicio_actividad=True), 2026)
    # 147648.4809 * 0.2 = 29529.6962 off: taxable 118118.7847; the 130 still on 147648.4809
    assert f.startup_reduction == pytest.approx(29529.6962, abs=1e-3)
    assert f.taxable == pytest.approx(118118.7847, abs=1e-3)
    assert f.pago_fraccionado == pytest.approx(29529.6962, abs=1e-3)
    # tax(118118.7847): state 8950.75 + 58118.7847 * .225 (13076.7266) = 22027.4766 - 527.25
    #   = 21500.2266; Andalucia 8910 + 13076.7266 = 21986.7266 - 550.05 = 21436.6766 -> 42936.9032
    assert f.irpf == pytest.approx(42936.9032, abs=1e-3)


@pytest.mark.parametrize(
    ("monthly", "tramo", "base"),
    [
        (0, 1, 653.59),
        (670, 1, 653.59),  # the limit belongs to the lower tramo ("<= 670")
        (670.01, 2, 718.95),
        (1166.7, 3, 849.67),
        (1166.71, 4, 950.98),
        (6000, 14, 1732.03),
        (6000.01, 15, 1928.10),
    ],
)
def test_reta_tramo_limits(monthly, tramo, base):
    assert tax.reta_tramo(monthly, tax.rules_for(2026)) == (tramo, base)


def test_scale_tax_slices_the_base():
    s = ((10.0, 0.1), (20.0, 0.2), (None, 0.5))
    # 10 * .1 = 1; + 10 * .2 = 2 -> 3; + 5 * .5 = 2.5 -> 5.5
    assert tax.scale_tax(25, s) == pytest.approx(5.5)
    assert tax.scale_tax(10, s) == pytest.approx(1)
    assert tax.scale_tax(0, s) == 0
    assert tax.scale_tax(-5, s) == 0


def test_income_tax_is_zero_up_to_the_minimums():
    r = tax.rules_for(2026)
    assert tax.income_tax(5000, r) == 0
    # 5700: state 5700 * .095 - 5550 * .095 = 14.25; Andalucia below its 5790 minimum -> 0
    assert tax.income_tax(5700, r) == pytest.approx(14.25)


def test_a_loss_lowers_the_tax_on_the_salary():
    # no income at all: RETA tramo 1 (653.59 * .315 * 12 = 2470.5702) and the gestoria are paid
    f = tax.figures(0, SIDE, 2026)
    assert f.reta_annual == pytest.approx(2470.5702, abs=1e-4)
    # yield -3070.5702 (no 5%, no reduction on a loss); it comes off the salary's 49425 at 37%
    # (18.5 + 18.5): -3070.5702 * .37 = -1136.1110
    assert f.taxable == pytest.approx(-3070.5702, abs=1e-4)
    assert f.irpf == pytest.approx(-1136.1110, abs=1e-3)
    assert f.pago_fraccionado == 0
    assert f.net == pytest.approx(-600 - 2470.5702 + 1136.1110, abs=1e-3)


def test_a_later_year_uses_the_latest_block_and_says_so():
    assert tax.rules_for(2027).year == 2026
    assert tax.rules_for(2030).year == 2026
    assert tax.rules_for(2020).year == 2026  # nothing earlier: the earliest block there is
    assert tax.figures(GROSS_FULL, FULL, 2027).net == tax.figures(GROSS_FULL, FULL, 2026).net


def test_a_year_with_its_own_block_uses_it(monkeypatch):
    real = tax._blocks()[2026]
    later = {**real, "irpf": {**real["irpf"], "pago_fraccionado": 0.3}}
    monkeypatch.setattr(tax, "_blocks", lambda: {2026: real, 2028: later})
    assert [tax.rules_for(y).year for y in (2026, 2027, 2028, 2029)] == [2026, 2026, 2028, 2028]
    assert tax.rules_for(2028).pago_fraccionado == 0.3


def test_net_from_rate_is_figures_of_rate_times_days():
    # 800 EUR/day x 220 = 176,000 EUR gross
    assert tax.net_from_rate(800, 220, FULL, 2026) == tax.figures(176000, FULL, 2026).net


def test_rate_from_net_round_trips():
    for p in (SIDE, FULL, with_(FULL, tarifa_plana=True, inicio_actividad=True)):
        for target in (0, 15000, 50000, 93423.21, 250000):
            rate = tax.rate_from_net(target, 220, p, 2026)
            assert rate is not None
            assert tax.net_from_rate(rate, 220, p, 2026) >= target - 1e-6
            # and a cent a day less does not reach it (away from a tramo step)
            assert tax.net_from_rate(rate - 0.01, 220, p, 2026) < target


def test_rate_from_net_full_time_anchor():
    # the inverse of the full-time anchor: net 93423.2143 at 220 days comes from 800 EUR/day
    # (= $100 x 8 h / 1.1172 = 716.0759 EUR/day)
    rate = tax.rate_from_net(93423.2143, 220, FULL, 2026)
    assert rate == pytest.approx(800 / FX, abs=1e-3)


@pytest.mark.parametrize(("net", "billable"), [(85000, 0), (85000, -1), (-1, 220)])
def test_rate_from_net_none(net, billable):
    assert tax.rate_from_net(net, billable, FULL, 2026) is None


def test_rate_from_net_none_past_the_ceiling():
    assert tax.rate_from_net(1e12, 220, FULL, 2026) is None


def test_month_figures_share_the_year():
    days = (18, 20, 0, 22, 19, 21, 23, 10, 21, 22, 20, 20)  # 216 in all
    annual = tax.figures(450 * 216, FULL, 2026)
    months = [tax.month_figures(450, d, annual) for d in days]
    # the twelve months add up to the year: the Dashboard's months and its total cannot disagree
    assert sum(g for g, _ in months) == pytest.approx(annual.gross)
    assert sum(n for _, n in months) == pytest.approx(annual.net)
    # an empty month still pays its twelfth of the gestoria and the RETA, and no IRPF
    assert months[2] == (0, pytest.approx(-(600 + annual.reta_annual) / 12))


def test_hourly_daily_conversion():
    # $100/h x 2 h = 200 per day, and back
    assert tax.hourly_to_daily(100, SIDE) == 200
    assert tax.daily_to_hourly(200, SIDE) == 100
    p = with_(FULL, hours_per_day=7.5)
    assert tax.daily_to_hourly(450, p) == 60
    assert tax.hourly_to_daily(60, p) == 450


def test_round_half_up_is_half_up_not_bankers():
    # Python's round(2.5) is 2 and round(0.5) is 0; money rounds a half up, as the browser does
    assert (round(2.5), round(0.5)) == (2, 0)
    assert tax.round_half_up(2.5) == 3
    assert tax.round_half_up(0.5) == 1
    assert tax.round_half_up(1.5) == 2
    assert tax.round_half_up(0.4) == 0


def test_round_half_up_sends_a_negative_half_away_from_zero():
    # the half goes away from zero, whatever the sign, like Intl.NumberFormat and the
    # PDF (which rounds the magnitude). JavaScript's Math.round(-2.5) is -2; this is -3 on purpose.
    assert tax.round_half_up(-2.5) == -3
    assert tax.round_half_up(-0.5) == -1
    assert tax.round_half_up(-2.4) == -2
    assert tax.round_half_up(-2.6) == -3
    assert tax.round_half_up(-0.125, 2) == -0.13


def test_round_half_up_returns_float_equal_to_an_integer():
    r = tax.round_half_up(2.5)
    assert isinstance(r, float)
    assert r == 3.0


def test_round_half_up_never_returns_negative_zero():
    assert math.copysign(1.0, tax.round_half_up(-0.001, 2)) == 1.0
    assert math.copysign(1.0, tax.round_half_up(-0.4)) == 1.0


def test_round_half_up_decimals_follow_the_binary_product_like_javascript():
    # 1.005 * 100 = 100.49999999999999 in binary floating point, so the browser's
    # Math.round(1.005 * 100) / 100 gives 1 (not 1.01); Python must give the same number
    assert tax.round_half_up(1.005, 2) == 1
    # 1.255 * 100 = 125.49999999999999 -> 125 -> 1.25;  2.675 * 100 is exactly 267.5 -> 268 -> 2.68
    assert tax.round_half_up(1.255, 2) == 1.25
    assert tax.round_half_up(2.675, 2) == 2.68
    # plain cases: 3.14159 * 100 + 0.5 = 314.659 -> 314 -> 3.14
    # and 0.126 * 100 + 0.5 = 13.1 -> 13 -> 0.13
    assert tax.round_half_up(3.14159, 2) == 3.14
    assert tax.round_half_up(0.126, 2) == 0.13


def test_round_half_up_leaves_a_huge_figure_alone():
    # 2**52 + 1 + 0.5 is not representable and would round to the even 2**52 + 2: past 2**52 a
    # figure has no fraction, so it is returned as it is
    assert tax.round_half_up(2.0**52 + 1, 0) == 2.0**52 + 1
    assert tax.round_half_up(1e300, 2) == 1e300
    assert tax.money(1e13 + 0.125) == 10000000000000.13  # still below 2**52 cents: a real tie


def test_round_half_up_raises_where_the_scaled_figure_overflows():
    # /api/calc turns this into a 422 "Input too large" (tests/test_calc_api.py)
    with pytest.raises(OverflowError):
        tax.round_half_up(1e307, 2)
    with pytest.raises(OverflowError):
        tax.round_half_up(math.inf, 2)


def test_money_never_raises_and_returns_a_huge_figure_as_it_is():
    assert tax.money(1e307) == 1e307
    assert tax.money(math.inf) == math.inf


def test_money_rounds_an_exact_half_cent_up():
    # 0.125, 33125.625 and 0.375 are exact in binary, so these are true ties: Python's round()
    # gives the even cent (0.12, 33125.62), money gives the upper one
    assert (round(0.125, 2), round(33125.625, 2)) == (0.12, 33125.62)
    assert tax.money(0.125) == 0.13
    assert tax.money(33125.625) == 33125.63
    assert tax.money(0.375) == 0.38
    assert tax.money(-0.125) == -0.13
    assert tax.money(2.5) == 2.5  # a figure already in cents is left alone


def test_params_from_config_copies_the_tax_inputs():
    cfg = SimpleNamespace(
        gestoria_annual=2,
        other_expenses=3,
        hours_per_day=6,
        salary_annual=7,
        tarifa_plana=1,
        inicio_actividad=0,
        daily_rate=999,  # not a tax input, must be ignored
    )
    assert tax.TaxParams.from_config(cfg) == tax.TaxParams(2, 3, 6, 7, True, False)


def test_params_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        FULL.salary_annual = 0  # type: ignore[misc]


def test_tax_module_is_pure():
    """The point of the module is that nothing web or DB can leak into the maths: it reads its
    figures from a JSON file next to it and nothing else."""
    src = Path(tax.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    allowed = {"__future__", "math", "dataclasses", "json", "functools", "pathlib", "typing"}
    assert imported <= allowed, imported


def test_fiscal_file_is_well_formed():
    """Each block a later year may copy: scales ascending and ending open, rates in (0, 1)."""
    import json

    data = json.loads(tax.FISCAL_FILE.read_text(encoding="utf-8"))
    for year in data["years"]:
        r = tax.rules_for(int(year))
        scales = [r.reta_tramos, r.state_scale, r.region_scale]
        for s in scales:
            limits = [hi for hi, _ in s]
            assert limits[-1] is None
            assert limits[:-1] == sorted(limits[:-1])
        for _, rate in (*r.state_scale, *r.region_scale):
            assert 0 < rate < 1
        bases = [b for _, b in r.reta_tramos]
        assert bases[3:] == sorted(bases[3:])  # the general table never goes down
