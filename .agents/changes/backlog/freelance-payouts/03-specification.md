# Phase 37 - Freelance payouts

Kronos estimates freelance money as hours times the rate stored on each block. A "payout" is what one income source actually paid for one ISO week, and wherever one exists it is the money Kronos uses for that source and week, instead of the estimate. Without a payout, the estimate stays. No new page: payouts are typed in Days and read everywhere else.

# Data

A new table, `freelance_payouts`, with one row per source and ISO week:

- `source_id` (FK to `income_sources`), `week_start` (the Monday), unique together
- `amount` in the source's currency, plus `currency` copied from the source at save (like the blocks' snapshot)
- `fx_rate`: for USD, the ECB rate of the week's Sunday through `fx.for_date()` (a weekend takes the last published day), editable; `null` when there is no rate, and then the payout is counted as missing, never at 1:1
- `note`, optional

A source with payouts cannot be deleted (409), only archived, as with blocks. `DELETE /api/data` wipes payouts with the blocks. The backup goes to version 4 and carries the payouts; versions 1 to 3 still restore, and the fidelity test populates payouts too.

# How the money is counted

For a source and week with a payout:

- The money of that source in that week is the payout in euros. The hours are still the blocks' hours, so the €/h of that week, month and year moves accordingly.
- The payout is spread over the days of the week pro-rata by each day's block estimate in euros. That share is what goes into each month, quarter (the 130) and year, so a week from 29 December to 4 January splits between the two tax years by work date.
- With no blocks of that source in the week, the payout counts with 0h on the week's Sunday.
- Blocks keep their stored estimate. Adding, editing or deleting a block in a paid week changes the hours and the spread, never the payout.
- A block without an exchange rate in a paid week does not matter for the money (the payout decides it), but it still counts as missing for the spread; the spread then uses the hours of the blocks instead of their euros if no block of the week has euros.

Every sum in `services/freelance.py` goes through this one rule: the summary (totals, this week, this month, per month, per source), the 130s, the projection's realised €/h, the dashboard card and the Analytics ledger and income series. The summary reports both parts: `paid_out_eur` and `estimated_eur` next to the total, and a count of past weeks with blocks and no payout.

# Screens

- **Days, ⚡ Freelance.** Inside each month section, a header per ISO week ("W44, Oct 26 - Nov 1"). Per source with blocks or a payout that week: the hours, the estimate, and the payout field (empty means "use the estimate"). With a payout, the gap ("+$360") and the week's €/h; past weeks with blocks and no payout show a quiet "awaiting payout"; a payout without blocks shows "payout with no hours". Saving is like Settings: on its own after typing, with "saved" in the header. Deleting a payout offers Undo in the ribbon. A USD payout shows its exchange rate and lets it be edited. The source filter and the year filter apply to the headers too.
- **Log, ⚡ card.** When the selected day's week has a payout for a source, one read-only line: "W44 payout $3,000", with a link to the week in Days.
- **Freelance tab.** The hero shows the total and the split ("€7,400 paid out, €1,800 estimated"); the monthly bars show the paid-out part solid and the estimated part in a lighter shade, plus the planned part dashed as today.
- **Dashboard card and Analytics.** The same split, in words, next to the totals of the week, the month and the range.
- **Freelance PDF** (`/timesheet/freelance`). The block rows stay. Under each week that has a payout, a line with the payout and its gap to the estimate; the totals use the payouts.
- **CSV.** `GET /api/freelance/payouts.csv`, one row per payout, next to the blocks' CSV in Export.

The names on screen: "payout", "paid out", "estimated", "awaiting payout".

# Order of work

1. Archive Phases 34 and 35 (confirmed by Miguel on 2026-11-04 in this interview) and add Phase 37 to `docs\BUILD_PHASES.md`. Check: one `docs:` commit, the Done table has the rows.
2. Mockups in `docs\mockups\`: the Days week header (phone and desktop) and the Freelance hero and bars with the split. Check: Miguel picks.
3. Data: model, migration, CRUD under `/api/freelance/payouts`, backup v4, wipe and delete rules. Check: models and migrations test green, API tests, the fidelity test with payouts, a red control.
4. The money rule in `services/freelance.py` and everything that reads it (summary, 130s, projection, Analytics). Check: unit tests by hand on a week that crosses a year, a payout without blocks, a missing exchange rate, a block edited after the payout; employee numbers unchanged.
5. Days week headers and the Log line. Check: e2e typing a payout, the gap, Undo, the filter.
6. Freelance tab, dashboard and Analytics split. Check: e2e and a screenshot with `kctl`.
7. PDF line and CSV. Check: unit test of `build_freelance_timesheet` with a payout, the employee sheet byte-for-byte unchanged.
8. Seed (a couple of payouts), `smoke.py`, service worker cache bump, docs. Then land on `master` as one commit, `Phase 37 - Freelance payouts`, and check INT.

# Acceptance

- A week with a payout uses the payout everywhere money appears, and the blocks' estimates nowhere for that source and week.
- A week without a payout looks exactly as it does today (pinned by a test).
- No employee number moves (the dashboard hero, balance, streaks, the employee timesheet).
- Backup, wipe and restore give back identical payouts.
- Each new test fails against a planted one-line bug.

# Constraints

- PROD is Miguel's button in the pipeline; Claude lands on `master` and checks INT, never deploys PROD.
- The repo is mirrored publicly: no host details or personal amounts in the code or the seed.
- `tax.py` stays the only source of tax figures.
