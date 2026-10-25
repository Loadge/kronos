# Kronos — Build Phases

Personal work-hours tracker. Single-user, no auth — trusted network only.
Stack: FastAPI + SQLite + Alpine.js + Pico CSS. Mirrors Lorca's structural patterns.

**Completed phases live in `BUILD_PHASES_ARCHIVE.md`** (decisions, what shipped, known limits; read
it for the history of a decision, not by default). This file keeps only open and unconfirmed work.

---

## Done (archived in `BUILD_PHASES_ARCHIVE.md`)

| Phase | What | Landed |
|---|---|---|
| 1–10 | Base app: scaffolding, entry CRUD, Log / Dashboard / Days / Analytics / Settings tabs, backup and CSV export, UX polish, calendar picker | before git history |
| 11 | Bulk date logging | `ac562e1` |
| 12 | Server-side templates | `5409030` |
| 13 | Clock in / clock out | `e514613` |
| 14 | Public holidays from Nager.Date (+ preview) | `0679290`, `cee88f8` |
| 16 | Notes search | `d688dea` |
| 17 | Week view | no commit of its own |
| 18 | Streaks & milestones | `8248dd5` |
| 19 | CSV import | `01f4de5` |
| 22 | Log tab UI overhaul | `0e9d347` |
| 23 | Date-effective daily target | `31bd9ba` |
| 27 | Spanish holidays from the BOE (+ list under the preview) | `bfdffe1`, `a1c8bff` |

---

## Open phases

Suggested order (2026-10-25): 24 → 26 → 25 (26 is a low-risk break between the two halves of the
leave work), then 29. 28 starts with its spike; 30 only if logging from the phone outside the LAN
turns out to be common.

### Phase 24 — Half-Day Leave (planned)

Vacation / sick / holiday / flex are whole-day only. Real leave is often a half-day
(a morning off, a half-day sick). Add 0.5-day granularity to non-work entries.

- Non-work entries gain a fraction (1.0 / 0.5); a half-day charges half the day's target
  against the surplus pool and counts as 0.5 against the vacation budget.
- Log tab + bulk logging expose the half-day option; Days/Week/dashboard reflect it.
- Vacation-budget math and `summarize()` account for fractional non-work days.
- A model change (Alembic migration) that reaches almost every computation: backup/restore and the
  CSV import/export must round-trip the fraction, and old backups must still load as whole days.

### Phase 25 — Time-Off Planner (planned)

Kronos is retrospective — you log what already happened. The planner is forward-looking:
pencil in future vacation/holiday/flex and see the projected cumulative balance and
remaining vacation budget **before** the days arrive. Builds on the existing vacation
budget + forecast, the date-effective target (Phase 23), and half-day leave (Phase 24).

- A planning view where future non-work days can be drafted (not yet real entries).
- Live projection: cumulative balance and vacation budget remaining as-of year end, given
  the drafted days.
- "Commit" turns drafts into real entries via the existing batch endpoint.

### Phase 26 — Printable Timesheet / PDF Export (planned)

A cleanly formatted monthly or annual timesheet for records, an employer, or invoicing.
Independent of the other phases — pure output layer, no model changes.

- Print-optimized HTML view (period picker → formatted table + totals) that the browser
  can save to PDF; no server-side PDF dependency required.
- Reuses the existing period/summary computations; shows per-day rows + period totals.

### Phase 28 — Log Without Typing (idea, spike first)

Kronos proposes the day from signals that already exist and Miguel only confirms it: the work PC's
power-on / power-off events, presence in Home Assistant, and optionally Anselmo over Telegram ("hoy
entré a las 8:30, comí 45 min"), with the local LLM extracting the times from the text.

- **Spike first, before any build:** do the signals give reliable start/end times or just noise?
  Compare a few weeks of signals against the logged days.
- A proposal is never an entry until confirmed; nothing overwrites a logged day.
- Boundary with **jornada**: Kronos is publicly mirrored and nothing from jornada may go into it.
  An idea of Kronos' own is fine; copying jornada's design is not.

### Phase 29 — BOE Resolution Discovery (planned)

Phase 27 left a yearly chore: add next year's BOE id to `BOE_RESOLUTIONS` each October. Find it
instead: search the BOE summary for the "relación de fiestas laborales para el año N" resolution,
check it parses like the fixtures, keep the hand-written table as the fallback.

- While there: Canarias' island holidays and Arán's substitution, which live in the table's
  footnotes and are not imported today.

### Phase 30 — Offline PWA (idea)

The service worker caches only the app shell. Queue writes made offline on the phone (clock in/out,
save a day) and sync them on reconnect, resolving conflicts per date. Serious frontend and e2e work;
worth it only if logging from the phone outside the LAN is common.

---

## Small items

- **PROD data from the Phase 27 check (2026-10-16):** 1-may is stored as `vacation`, and 12-jun /
  19-jun as holidays without a note. Left for Miguel to decide.
- **`IMPROVEMENTS.md`** (git-ignored, local only) is a superseded backlog (see its banner); delete
  it or fold what's left in here.

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
