"""API tests for the printable timesheet page and the profile settings it reads."""

from __future__ import annotations

import re

TODAY = "2026-10-26"


def _work(date, start="09:00", end="18:00", breaks=(60,)):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


def _get(client, **params):
    return client.get("/timesheet", params={"today": TODAY, **params})


def _rows(html):
    """(date, row class) for every day row."""
    return re.findall(r'<tr class="(row-[a-z]+[^"]*)" data-date="(\d{4}-\d{2}-\d{2})"', html)


class TestPage:
    def test_defaults_to_this_month_up_to_today(self, client):
        r = _get(client)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        dates = [d for _, d in _rows(r.text)]
        assert dates[0] == "2026-10-01" and dates[-1] == TODAY
        assert "1 Oct – 26 Oct 2026" in r.text

    def test_month_range_lists_every_calendar_day(self, client):
        r = _get(client, **{"from": "2026-09-01", "to": "2026-09-30"})
        rows = _rows(r.text)
        assert len(rows) == 30
        assert "September 2026" in r.text
        by = dict((d, c) for c, d in rows)
        assert "we" in by["2026-09-05"]  # Saturday shaded
        assert by["2026-09-02"].startswith("row-gap")  # past work day, unlogged
        assert "not logged" in r.text

    def test_rows_and_totals(self, client):
        client.post("/api/entries", json=_work("2026-09-01", end="19:00"))  # 9h → +1
        client.post(
            "/api/entries", json={"date": "2026-09-02", "day_type": "holiday", "notes": "fiesta"}
        )
        client.post(
            "/api/entries",
            json={
                "date": "2026-09-03",
                "day_type": "vacation",
                "fraction": 0.5,
                "start_time": "09:00",
                "end_time": "13:00",
            },
        )
        r = _get(client, **{"from": "2026-09-01", "to": "2026-09-03", "notes": 1})
        html = r.text
        assert "row-work" in html and "row-leave" in html and "row-partial" in html
        assert "vacation</span> · 4h" in html
        assert "fiesta" in html
        assert "+1.00" in html  # delta and running
        # Totals: net 13, target 12, balance +1, 1.5 work days, 1.5 off
        assert "13.00" in html and "12.00" in html
        assert "1.5 work days, 1.5 off" in html

    def test_whole_day_leave_prints_blank_numbers_in_full_detail(self, client):
        client.post("/api/entries", json={"date": "2026-09-02", "day_type": "flex"})
        html = _get(client, **{"from": "2026-09-02", "to": "2026-09-02"}).text
        row = re.search(r'<tr class="row-leave"[^>]*>(.*?)</tr>', html, re.S).group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        # day, dow, type, start, end, breaks, net, target, delta, running
        assert cells[6].strip() == "" and cells[7].strip() == "" and cells[8].strip() == ""
        assert "−8.00" in cells[9]

    def test_compact_hides_target_delta_running(self, client):
        full = _get(client, detail="full").text
        compact = _get(client, detail="compact").text
        assert '<th class="n">Σ</th>' in full
        assert '<th class="n">Σ</th>' not in compact

    def test_hours_formats(self, client):
        client.post("/api/entries", json=_work("2026-09-01", end="18:30"))  # 8.5h
        dec = _get(client, **{"from": "2026-09-01", "to": "2026-09-01"}).text
        hm = _get(client, **{"from": "2026-09-01", "to": "2026-09-01", "hours": "hm"}).text
        assert '<td class="n">8.50</td>' in dec and '<td class="n">8:30</td>' not in dec
        assert '<td class="n">8:30</td>' in hm and "Hours as h:mm" in hm

    def test_multi_month_has_sections_and_subtotals(self, client):
        html = _get(client, **{"from": "2026-08-01", "to": "2026-09-30"}).text
        assert html.count('<tr class="month">') == 2
        assert "Aug subtotal" in html and "Sep subtotal" in html
        assert "August – September 2026" in html

    def test_year_label(self, client):
        html = _get(client, **{"from": "2025-01-01", "to": "2025-12-31"}).text
        assert '<div class="period">2025</div>' in html
        assert html.count('<tr class="month">') == 12

    def test_signatures_and_theme(self, client):
        html = _get(client, sign=1, theme="dark").text
        assert "Employee · signature and date" in html
        assert '<html lang="en" data-theme="dark">' in html
        assert "signature" not in _get(client).text.split("<main")[1].split("</main")[0]

    def test_future_days_are_not_gaps(self, client):
        html = _get(client, **{"from": "2026-10-26", "to": "2026-10-30"}).text
        rows = dict((d, c) for c, d in _rows(html))
        assert rows["2026-10-26"].startswith("row-gap")
        assert rows["2026-10-27"].startswith("row-empty")

    def test_target_line_shows_the_schedule_in_force(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2026-01-01", "hours": 8},
                    {"effective_from": "2026-09-15", "hours": 6},
                ]
            },
        )
        html = _get(client, **{"from": "2026-09-01", "to": "2026-09-30"}).text
        assert "Daily target: <strong>6h / 8h</strong>" in html

    def test_custom_work_week_in_meta(self, client):
        client.put("/api/config", json={"work_week_days": [0, 1, 2, 3]})
        assert "Work week: Mon, Tue, Wed, Thu" in _get(client).text


