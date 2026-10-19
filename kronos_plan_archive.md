# Kronos — Plan Archive

Completed and confirmed phases of `kronos_plan.md`, summarised: what each one decided and shipped,
what it left undone, and where the detail is. **Not loaded by default**: read it when you need the
history of a decision. The code and the tests are the current truth; this file is the "why".
Phases 1–23 predate this file and still sit in `kronos_plan.md` as ✅ DONE blocks.

---

## Phase 27 — Spanish Holidays from the BOE
Confirmed by Miguel and deployed to PROD 2026-10-19.

**Why.** Phase 14 took Spain from Nager.Date, which is wrong for every Spanish region: it leaves
national holidays that fall on a Sunday on the Sunday (1-nov and 6-dic 2026, 15-ago 2027) instead
of the Monday the regions move them to, and it misses each region's own choices (San José, Easter
Monday, substitutions). Against the official list it differed in all 19 regions (76 differences in
2026, 46 in 2027). Madrid 2027: the BOE has 19-mar and 16-ago, Nager 2-may and 15-ago.

**What shipped.**
- Spain comes from the yearly resolution of the Dirección General de Trabajo ("relación de fiestas
  laborales"), fetched as XML from `boe.es/diario_boe/xml.php?id=<id>`. `services/boe_holidays.py`
  parses its table (one row per date, one column per region; `*`/`**` national, `***` the region's
  own, so only `***` shows as "regional"; a mark with a footnote call still counts). Header texts
  drift between years, so columns map to ISO codes by keyword; an unreadable table raises (→ 502)
  rather than returning partial data.
- `BOE_RESOLUTIONS` maps year → BOE id (2026: `BOE-A-2025-21667`, 2027: `BOE-A-2026-21254`).
  **Add the next year's id each October.** A Spanish year without one is a 404 that says so, never a
  fallback to Nager; the Settings preview shows that error instead of an empty calendar.
- Without a region, Spain imports only the holidays all 19 regions share. Subdivisions for ES are the
  19 BOE columns. Every other country still uses Nager.Date.
- Settings lists the previewed holidays one per line under the legend ("Thu, Jan 1 — Año Nuevo",
  "regional" tag, "already logged" note), asked for by Miguel while checking INT.

**Tests.** The two real XML files are fixtures (`tests/fixtures/boe/`, kept byte-for-byte by
`.gitattributes`). ES-MD 2027 imports exactly its 12 official dates; the Spain API tests make Nager
raise, so routing Spain back to Nager fails 7 of them (checked by planting it). 19 new tests (345
total). The holiday list has no automated test: the preview depends on the live BOE fetch.

**Known limits.** Canarias' island holidays and Arán's substitution live in the table's footnotes and
are not imported (log them by hand, like local fiestas).

**PROD data at the time** (read-only check, 2026-10-16): the 2026 holidays already matched the BOE
for ES-MD (fixed by hand earlier); 1-may was stored as `vacation` and 12-jun / 19-jun as holidays
without a note — left for Miguel.

**Commits.** `bfdffe1` Phase 27 — Spanish Holidays from the BOE; `a1c8bff` the holiday list.
Pipelines 218 and 233 (PROD from 233).
