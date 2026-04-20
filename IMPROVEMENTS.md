# Kronos — Improvement Backlog

Inspired by paid tools (Toggl, Harvest, Clockify, Factorial, BambooHR).
Each item is tagged with its rough scope: `[frontend]`, `[backend]`, `[both]`.

---

## ✅ Done

- [x] **Cumulative trend sparkline** `[frontend]` — SVG polyline in Analytics showing running surplus/deficit over all months; area fill + end dot coloured green/red/neutral.
- [x] **Monthly bar chart** `[frontend]` — SVG bar chart above the month cards; each bar = net hours, dashed brass line = target; colour-coded surplus/deficit.
- [x] **Year-at-a-glance heatmap** `[frontend]` — GitHub-style calendar grid; each cell coloured by day type and surplus/deficit magnitude; scrollable on mobile.

---

## 🔄 In progress

_(none)_

---

## 📋 Pending

### Visualisation
- [ ] **Week heatmap** `[frontend]` — show surplus/deficit intensity by day of week across all data (patterns: always worst on Mondays?).
- [ ] **Forecast** `[frontend]` — "at your current weekly average you'll end the year at ±Xh". Pure arithmetic on existing data, shown on Dashboard.

### Time tracking
- [ ] **Live timer** `[frontend]` — start/stop button on Dashboard. Pressing stop pre-fills the Log form with the elapsed time.
- [ ] **Quick-log from Dashboard** `[frontend]` — inline "Log today" shortcut so the user never has to leave the Dashboard for a standard day.
- [ ] **Day templates** `[frontend]` — save a standard workday (e.g. 09:00–17:00, 30 min lunch) and apply it with one click in the Log form.

### HR / leave tracking
- [ ] **Vacation budget** `[both]` — configurable annual allowance (e.g. 22 days). Settings shows remaining days; Analytics shows used vs. budget.
- [ ] **Carry-over summary** `[frontend]` — how much surplus rolled into the new year (visible in yearly breakdown).

### UX / quality of life
- [ ] **Browser notification reminder** `[frontend]` — daily nudge (configurable time) via the already-registered Service Worker if today has no entry.
- [ ] **Bulk day logging** `[frontend]` — select a date range and mark all weekdays as vacation/holiday in one action.
- [ ] **Markdown notes** `[frontend]` — render the notes field as Markdown in the Days table tooltip/expand.
- [ ] **PDF export** `[backend]` — formatted monthly/yearly report download alongside the existing CSV/JSON exports.