class TestValidation:
    def test_to_before_from(self, client):
        assert _get(client, **{"from": "2026-09-02", "to": "2026-09-01"}).status_code == 422

    def test_range_too_long(self, client):
        assert _get(client, **{"from": "2020-01-01", "to": "2026-01-01"}).status_code == 422

    def test_bad_enum(self, client):
        assert _get(client, detail="huge").status_code == 422
        assert _get(client, hours="min").status_code == 422
        assert _get(client, theme="sepia").status_code == 422

    def test_bad_date(self, client):
        assert _get(client, **{"from": "yesterday"}).status_code == 422


class TestProfile:
    def test_profile_round_trip(self, client):
        r = client.put(
            "/api/config",
            json={
                "profile_name": " Juan Pérez ",
                "profile_employer": "ACME",
                "profile_extra": "nº 4711",
            },
        )
        assert r.status_code == 200
        cfg = client.get("/api/config").json()
        assert cfg["profile_name"] == "Juan Pérez"  # stripped
        assert cfg["profile_employer"] == "ACME"
        assert cfg["profile_extra"] == "nº 4711"

    def test_profile_defaults_empty(self, client):
        cfg = client.get("/api/config").json()
        assert (cfg["profile_name"], cfg["profile_employer"], cfg["profile_extra"]) == ("", "", "")

    def test_profile_prints_in_the_header_only_when_set(self, client):
        assert '<div class="who">' not in _get(client).text
        client.put("/api/config", json={"profile_name": "Juan Pérez", "profile_employer": "ACME"})
        html = _get(client).text
        assert "<strong>Juan Pérez</strong>" in html and "ACME" in html
        assert "Timesheet · 1 Oct – 26 Oct 2026 · Juan Pérez" in html  # <title>

    def test_profile_too_long_rejected(self, client):
        assert client.put("/api/config", json={"profile_name": "x" * 121}).status_code == 422

    def test_profile_in_backup_and_restore(self, client):
        client.put("/api/config", json={"profile_name": "Juan", "profile_extra": "team"})
        backup = client.get("/api/backup").json()
        assert backup["settings"]["profile_name"] == "Juan"
        client.put("/api/config", json={"profile_name": "", "profile_extra": ""})
        assert client.post("/api/restore", json=backup).status_code == 200
        cfg = client.get("/api/config").json()
        assert (cfg["profile_name"], cfg["profile_extra"]) == ("Juan", "team")

    def test_old_backup_without_profile_restores(self, client):
        client.put("/api/config", json={"profile_name": "Juan"})
        old = {
            "version": 1,
            "settings": {"daily_target_hours": 8, "cumulative_start_date": "2025-01-01"},
        }
        assert client.post("/api/restore", json=old).status_code == 200
        assert client.get("/api/config").json()["profile_name"] == ""  # the file had none
