/* Kronos — Alpine component + API client.
 *
 * Exposes a single global `app()` factory consumed by x-data="app()" on <main>.
 * No build step, no modules — just a function on window.
 */

// ── Service Worker registration (E4) ────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => {
      console.warn('[SW] registration failed:', err);
    });
  });
}

// What the year dial reads for the day under its index (see dialData): kept out of Alpine's state.
const _dial = { entries: new Map(), keys: [], sums: [], reset: false };

// The bezel's own scratch space: what a drag in progress needs, kept out of Alpine's reactive state so that
// moving the pointer never re-renders anything.
const _bz = { paintTo: null, pending: false, start: '', crossed: false, last: 0, rove: '', waveTimer: 0 };

// The day ribbon (Log). Everything is minutes since midnight. The helpers are pure: they take the form as it
// stands and answer with numbers, so the methods further down only draw and write. The scratch state of a
// drag lives here, out of Alpine, as the bezel's does: moving the pointer re-renders only when a value snaps.
const DR_LO = 360;        // the ribbon opens at 06:00 (earlier if the day does) ...
const DR_HI = 1440;       // ... and ends at midnight
const DR_END_MAX = 1425;  // the latest an end can be, 23:45: a time field has no 24:00
const DR_STEP = 15;
// the logo's callout: the timer that shows it and the one that closes it by itself
const _hint = { armed: false, show: 0, hide: 0 };

const _dr = {
  cur: null, active: false, field: null, pending: false, moved: false, kind: '', i: -1, id: null, pid: -1,
  x0: 0, y0: 0, left: 0, width: 1, laneTop: 0, laneBottom: 0, lo: DR_LO, pm0: 0, off: 0,
  base: null, dashes: [], orig: null, flag0: false, lastTap: { at: -1e9, x: 0 },
};

function drMin(v) {
  const m = typeof v === 'string' ? /^(\d{2}):(\d{2})(?::\d{2})?$/.exec(v) : null;
  if (!m || +m[1] > 23 || +m[2] > 59) return null;
  return +m[1] * 60 + +m[2];
}
function drHHMM(m) {
  const r = Math.round(m);
  return `${String(Math.floor(r / 60)).padStart(2, '0')}:${String(r % 60).padStart(2, '0')}`;
}
const drSnap = m => Math.round(m / DR_STEP) * DR_STEP;
const drClamp = (v, a, b) => Math.max(a, Math.min(b, v));  // a wins if the room is negative
const drPct = (m, lo) => (m - lo) / (DR_HI - lo) * 100;

// The form's day as numbers: the span, the breaks that have a place in it (ranged) and those that are only
// minutes. `i` is the break's index in form.breaks.
function drDay(f) {
  const s = drMin(f.start_time), e = drMin(f.end_time);
  const ranged = [], dashes = [];
  (f.breaks || []).forEach((b, i) => {
    const bs = drMin(b.start_time), be = drMin(b.end_time), mins = Number(b.break_minutes) || 0;
    if (bs !== null && be !== null && be > bs) ranged.push({ i, s: bs, e: be });
    else if (mins > 0) dashes.push({ i, min: mins });
  });
  return { s, e, ok: s !== null && e !== null && e > s, ranged, dashes };
}
// Minutes-only breaks have no place in the day: they are drawn side by side, centred in the bar.
function drDashes(d) {
  if (!d.ok || !d.dashes.length) return [];
  const total = d.dashes.reduce((t, k) => t + k.min, 0);
  let at = Math.max(d.s, d.s + (d.e - d.s - total) / 2);
  return d.dashes.map(k => { const seg = { i: k.i, min: k.min, s: at, e: Math.min(d.e, at + k.min) }; at += k.min; return seg; });
}
// Earlier than 06:00 opens the range at that hour.
function drLo(d, starts) {
  let lo = DR_LO;
  for (const t of [d.s, ...d.ranged.map(b => b.s), ...starts]) if (t !== null && t < lo) lo = Math.floor(t / 60) * 60;
  return lo;
}
// The moment the day's net reaches the target, walking from the start and skipping the breaks; null when the
// bar ends first. A break that begins at that very moment stays after it.
function drFlag(d, dashes, targetHours) {
  if (!d.ok || !(targetHours > 0)) return null;
  const cuts = [...d.ranged, ...dashes].map(k => [k.s, k.e]).sort((p, q) => p[0] - q[0]);
  let need = targetHours * 60, t = d.s;
  for (const [a, z] of cuts) {
    if (a <= t) { t = Math.max(t, z); continue; }
    if (a - t >= need) break;
    need -= a - t;
    t = z;
  }
  return t + need <= d.e + 1e-6 ? t + need : null;
}
// How far each handle may go with the day as it stands. A grip stops at the first break (the form never holds
// a break outside its bar); `day` is the range of a whole-day move.
function drLimits(d, lo) {
  const first = d.ranged.length ? Math.min(...d.ranged.map(b => b.s)) : Infinity;
  const last = d.ranged.length ? Math.max(...d.ranged.map(b => b.e)) : -Infinity;
  return {
    start: [lo, Math.min(d.e - DR_STEP, first)],
    end: [Math.max(d.s + DR_STEP, last), DR_END_MAX],
    day: [lo - d.s, DR_END_MAX - d.e],
  };
}
// The room a break has: the bar, less its neighbours. Two breaks never overlap.
function drRoom(d, self) {
  let a = d.s, z = d.e;
  for (const o of d.ranged) {
    if (o.i === self.i) continue;
    if (o.e <= self.s) a = Math.max(a, o.e);
    else if (o.s >= self.e) z = Math.min(z, o.s);
  }
  return [a, z];
}
// Where a new break of `len` minutes goes when the bar is double-clicked at `pm`: the quarter clicked, moved to
// the nearest free stretch if it is taken; null when no stretch is long enough.
function drPlaceBreak(d, pm, len) {
  const cuts = d.ranged.map(b => [b.s, b.e]).sort((p, q) => p[0] - q[0]);
  const free = [];
  let at = d.s;
  for (const [a, z] of cuts) { if (a > at) free.push([at, a]); at = Math.max(at, z); }
  if (d.e > at) free.push([at, d.e]);
  const room = free.filter(([a, z]) => z - a >= len);
  if (!room.length) return null;
  const gap = ([a, z]) => (pm < a ? a - pm : pm > z ? pm - z : 0);
  room.sort((p, q) => gap(p) - gap(q));
  const [a, z] = room[0];
  return drClamp(Math.floor(pm / DR_STEP) * DR_STEP, a, z - len);
}
function drTicks(lo) {
  const out = [];
  for (let h = Math.ceil(lo / 60); h <= 24; h++) {
    out.push({ h, style: `left:${drPct(h * 60, lo).toFixed(3)}%`, lab: h % 3 === 0 ? String(h).padStart(2, '0') : '', six: h % 6 === 0 });
  }
  return out;
}

function app() {
  return {
    // ---------- nav + global state ---------------------------------------
    tab: 'dashboard',
    error: null,

    // ---------- dashboard -----------------------------------------------
    dashboard: null,

    // ---------- streaks & milestones -------------------------------------
    streakStats: null,
    MILESTONES: [30, 100, 365],

    // ---------- dashboard trajectory ------------------------------------
    series: null,                  // /api/analytics/cumulative-series for this year
    traj: { svg: '', aria: '' },   // the chart as markup (see buildTrajectory)

    // ---------- log form ------------------------------------------------
    // leave_hours: hours of leave on a non-work day, null for work days.
    // Stored on the server as a fraction of that date's target (see formFraction()).
    form: { date: '', day_type: 'work', start_time: '09:00', end_time: '17:00', notes: '', breaks: [], leave_hours: null },
    notesOpen: false,
    drActive: null,            // the ribbon handle being dragged: { kind, i, off }
    editingDate: null,

    // ---------- log calendar --------------------------------------------
    calYear: new Date().getFullYear(),
    calMonth: new Date().getMonth(),

    // ---------- week strip (dashboard) ----------------------------------
    weekStart: '', // ISO date of this week's Monday; set in init()

    // ---------- time-off planner ----------------------------------------
    plans: [],            // every draft (all years); the Plan tab filters by planYear
    projection: null,     // /api/plans/projection for planYear
    planYear: new Date().getFullYear(),
    planMonth: new Date().getMonth(),      // the working month shown large
    planType: 'vacation',                  // what a click / drag drafts
    planNote: '',                          // note attached to new drafts
    planMode: localStorage.getItem('k-plan-mode') || 'on_target',  // 'on_target' | 'at_pace'
    planDrag: { anchor: null, current: null, dragging: false, startX: 0, startY: 0 },
    planBusy: false,
    planNoteEdit: null,   // { key, text } while a ledger note is being edited

    // ---------- printable timesheet (Days → PDF) -------------------------
    pdfModal: { open: false, kind: 'employee', preset: 'this_month', from: '', to: '', detail: 'full', hours: 'dec', theme: 'light', notes: false, sign: false },

    // ---------- days list -----------------------------------------------
    daysMode: 'employee',      // 'employee' | 'freelance' (the sub-tabs, once a source exists)
    daysSources: [],           // source ids included in the freelance view (none, one, several, all)
    _daysYearMemo: null,       // the year "All" goes back to
    _daysSourcesInit: false,
    entries: [],
    sortKey: 'date',
    sortDir: 'desc',
    daysYear: String(new Date().getFullYear()),
    notesQuery: '',
    daysFlashWeek: '',         // Monday of the week flashed after a jump from the Log calendar
    nowDisplay: '',

    // ---------- analytics -----------------------------------------------
    yearly: [],
    yoy: null,
    analyticsYear: String(new Date().getFullYear()),  // the year at a glance
    anSeries: null,                                   // /api/analytics/cumulative-series?all=true
    // The zoomable chart: the visible range [x0, x1) in ms, the series shown, the active
    // preset (null once zoomed by hand), and the interaction in progress.
    an: { mode: 'balance', x0: 0, x1: 0, preset: 'year', drag: null, hover: null, pinch: null },
    anChart: { svg: '', brush: '', aria: '' },
    AN_PRESETS: [
      { id: 'month', label: 'This month' },
      { id: '3m',    label: '3 months' },
      { id: 'year',  label: 'This year' },
      { id: '12m',   label: '12 months' },
      { id: 'all',   label: 'All' },
    ],
    hmTip: { show: false, x: 0, y: 0, title: '', body: '', note: '', hint: '' },
    anStuck: false,   // Year at a glance is pinned and has shrunk to its toolbar
    _anPinObserver: null,

    // ---------- settings ------------------------------------------------
    settingsForm: { daily_target_hours: 8, cumulative_start_date: '', reset_annually: false, work_week_days: [0,1,2,3,4], vacation_budget_days: 0, default_start_time: '09:00', default_end_time: '17:00', holiday_country: '', holiday_region: '', daily_target_schedule: [], profile_name: '', profile_employer: '', profile_extra: '', freelance_hours_per_week: 0, freelance_days_off: 0 },
    // Settings save themselves: a field half a second after the last keystroke, a switch or a
    // picker at once. Per section: '' · 'busy' · 'saved' · 'invalid' · 'error'.
    settingsStatus: {},
    _autosave: {},
    _scheduleKeySeq: 0,  // stable keys for the date-effective target rows
    _settingsSaved: null,  // the form as last loaded / saved, for the per-section dirty flags
    // Settings has two levels: three groups (Employee · Freelance · General), each a page of
    // cards with a section index; each section saves its own fields.
    SETTINGS_GROUPS: [
      { id: 'employee',  label: 'Employee',  mark: '👔' },
      { id: 'freelance', label: 'Freelance', mark: '⚡' },
      { id: 'general',   label: 'General',   mark: '🧰' },
    ],
    SETTINGS_SECTIONS: [
      { id: 'work',       group: 'employee',  label: 'Work',       fields: ['daily_target_hours', 'default_start_time', 'default_end_time', 'work_week_days', 'cumulative_start_date', 'reset_annually'] },
      { id: 'leave',      group: 'employee',  label: 'Leave',      fields: ['vacation_budget_days'] },
      { id: 'holidays',   group: 'employee',  label: 'Holidays',   fields: [] },
      { id: 'profile',    group: 'employee',  label: 'Profile',    fields: ['profile_name', 'profile_employer', 'profile_extra'] },
      { id: 'templates',  group: 'employee',  label: 'Templates',  fields: [] },
      { id: 'sources',    group: 'freelance', label: 'Sources',    fields: [] },
      { id: 'taxes',      group: 'freelance', label: 'Taxes',      fields: [] },
      { id: 'projection', group: 'freelance', label: 'Projection', fields: ['freelance_hours_per_week', 'freelance_days_off'] },
      { id: 'currency',   group: 'freelance', label: 'Currency',   fields: [] },
      { id: 'data',       group: 'general',   label: 'Data',       fields: [] },
    ],
    settingsGroup: localStorage.getItem('k-settings-group') || 'employee',
    settingsActive: 'work',
    _settingsSpy: null,

    // ---------- freelance -----------------------------------------------
    sources: [],          // income sources (archived included; pickers filter)
    blocks: [],           // every freelance block, loaded with the entries
    payouts: [],          // every weekly payout, loaded next to the blocks
    daysWeekOpen: {},     // Days > Freelance: week key (its Monday) -> days shown by hand; unset = only the current week shows its days
    daysWeekOpenQ: {},    // the same while the notes search has text (unset = open, so a hit is never hidden); emptied when the search clears
    daysWave: {},         // week key -> ms of delay, for the wave after the bezel's + or -: its ticks light and its rows fade in; emptied after
    payDraft: {},         // `${source}|${week}` -> the payout text being typed, until it is saved
    fxEditing: null,      // id of the payout whose exchange rate is being edited
    // the Log tab's block editor: `id` set while editing an existing block
    flForm: { id: null, source_id: null, by: 'hours', hours: 1, start_time: '18:00', end_time: '19:00', notes: '', rate: null, fx_rate: null },
    flBusy: false,
    flFloat: null,        // { text, key } — the "+€170" that floats off a saved block
    flSummary: null,      // /api/freelance/summary for flYear (the Freelance tab, the dashboard card)
    // Something moved the year's numbers: reload the summary next time it is shown. (Never
    // reset it to null once loaded: Alpine can still run effects of a torn-down Freelance tab,
    // and those would read fields of null.)
    _flStale: false,
    flYear: new Date().getFullYear(),
    fxInfo: null,         // /api/fx, asked for when a view needs a rate (never on a timer)
    srcForm: { id: null, name: '', hourly_rate: '', currency: 'EUR' },   // Settings → Sources editor
    accounts: [],         // where payouts land (archived included; pickers filter)
    currencyList: [],     // GET /api/currencies, once
    acctForm: { id: null, name: '', currency: 'EUR', kind: 'bank' },   // Settings → Accounts editor
    curQuery: '', curOpen: false, curIdx: 0,   // the currency picker of that editor
    payAcct: {},          // `${source}|${week}` -> the account chosen for a payout before it is saved (null = as billed)
    worthOpen: null,      // id of the payout whose "worth €" field is open by hand
    fxRates: {},          // `${currency}|${date}` -> the ECB rate the FX chip quotes, asked for when a chip opens
    fxTip: { open: false, pinned: false, id: null, text: '', style: '' },   // the FX chip's tooltip
    taxYear: new Date().getFullYear(),
    taxForm: null,        // Settings → Taxes: the year's inputs as loaded
    _taxSaved: null,
    calcEdit: null, calcDraft: '',   // the calculator field being typed in, and its text as typed
    calc: { mode: 'hourly', hourly: 60, daily: '', net: '', currency: 'EUR', fx_rate: '', fx_source: 'ECB', billable_days: 220, billable_mode: 'default', hours_per_day: 8, salary_annual: 0, gestoria_annual: 0, other_expenses: 0, tarifa_plana: false, inicio_actividad: false, result: null, busy: false, _seq: 0 },

    // ---------- public holidays ------------------------------------------
    holidayCountries: [],
    holidaySubdivisions: [],
    holidayPreview: [],
    holidayYear: new Date().getFullYear(),
    holidayImporting: false,

    // ---------- day templates (server-side) -----------------------------
    templates: [],
    _tplName: '',

    // ---------- fun zone ------------------------------------------------
    wipeConfirming: false,
    wipeInput: '',
    seedConfirming: false,
    seedInput: '',

    // ---------- E2 skeleton / optimistic --------------------------------
    loading: { dashboard: false, days: false, analytics: false, settings: false },
    saving: false,

    // ---------- updates: is the server running a newer build than this page? ----
    updateReady: false,
    newVersion: '',

    // ---------- W1 animated metrics (tick-up) ---------------------------
    animWeek: 0, animMonth: 0,

    // ---------- W5 save ribbon ------------------------------------------
    toast: { msg: '', kind: 'neutral', show: false, action: null, seal: null },
    _toastTimer: null,

    // ---------- W6 easter egg + streaks ---------------------------------
    streaksUnlocked: false,
    streaks: null,
    eggAnimating: false,

    // ---------- bulk log modal ------------------------------------------
    bulkModal: { open: false, year: new Date().getFullYear(), month: new Date().getMonth(), selected: [], _dragging: false, _dragAnchor: null, _dragCurrent: null, submitting: false },

    // ---------- command palette -----------------------------------------
    palette: { open: false, query: '', selected: 0 },

    // ---------- year dial (the logo, or Y) ------------------------------
    dialOpen: false,
    dialHint: false,
    _dialBack: null,       // what had the focus before it opened

    // =====================================================================
    // init
    // =====================================================================
    async init() {
      // Kronos is dark only; a theme remembered by an older version is forgotten.
      try { localStorage.removeItem('k-theme'); } catch { /* storage may be blocked */ }

      // Clearing the notes search puts every week back as it was before the search.
      this.$watch('notesQuery', q => { if (!q.trim()) this.daysWeekOpenQ = {}; });

      const TABS = ['dashboard', 'plan', 'log', 'days', 'analytics', 'freelance', 'settings'];
      const hash = location.hash.replace('#', '');
      if (TABS.includes(hash)) this.tab = hash;

      // The brass line under (or, on a phone, over) the active tab: placed at once when the page
      // opens, on a resize and when the Freelance tab appears; slid when the tab changes. The new
      // page fades in on a change only, never on load (the watcher is set after the first tab).
      this.$watch('tab', () => this.$nextTick(() => { this._tabsInk(true); this._pageFx(); }));
      this.$watch('sources.length', (n, was) => { if (n !== was) this.$nextTick(() => this._tabsInk(false)); });
      window.addEventListener('resize', () => this._tabsInk(false));
      this.$nextTick(() => this._tabsInk(false));

      window.addEventListener('hashchange', () => {
        const t = location.hash.replace('#', '');
        if (TABS.includes(t) && t !== this.tab) this.go(t);
      });

      // Keyboard shortcuts
      let _keyBuf = '';
      document.addEventListener('keydown', (e) => {
        // The year dial takes every key while it is open (Esc and Tab it handles itself).
        if (this.dialOpen) return;
        const tag = e.target?.tagName?.toUpperCase() || '';
        const inInput = ['INPUT','TEXTAREA','SELECT'].includes(tag) || e.target?.isContentEditable;

        // Ctrl+Enter — submit visible form regardless of focus
        if (e.ctrlKey && e.key === 'Enter') {
          if (this.tab === 'log')      { e.preventDefault(); this.saveEntry(); }
          else if (this.tab === 'settings') { e.preventDefault(); this.saveSettings(); }
          return;
        }

        // Escape — dismiss in priority order: an overlay, then the field you are in, then
        // an edit in progress, then the tab itself: Escape from any tab goes home.
        if (e.key === 'Escape') {
          if (this.dialHint)                          { e.stopImmediatePropagation(); this.closeDialHint(); return; }
          if (this.palette.open)                      { this.closePalette(); return; }
          if (this.bulkModal.open)                    { this.closeBulkModal(); return; }
          if (this.pdfModal.open)                     { this.pdfModal.open = false; return; }
          if (inInput)                                { e.target.blur(); return; }
          if (this.tab === 'log' && this.flForm.id)   { this.flCancelEdit(); return; }
          if (this.tab === 'log' && this.editingDate) { this.openNewEntry({ keepMonth: true }); return; }
          if (this.tab !== 'dashboard')               { this.go('dashboard'); return; }
          return;
        }

        // All remaining shortcuts fire only when focus is not inside a field
        if (inInput || e.ctrlKey || e.altKey || e.metaKey) return;

        switch (e.key) {
          case 'p': case 'P': e.preventDefault(); this.go('plan');      break;
          case 'l': case 'L': e.preventDefault(); this.go('log');       break;
          case 'd': case 'D': e.preventDefault(); this.go('days');      break;
          case 'a': case 'A': e.preventDefault(); this.go('analytics'); break;
          case 'f': case 'F': e.preventDefault(); this.go('freelance'); break;
          case 's': case 'S': e.preventDefault(); this.go('settings');  break;
          case '.': e.preventDefault(); this.openPalette(); break;
          case 'y': case 'Y':
            e.preventDefault();
            if (!this.bulkModal.open && !this.pdfModal.open) this.openDial();
            break;
        }

        // W6 — "kronos" easter egg key buffer
        if (e.key?.length === 1) {
          _keyBuf = (_keyBuf + e.key.toLowerCase()).slice(-6);
          if (_keyBuf === 'kronos') { this.triggerEasterEgg(); _keyBuf = ''; }
        }
      });

      // Live clock for the "Now" stamp pill — synced to the minute boundary
      const tickNow = () => { this.nowDisplay = this._nowHHMM(); };
      tickNow();
      setTimeout(() => { tickNow(); setInterval(tickNow, 60000); }, (60 - new Date().getSeconds()) * 1000);
      this._dialHintInit();

      // Is there a newer build on the server? Asked when the tab becomes visible again, when
      // the connection returns and every 10 minutes while visible. It only shows a pill:
      // the page never reloads by itself (the user may be typing).
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') this.checkForUpdate();
      });
      window.addEventListener('online', () => this.checkForUpdate());
      setInterval(() => { if (document.visibilityState === 'visible') this.checkForUpdate(); }, 10 * 60 * 1000);
      this.checkForUpdate();

      this.weekStart = this._mondayIso(new Date());
      this.loadSettings(); // pre-load so logPreview() has accurate target hours
      this.loadTemplates();
      this.loadSources();  // the freelance tab and the dashboard card exist once a source does
      this.openNewEntry();
      await this.go(this.tab);
      // the bead in the header reads today's entry: tabs that do not load the days load them quietly
      if (!['dashboard', 'log', 'days'].includes(this.tab) && !this.entries.length && !this.loading.days) this.loadDays();
    },

    // =====================================================================
    // updates
    // =====================================================================
    // The page carries the id of the build it loaded (<meta name="kronos-build">); the server
    // reports the one it runs now. A difference shows the pill. Offline, a failing request or
    // a malformed answer change nothing.
    async checkForUpdate() {
      try {
        const mine = document.querySelector('meta[name="kronos-build"]')?.content;
        if (!mine) return;
        const r = await fetch('/api/version', { cache: 'no-store' });
        if (!r.ok) return;
        const server = await r.json();
        if (server && server.build && server.build !== mine) {
          this.newVersion = String(server.version || '');
          this.updateReady = true;
        } else {
          this.updateReady = false;
        }
      } catch { /* offline or unreachable: say nothing */ }
    },

    // Ask the browser for the newest service worker first, then reload; the reload itself is
    // network-first (sw.js), so it really brings the new files.
    async applyUpdate() {
      try { await (await navigator.serviceWorker?.getRegistration())?.update(); } catch { /* reload anyway */ }
      location.reload();
    },

    // =====================================================================
    // nav
    // =====================================================================
    async go(t) {
      if (this.tab === 'settings' && t !== 'settings') this.settingsFlush();
      this.tab = t;
      // Mirror tab to URL hash without re-triggering hashchange
      if (location.hash.replace('#', '') !== t) location.hash = t;
      this.error = null;
      this.notesQuery = '';
      if (t === 'dashboard') await this.loadDashboard();
      else if (t === 'plan') await this.loadPlan();
      else if (t === 'log') this.loadDays(); // fire-and-forget: entries needed by calendar
      else if (t === 'days') await this.loadDays();
      else if (t === 'analytics') await this.loadAnalytics();
      else if (t === 'freelance') await this.loadFreelance();
      else if (t === 'settings') { await this.loadSettings(); this.loadHolidayData(); this.loadSettingsGroupData(); }
    },

    // Put the tabs' brass line under the active tab. `slide` is true only for a change of tab, and
    // only once the line has been placed; the first placement, a resize and a new tab are instant.
    _tabsInk(slide) {
      const ink = document.querySelector('.tabs .tabs-ink');
      if (!ink) return;
      const on = document.querySelector('.tabs [role="tab"][aria-selected="true"]');
      ink.classList.toggle('is-on', !!on); // Settings is open: no tab is active, the line fades out
      if (!on) return;
      const move = () => { // fractional: six columns of a phone are 53.3px wide
        const nav = ink.parentElement.getBoundingClientRect(), r = on.getBoundingClientRect();
        ink.style.setProperty('--ink-x', (r.left - nav.left + ink.parentElement.scrollLeft) + 'px');
        ink.style.setProperty('--ink-w', r.width + 'px');
      };
      if (slide && ink.dataset.placed === '1') { move(); return; }
      ink.style.transition = 'none';
      move();
      void ink.offsetWidth;
      ink.style.transition = '';
      ink.dataset.placed = '1';
    },
    // The page that just opened fades in over 160 ms, once.
    _pageFx() {
      this._bzFx(document.querySelector('main > section'), 'page-in', 200);
    },

    // Roving-tabindex arrow navigation for the tab list (E3)
    focusTab(dir, el) {
      const tabs = [...el.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];
      const next = tabs[(tabs.indexOf(el) + dir + tabs.length) % tabs.length];
      next.focus();
      next.click();
    },

    toggleWorkDay(i) {
      const days = this.settingsForm.work_week_days;
      this.settingsForm.work_week_days = days.includes(i)
        ? days.filter(d => d !== i)
        : [...days, i].sort((a, b) => a - b);
    },

    // =====================================================================
    // Day templates (server-side)
    // =====================================================================
    async loadTemplates() {
      try {
        this.templates = await this.api('GET', '/api/templates');
        // Silent one-time migration: if the server has no templates but localStorage does,
        // upload them and clear the local copy.
        if (this.templates.length === 0) {
          let local = [];
          try { local = JSON.parse(localStorage.getItem('kronos_templates') || '[]'); } catch {}
          if (local.length > 0) {
            for (const t of local) {
              try {
                await this.api('POST', '/api/templates', {
                  name: t.name, start_time: t.start_time, end_time: t.end_time,
                  breaks: (t.breaks || []).map(b => ({ break_minutes: b.break_minutes })),
                });
              } catch { /* skip invalid entries */ }
            }
            localStorage.removeItem('kronos_templates');
            this.templates = await this.api('GET', '/api/templates');
          }
        }
      } catch { this.templates = []; }
    },
    async saveCurrentAsTemplate(name) {
      if (!name.trim() || this.form.day_type !== 'work') return;
      const t = await this.api('POST', '/api/templates', {
        name: name.trim(),
        start_time: this.form.start_time,
        end_time: this.form.end_time,
        breaks: this.form.breaks.map(b => ({ break_minutes: b.break_minutes, start_time: b.start_time || null, end_time: b.end_time || null })),
      });
      this.templates = [...this.templates, t];
    },
    async deleteTemplate(id) {
      await this.api('DELETE', `/api/templates/${id}`);
      this.templates = this.templates.filter(t => t.id !== id);
    },
    applyTemplate(t) {
      this.form.day_type = 'work';
      this.form.start_time = t.start_time;
      this.form.end_time = t.end_time;
      this.form.breaks = t.breaks.map(b => ({ break_minutes: b.break_minutes, start_time: '', end_time: '' }));
    },

    // =====================================================================
    // Clock in / Clock out
    // =====================================================================
    _nowHHMM() {
      const now = new Date();
      return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    },
    stampNow(field) {
      this.form[field] = this._nowHHMM();
    },

    // =====================================================================
    // Quick-log from Dashboard
    // =====================================================================
    async quickLogTemplate(t) {
      await this._quickLog({
        date: this.todayIso(),
        day_type: 'work',
        start_time: t.start_time,
        end_time: t.end_time,
        breaks: t.breaks,
      });
    },
    async quickLogNonWork(dayType) {
      await this._quickLog({ date: this.todayIso(), day_type: dayType });
    },
    async _quickLog(body) {
      try {
        const saved = await this.api('POST', '/api/entries', body);
        await this.loadDashboard();
        if (this.entries.length) this.loadDays();
        const dow = new Date(saved.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long' });
        this.showToast(`Logged — ${dow} is ${this.formatSurplus(saved.surplus_hours)}`, this.surplusClass(saved.surplus_hours));
      } catch (e) {
        if (e.message.includes('already exists')) {
          await this.probeDate(body.date);
          this.go('log');
        } else {
          this.error = e.message;
        }
      }
    },

    // =====================================================================
    // Markdown / notes
    // =====================================================================
    renderMarkdown(text) {
      if (!text) return '';
      let s = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      s = s.replace(/\n/g, '<br>');
      return s;
    },
    highlightNotes(text, query) {
      const html = this.renderMarkdown(text);
      const q = query.trim();
      if (!q) return html;
      const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      // Replace only in text nodes (skip content inside HTML tags).
      return html.replace(new RegExp(`(${escaped})(?![^<]*>)`, 'gi'), '<mark>$1</mark>');
    },

    // =====================================================================
    // printable timesheet
    // =====================================================================
    openPdfModal() {
      // Remembered choices, except the theme: light prints best, so it is the default every
      // time; dark is a per-report decision. The kind follows the Days sub-tab: the
      // employee's sheet, or the freelance one with the sources ticked in the filter.
      const saved = JSON.parse(localStorage.getItem('k-pdf-options') || '{}');
      this.pdfModal = { ...this.pdfModal, ...saved, theme: 'light', open: true, kind: this.daysMode };
      if (this.daysMode === 'freelance') this._daysSourcesReady();
      if (!this.pdfModal.from) { const { from, to } = this.pdfPresets()[0]; this.pdfModal.from = from; this.pdfModal.to = to; }
    },
    // Presets end today when the period is still running — an employer doesn't want
    // sixty blank rows — and cover whole past periods.
    pdfPresets() {
      const today = new Date(); const iso = this.todayIso();
      const y = today.getFullYear(), m = today.getMonth();
      const first = (yy, mm) => `${yy}-${String(mm + 1).padStart(2, '0')}-01`;
      const last = (yy, mm) => this._dateIso(new Date(yy, mm + 1, 0));
      const pm = m === 0 ? [y - 1, 11] : [y, m - 1];
      const monthName = (yy, mm) => new Date(yy, mm, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
      return [
        { id: 'this_month', label: 'This month', hint: `${monthName(y, m)}, up to today`, from: first(y, m), to: iso },
        { id: 'last_month', label: 'Last month', hint: monthName(...pm), from: first(...pm), to: last(...pm) },
        { id: 'this_year', label: 'This year', hint: `${y}, up to today`, from: `${y}-01-01`, to: iso },
        { id: 'last_year', label: 'Last year', hint: String(y - 1), from: `${y - 1}-01-01`, to: `${y - 1}-12-31` },
        { id: 'custom', label: 'Custom range', hint: '', from: '', to: '' },
      ];
    },
    timesheetUrl() {
      const o = this.pdfModal;
      const preset = this.pdfPresets().find(p => p.id === o.preset);
      const from = o.preset === 'custom' ? o.from : preset.from;
      const to = o.preset === 'custom' ? o.to : preset.to;
      const q = new URLSearchParams({ from, to, hours: o.hours, theme: o.theme });
      if (o.notes) q.set('notes', '1');
      if (o.sign) q.set('sign', '1');
      if (o.kind === 'freelance') { q.set('sources', [...this.daysSources].sort((a, b) => a - b).join(',')); return `/timesheet/freelance?${q}`; }
      q.set('detail', o.detail);
      return `/timesheet?${q}`;
    },
    openTimesheet() {
      const o = this.pdfModal;
      if (o.preset === 'custom' && (!o.from || !o.to || o.to < o.from)) { this.showToast('Pick a valid date range', 'deficit'); return; }
      const { open, kind, ...remember } = o;
      localStorage.setItem('k-pdf-options', JSON.stringify(remember));
      window.open(this.timesheetUrl(), '_blank', 'noopener');
      this.pdfModal.open = false;
    },

    // =====================================================================
    // time-off planner
    // =====================================================================
    async loadPlan() {
      try {
        const [projection] = await Promise.all([
          this.api('GET', `/api/plans/projection?year=${this.planYear}`),
          this.loadDays(),  // entries + every draft, for the year strip and the month
        ]);
        this.projection = projection;
      } catch (e) { this.error = e.message; }
    },
    async _refreshPlan() {
      // After a change: drafts + projection, and the dashboard's forecast inputs.
      await this.loadPlan();
      this.loadDashboard();
    },
    setPlanYear(y, month = null) {
      this.planYear = y;
      const now = new Date();
      this.planMonth = month ?? (y === now.getFullYear() ? now.getMonth() : 0);
      this.loadPlan();
    },
    setPlanMode(mode) {
      this.planMode = mode;
      localStorage.setItem('k-plan-mode', mode);
    },
    planYearEndBalance() {
      if (!this.projection) return null;
      return this.planMode === 'at_pace' ? this.projection.at_pace : this.projection.on_target;
    },
    planYearDrafts() {
      return this.plans.filter(p => p.date.startsWith(String(this.planYear)));
    },

    // ── the three drawings on the Plan cards: only the figures already on each card ──
    // Balance: a line from today's balance to the year-end one (a faint one for the other assumption)
    planSpark() {
      const p = this.projection;
      if (!p) return null;
      const now = p.balance_today, end = this.planYearEndBalance();
      const alt = this.planMode === 'at_pace' ? p.on_target : p.at_pace;
      const vals = [now, end, alt, 0];
      const lo = Math.min(...vals), hi = Math.max(...vals), span = (hi - lo) || 1;
      const X0 = 3, X1 = 97, Y0 = 3, Y1 = 21;          // padding inside the 100 x 24 box
      const y = v => +(Y1 - ((v - lo) / span) * (Y1 - Y0)).toFixed(2);
      const pct = v => +((y(v) / 24) * 100).toFixed(2);
      return {
        line: `M${X0} ${y(now)} L${X1} ${y(end)}`,
        alt: `M${X0} ${y(now)} L${X1} ${y(alt)}`,
        zero: y(0),
        nowLeft: X0, nowTop: pct(now),
        endLeft: X1, endTop: pct(end),
        label: `Balance from ${this.formatSurplus(now)} today to ${this.formatSurplus(end)} on Dec 31`,
      };
    },
    // Vacation: one pip per budget day (per used or drafted day without a budget), lit when used
    planVacationPips() {
      const p = this.projection;
      if (!p) return [];
      const used = p.vacation_used_days, drafted = p.vacation_drafted_days;
      const budget = p.vacation_budget_days > 0 ? p.vacation_budget_days : 0;
      const total = Math.min(60, Math.max(Math.ceil(budget), Math.ceil(used + drafted)));
      const out = [];
      for (let i = 0; i < total; i++) {
        const usedShare = Math.min(1, Math.max(0, used - i));
        const draftShare = Math.min(1, Math.max(0, used + drafted - i));
        let cls = '';
        if (usedShare >= 1) cls = 'on';
        else if (usedShare > 0) cls = 'on half';
        else if (draftShare >= 1) cls = 'draft';
        else if (draftShare > 0) cls = 'draft half';
        if (budget && i >= budget) cls += ' over';
        out.push({ k: i, cls });
      }
      return out;
    },
    // Drafted: one pip per drafted day after today, in the colour of its type
    planDraftPips() {
      const p = this.projection;
      if (!p) return [];
      return this.plans
        .filter(d => !d.exists && d.date > p.today && d.date.startsWith(String(this.planYear)))
        .sort((a, b) => a.date.localeCompare(b.date))
        .map(d => ({ k: d.date, cls: d.day_type + (d.fraction < 1 ? ' half' : ''), title: `${d.date} · ${d.day_type}` }));
    },

    // ── year strip: twelve mini months, click one to work on it (Plan and Log) ──
    planYearStrip() { return this.yearStrip(this.planYear, this.planMonth); },
    yearStrip(year, activeMonth) {
      const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const entryMap = {};
      for (const e of this.entries) if (e.date.startsWith(String(year))) entryMap[e.date] = e;
      const drafts = this.draftMap();
      const todayStr = this.todayIso();
      const out = [];
      for (let mo = 0; mo < 12; mo++) {
        const offset = (new Date(year, mo, 1).getDay() + 6) % 7;
        const days = new Date(year, mo + 1, 0).getDate();
        const cells = [];
        for (let i = 0; i < offset; i++) cells.push({ key: `p${i}`, pad: true });
        for (let d = 1; d <= days; d++) {
          const iso = `${year}-${String(mo + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
          const entry = entryMap[iso] || null;
          const dow = (offset + d - 1) % 7;
          cells.push({ key: iso, pad: false,
            cls: this.dayCellCls(entry, drafts[iso]) + (dow >= 5 ? ' hm-weekend' : '') + (iso === todayStr ? ' hm-today' : ''),
            style: this.entryCellStyle(entry) });
        }
        out.push({ mo, label: MONTHS[mo], cells, active: mo === activeMonth });
      }
      return out;
    },

    // ── the working month ────────────────────────────────────────────────
    planMonthLabel() {
      return new Date(this.planYear, this.planMonth, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    },
    planPrev() { if (this.planMonth === 0) this.setPlanYear(this.planYear - 1, 11); else this.planMonth--; },
    planNext() { if (this.planMonth === 11) this.setPlanYear(this.planYear + 1, 0); else this.planMonth++; },
    planCalDays() {
      const year = this.planYear, month = this.planMonth;
      const todayStr = this.todayIso();
      const entryMap = {};
      for (const e of this.entries) entryMap[e.date] = e;
      const drafts = this.draftMap();
      const firstDow = (new Date(year, month, 1).getDay() + 6) % 7;
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const cells = [];
      for (let i = 0; i < firstDow; i++) cells.push({ padded: true, key: `ppad-${i}` });
      for (let d = 1; d <= daysInMonth; d++) {
        const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const entry = entryMap[iso] || null;
        const draft = entry ? null : (drafts[iso] || null);
        const dow = new Date(year, month, d).getDay();
        // Logged days and the past can't be drafted; clicking them opens the Log tab.
        const opensLog = !!entry || iso < todayStr;
        cells.push({ padded: false, key: iso, date: iso, day: d, entry, draft, opensLog,
          cls: this.dayCellCls(entry, draft), style: this.entryCellStyle(entry),
          isToday: iso === todayStr, weekend: dow === 0 || dow === 6, past: iso < todayStr,
          title: entry ? `${this.pillLabel(entry)} — logged · open in Log` : opensLog ? 'open in Log'
            : draft ? `${draft.day_type} · drafted${draft.notes ? ' · ' + draft.notes : ''}` : '' });
      }
      return cells;
    },
    _planWorkWeek() {
      return new Set(this.dashboard?.work_week_days ?? this.settingsForm.work_week_days ?? [0,1,2,3,4]);
    },
    _isWorkWeekDay(iso) { return this._planWorkWeek().has((new Date(iso + 'T12:00:00').getDay() + 6) % 7); },
    // Highlight only what a drag will draft: the range's work-week days.
    planIsHighlighted(iso) {
      const g = this.planDrag;
      if (!iso || !g.dragging || !g.anchor || !g.current) return false;
      return this._isWorkWeekDay(iso) && this._bulkRange(g.anchor, g.current).includes(iso);
    },
    planMousedown(event, cell) {
      if (!cell.date || cell.opensLog) return;  // those cells open the Log tab on click instead
      this.planDrag = { anchor: cell.date, current: cell.date, dragging: false, startX: event.clientX, startY: event.clientY };
    },
    planGridMove(event) {
      const g = this.planDrag;
      if (!g.anchor) return;
      if (Math.hypot(event.clientX - g.startX, event.clientY - g.startY) < 4) return;
      const iso = event.target.closest('[data-pdate]')?.dataset.pdate;
      if (!iso || iso === g.current) return;
      g.dragging = true;
      g.current = iso;
    },
    async planMouseup() {
      const g = this.planDrag;
      if (!g.anchor) return;
      const { anchor, current, dragging } = g;
      this.planDrag = { anchor: null, current: null, dragging: false, startX: 0, startY: 0 };
      if (dragging) {
        // A dragged range drafts its work-week days only (a click still takes any day).
        const entryDates = new Set(this.entries.map(e => e.date));
        const dates = this._bulkRange(anchor, current)
          .filter(d => this._isWorkWeekDay(d) && !entryDates.has(d));
        if (dates.length) await this.draftDates(dates);
      } else {
        const existing = this.draftMap()[anchor];
        if (existing) await this.removeDraft([anchor]);
        else await this.draftDates([anchor]);
      }
    },
    async draftDates(dates) {
      if (this.planBusy) return;
      this.planBusy = true;
      try {
        const body = { dates, day_type: this.planType, notes: this.planNote.trim() || null };
        const r = await this.api('POST', '/api/plans', body);
        await this._refreshPlan();
        const n = r.drafted.length + r.replaced.length;
        this.showToast(`${n} day${n !== 1 ? 's' : ''} drafted as ${this.planType}`, 'neutral');
      } catch (e) { this.error = e.message; }
      finally { this.planBusy = false; }
    },
    async removeDraft(dates) {
      if (this.planBusy) return;
      this.planBusy = true;
      try {
        for (const d of dates) await this.api('DELETE', `/api/plans/${d}`);
        await this._refreshPlan();
      } catch (e) { this.error = e.message; }
      finally { this.planBusy = false; }
    },
    async commitDraft(block) {
      if (this.planBusy) return;
      this.planBusy = true;
      try {
        const r = await this.api('POST', '/api/plans/commit', { dates: block.dates });
        await this._refreshPlan();
        const n = r.created.length, s = r.skipped.length;
        this.showToast(s ? `${n} logged, ${s} already logged` : `${n} day${n !== 1 ? 's' : ''} logged as ${block.day_type}`, 'neutral');
      } catch (e) { this.error = e.message; }
      finally { this.planBusy = false; }
    },
    // A logged block in the ledger: delete its entries (same confirm as the Log tab).
    async deleteLoggedBlock(block) {
      const n = block.dates.length;
      if (!confirm(`Delete ${n === 1 ? 'the entry for ' + block.label : n + ' logged days (' + block.label + ')'}?`)) return;
      if (this.planBusy) return;
      this.planBusy = true;
      try {
        for (const d of block.dates) await this.api('DELETE', `/api/entries/${d}`);
        await this._refreshPlan();
        this.showToast(`${n} day${n !== 1 ? 's' : ''} deleted`, 'neutral');
      } catch (e) { this.error = e.message; }
      finally { this.planBusy = false; }
    },
    // Inline note editing on a ledger block (applies to every day of the block).
    startNoteEdit(block) {
      this.planNoteEdit = { key: block.key, text: block.notes || '' };
      this.$nextTick(() => document.querySelector('.plan-note-input')?.focus());
    },
    async saveNoteEdit(block) {
      if (!this.planNoteEdit || this.planNoteEdit.key !== block.key) return;
      const text = this.planNoteEdit.text.trim() || null;
      this.planNoteEdit = null;
      if ((block.notes || null) === text) return;
      try {
        for (const d of block.dates) await this.api('PUT', `/api/plans/${d}`, { notes: text });
        await this.loadPlan();
      } catch (e) { this.error = e.message; }
    },

    // ── ledger: drafts and logged time off of the year, oldest first ────
    // Consecutive days of the same type (weekends in between allowed) form one block.
    planLedger() {
      const year = String(this.planYear);
      const todayStr = this.todayIso();
      const week = this._planWorkWeek();
      const items = [];
      for (const p of this.plans) {
        if (!p.date.startsWith(year)) continue;
        items.push({ date: p.date, day_type: p.day_type, fraction: p.fraction, leave_hours: p.leave_hours,
          notes: p.notes, kind: p.exists ? 'logged-over' : (p.date <= todayStr ? 'overdue' : 'draft') });
      }
      for (const e of this.entries) {
        if (!e.date.startsWith(year) || e.day_type === 'work' || e.date <= todayStr) continue;
        items.push({ date: e.date, day_type: e.day_type, fraction: e.fraction, leave_hours: e.leave_hours, notes: e.notes, kind: 'logged' });
      }
      items.sort((a, b) => a.date < b.date ? -1 : 1);

      const gapIsFree = (a, b) => {  // only non-scheduled days between a and b (exclusive)
        const cur = new Date(a + 'T12:00:00'); cur.setDate(cur.getDate() + 1);
        const end = new Date(b + 'T12:00:00');
        while (cur < end) {
          if (week.has((cur.getDay() + 6) % 7)) return false;
          cur.setDate(cur.getDate() + 1);
        }
        return true;
      };
      const blocks = [];
      for (const it of items) {
        const last = blocks[blocks.length - 1];
        if (last && last.kind === it.kind && last.day_type === it.day_type && (last.notes || null) === (it.notes || null)
            && last.fraction === it.fraction && gapIsFree(last.dates[last.dates.length - 1], it.date)) {
          last.dates.push(it.date);
          last.days += it.fraction;
          last.leave_hours += it.leave_hours;
        } else {
          blocks.push({ key: `${it.kind}-${it.date}`, kind: it.kind, day_type: it.day_type, fraction: it.fraction,
            notes: it.notes, dates: [it.date], days: it.fraction, leave_hours: it.leave_hours });
        }
      }
      for (const b of blocks) {
        b.days = Math.round(b.days * 100) / 100;
        b.leave_hours = Math.round(b.leave_hours * 100) / 100;
        b.label = this._planBlockLabel(b.dates);
        b.detail = this._planBlockDetail(b);
      }
      return blocks;
    },
    _planBlockLabel(dates) {
      const fmt = (iso, opts) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', opts);
      if (dates.length === 1) return fmt(dates[0], { weekday: 'short', month: 'short', day: 'numeric' });
      const a = dates[0], b = dates[dates.length - 1];
      const sameMonth = a.slice(0, 7) === b.slice(0, 7);
      return `${fmt(a, { month: 'short', day: 'numeric' })} – ${fmt(b, sameMonth ? { day: 'numeric' } : { month: 'short', day: 'numeric' })}`;
    },
    _planBlockDetail(b) {
      const parts = [];
      if (b.dates.length > 1 || b.fraction < 1) parts.push(`${this.fmtDays(b.days)} day${b.days !== 1 ? 's' : ''}`);
      if (b.fraction < 1) parts.push(`${this.fmtHours(b.leave_hours)} off`);
      if (b.day_type === 'flex') parts.push(`−${this.fmtHours(b.leave_hours)} pool`);
      return parts.join(' · ');
    },
    planBlockCount(kind) { return this.planLedger().filter(b => b.kind === kind).length; },

    // =====================================================================
    // command palette
    // =====================================================================
    _COMMANDS: [
      { id: 'dashboard', label: 'Dashboard',     hint: 'Esc' },
      { id: 'plan',      label: 'Plan time off', hint: 'P'   },
      { id: 'log',       label: 'Log new entry', hint: 'L'   },
      { id: 'days',      label: 'Days',          hint: 'D'   },
      { id: 'pdf',       label: 'PDF timesheet', hint: ''    },
      { id: 'analytics', label: 'Analytics',     hint: 'A'   },
      { id: 'freelance', label: 'Freelance',     hint: 'F'   },
      { id: 'calc',      label: 'Rate calculator', hint: ''  },
      { id: 'dial',      label: 'Year dial',     hint: 'Y'   },
      { id: 'settings',  label: 'Settings',      hint: 'S'   },
    ],

    openPalette() {
      this.palette.open = true;
      this.palette.query = '';
      this.palette.selected = 0;
      this.$nextTick(() => document.getElementById('k-palette-input')?.focus());
    },

    closePalette() {
      this.palette.open = false;
    },

    filteredCommands() {
      const q = this.palette.query.toLowerCase().trim();
      if (!q) return this._COMMANDS;
      return this._COMMANDS.filter(c => c.label.toLowerCase().includes(q));
    },

    paletteNavigate(dir) {
      const len = this.filteredCommands().length;
      if (!len) return;
      this.palette.selected = (this.palette.selected + dir + len) % len;
    },

    async paletteRun(cmd) {
      this.closePalette();
      if (cmd.id === 'pdf') { await this.go('days'); this.openPdfModal(); return; }
      if (cmd.id === 'dial') { this.openDial(); return; }
      if (cmd.id === 'calc') { await this.go('freelance'); this.$nextTick(() => document.getElementById('fl-calc')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); return; }
      this.go(cmd.id);
    },

    paletteConfirm() {
      const cmds = this.filteredCommands();
      if (cmds.length) this.paletteRun(cmds[this.palette.selected] ?? cmds[0]);
    },

    // =====================================================================
    // year dial (dial.js draws and turns it; these hand it the days and the words)
    // =====================================================================
    async openDial() {
      if (this.dialOpen) return;
      this.closeDialHint();
      const a = document.activeElement;
      this._dialBack = a && a !== document.body && !a.closest('.palette-backdrop') ? a : null;
      this.dialOpen = true;
      // the days, blocks and balance it reads may still be on their way
      if (!this.dashboard && !this.loading.dashboard) this.loadDashboard();
      for (let n = 0; n < 100 && (!this.dashboard || this.loading.dashboard || this.loading.days); n++) {
        await new Promise(r => setTimeout(r, 50));
      }
      if (!this.dialOpen) return;
      await this.$nextTick();
      const root = document.getElementById('yd');
      if (!root || !window.KronosDial) { this.dialOpen = false; return; }
      window.KronosDial.open(root, this.dialData(), {
        year: y => this.dialYear(y),
        read: iso => this.dialRead(iso),
        go: iso => this.dialGo(iso),
        close: () => this.closeDial(),
        getSound: () => this.dialSound(),
        setSound: on => this.dialSetSound(on),
      });
    },

    // The logo's callout, once per browser: it shows ~1.2s after the first load of this version where the
    // dial was never opened, turns the logo a quarter, and goes by itself after 10s. Closing it or opening the
    // dial writes k-dial-hint = 1, and it never comes back. Without storage it is never shown.
    _dialHintInit() {
      if (_hint.armed) return;  // one callout, one timer, however often this is called
      let seen = true;
      try { seen = localStorage.getItem('k-dial-hint') === '1'; } catch { seen = true; }
      if (seen) return;
      _hint.armed = true;
      _hint.show = setTimeout(() => {
        _hint.show = 0;
        let seenSince = true;
        try { seenSince = localStorage.getItem('k-dial-hint') === '1'; } catch { seenSince = true; }
        if (this.dialOpen || seenSince) return;
        this.dialHint = true;
        if (!this._reduced()) this._bzFx(document.querySelector('.brand-logo'), 'logo-quarter', 1200);
        _hint.hide = setTimeout(() => this.closeDialHint(), 10000);
      }, 1200);
    },
    closeDialHint() {
      clearTimeout(_hint.show);
      clearTimeout(_hint.hide);
      _hint.show = _hint.hide = 0;
      this.dialHint = false;
      try { localStorage.setItem('k-dial-hint', '1'); } catch { /* storage blocked */ }
    },

    closeDial() {
      if (!this.dialOpen) return;
      window.KronosDial?.close();
      // the focus goes back now, while the dial is still in the page: the element that has it is
      // never the one Alpine removes next
      const back = this._dialBack;
      this._dialBack = null;
      (back && back.isConnected ? back : document.querySelector('.brand-btn'))?.focus({ preventScroll: true });
      this.dialOpen = false;
    },

    // Enter and "Open in Log": that day in Log, and the dial closes.
    dialGo(iso) {
      this.openDayInLog(iso).catch(e => { this.error = e.message; });
      this.closeDial();
    },

    dialSound() {
      try { return localStorage.getItem('k-dial-sound') === '1'; } catch { return false; }
    },
    dialSetSound(on) {
      try { localStorage.setItem('k-dial-sound', on ? '1' : '0'); } catch { /* storage may be blocked */ }
    },

    // What the dial needs once, when it opens: today, the years it can show, and the running balance,
    // counted as the Dashboard counts it: from the "Cumulative since" date, and from Jan 1 of each year
    // with "Reset on January 1st" on. The needle's scale is the largest it reaches.
    dialData() {
      const today = this.todayIso();
      const sorted = [...this.entries].sort((a, b) => (a.date < b.date ? -1 : 1));
      _dial.entries = new Map(sorted.map(e => [e.date, e]));
      _dial.keys = [];
      _dial.sums = [];
      const from = this.settingsForm.cumulative_start_date || '';
      _dial.reset = !!this.settingsForm.reset_annually;
      let run = 0, max = 0, year = '';
      for (const e of sorted) {
        if (_dial.reset && e.date.slice(0, 4) !== year) { year = e.date.slice(0, 4); run = 0; }
        if (e.date >= from) run += e.surplus_hours;
        _dial.keys.push(e.date);
        _dial.sums.push(run);
        max = Math.max(max, Math.abs(run));
      }
      const years = [...new Set([...sorted.map(e => Number(e.date.slice(0, 4))), Number(today.slice(0, 4))])].sort((a, b) => a - b);
      return { today, years, balanceMax: Math.round(max * 100) / 100 };
    },

    // The running balance up to and including that day (see dialData).
    dialBalanceAt(iso) {
      let lo = 0, hi = _dial.keys.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (_dial.keys[mid] <= iso) lo = mid + 1; else hi = mid;
      }
      if (!lo || (_dial.reset && _dial.keys[lo - 1].slice(0, 4) !== iso.slice(0, 4))) return 0;
      return Math.round(_dial.sums[lo - 1] * 100) / 100;
    },

    // One tick per day of the year y: { k: its kind, v: its signed length -1..1, fl: 'fl' | 'paid' }.
    dialYear(y) {
      const prefix = `${y}-`;
      const draft = this.draftMap();
      const bar = e => e.day_type === 'work' || this.isPartial(e);   // a partial day takes the bar of its surplus
      const fl = new Map();
      for (const b of this.blocks) {
        if (!b.date.startsWith(prefix)) continue;
        fl.set(b.date, fl.get(b.date) === 'paid' || b.payout_id != null ? 'paid' : 'fl');
      }
      let maxAbs = 0;
      for (const [iso, e] of _dial.entries) {
        if (iso.startsWith(prefix) && bar(e)) maxAbs = Math.max(maxAbs, Math.abs(e.surplus_hours));
      }
      const out = [];
      for (let d = new Date(y, 0, 1, 12); d.getFullYear() === y; d.setDate(d.getDate() + 1)) {
        const iso = this._dateIso(d), e = _dial.entries.get(iso), p = draft[iso];
        let t;
        if (e && bar(e)) {
          const s = e.surplus_hours;
          t = Math.abs(s) < 0.01 ? { k: 'neutral', v: 0 } : { k: s > 0 ? 'surplus' : 'deficit', v: s / maxAbs };
        } else if (e) t = { k: e.day_type, v: 0 };
        else if (p) t = { k: `draft-${p.day_type}`, v: 0 };
        else t = { k: 'empty', v: 0 };
        if (fl.has(iso)) t.fl = fl.get(iso);
        out.push(t);
      }
      return out;
    },

    // What one day says, in words and numbers already formatted: the face, the balance, the week.
    dialRead(iso) {
      const today = this.todayIso();
      const day = new Date(iso + 'T12:00:00');
      const e = _dial.entries.get(iso) || null;
      const p = e ? null : this.draftMap()[iso];
      const r = { date: day.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) };
      r.wk = [this.weekId(this._mondayIso(day)), iso === today ? 'today' : '', this.isPartial(e) ? this.pillLabel(e) : ''].filter(Boolean).join(' · ');
      if (e && (e.day_type === 'work' || this.isPartial(e))) {
        r.big = this.fmtHours(e.net_hours); r.bigKind = 'work';
        r.sub = this.formatSurplus(e.surplus_hours); r.subKind = this.surplusClass(e.surplus_hours);
      } else if (e) {
        r.big = e.day_type; r.bigKind = e.day_type; r.sub = ''; r.subKind = 'muted';
      } else if (p) {
        r.big = p.day_type; r.bigKind = p.day_type; r.sub = 'planned'; r.subKind = 'muted';
      } else {
        r.big = '–'; r.bigKind = 'none'; r.sub = iso > today ? 'still to come' : 'no entry'; r.subKind = 'muted';
      }
      r.note = (e || p)?.notes || '';
      const fl = this.flDayTotal(iso);
      r.fl = fl ? { text: `⚡ ${this.flTotalLabel(fl)}`, paid: this.blocksOn(iso).some(b => b.payout_id != null) } : null;
      const bal = this.dialBalanceAt(iso);
      r.balance = { value: bal, text: this.formatSurplus(bal) };
      // the week: seven pips from Monday, the selected one lit, and its sum
      const monday = new Date(day);
      monday.setDate(day.getDate() - ((day.getDay() + 6) % 7));
      let sum = 0;
      const pips = [];
      for (let n = 0; n < 7; n++) {
        const d = new Date(monday);
        d.setDate(monday.getDate() + n);
        const k = this._dateIso(d), we = _dial.entries.get(k);
        sum += we?.surplus_hours || 0;
        if (we && (we.day_type === 'work' || this.isPartial(we))) pips.push({ k: this.surplusClass(we.surplus_hours), h: we.net_hours / 10, on: k === iso });
        else pips.push({ k: we ? 'leave' : 'empty', h: null, on: k === iso });
      }
      r.week = { pips, sum: this.formatSurplus(Math.round(sum * 100) / 100) };
      r.text = `${r.date}, ${r.big}${r.sub ? ' ' + r.sub : ''}`;
      return r;
    },

    // =====================================================================
    // API client
    // =====================================================================
    async api(method, path, body) {
      const opts = { method, headers: { Accept: 'application/json' } };
      if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
      const res = await fetch(path, opts);
      if (!res.ok) {
        let msg = `${res.status} ${res.statusText}`;
        try {
          const data = await res.json();
          if (data.detail) {
            msg = typeof data.detail === 'string'
              ? data.detail
              : data.detail.map(d => `${d.loc?.join('.')}: ${d.msg}`).join('; ');
          }
        } catch { /* body wasn't JSON */ }
        throw new Error(msg);
      }
      if (res.status === 204) return null;
      return res.json();
    },

    // =====================================================================
    // helpers — formatting
    // =====================================================================
    surplusClass(h) {
      if (h > 0.01) return 'surplus';
      if (h < -0.01) return 'deficit';
      return 'neutral';
    },

    formatSurplus(h) {
      if (h === undefined || h === null) return '';
      const sign = h > 0 ? '+' : h < 0 ? '−' : '±';
      return `${sign}${Math.abs(h).toFixed(2)}h`;
    },

    // Line 2 of a Days row on a phone, only what the day has: "09:30-18:00 · 60m · Σ +24.50h".
    // The note follows it, drawn apart so a search can highlight it.
    daySub(e) {
      const parts = [];
      if (e.start_time && e.end_time) parts.push(`${e.start_time}-${e.end_time}`);
      if (e.total_break_minutes) parts.push(`${e.total_break_minutes}m`);
      if (e._cumulative !== undefined && e._cumulative !== null) parts.push(`Σ ${this.formatSurplus(e._cumulative)}`);
      return parts.join(' · ');
    },
    // The same for a freelance block: times, the rate, and the amount in the source's own
    // currency when that is not the euro already shown on line 1.
    blockSub(b) {
      const parts = [];
      if (b.start_time && b.end_time) parts.push(`${b.start_time}-${b.end_time}`);
      if (b.rate !== undefined && b.rate !== null) parts.push(`${this.fmtMoney(b.rate, b.currency)}/h`);
      if (b.currency !== 'EUR' && b.amount !== undefined && b.amount !== null) parts.push(this.fmtMoney(b.amount, b.currency));
      return parts.join(' · ');
    },

    subdialLabel(h) {
      if (h > 0.01) return 'Surplus';
      if (h < -0.01) return 'Deficit';
      return 'On target';
    },

    // 3 → "3h", 3.5 → "3.5h", 0.75 → "0.75h" — at most two decimals, no trailing zeros.
    fmtHours(h) {
      return `${Math.round((Number(h) || 0) * 100) / 100}h`;
    },
    // An exchange rate: four decimals, "1.1172".
    fmtFx(n) { return (Number(n) || 0).toFixed(4); },
    // The count-up of the Dashboard numbers: always two decimals while it runs, so it ends on
    // what formatSurplus shows.
    animText(n) { return (Number(n) || 0).toFixed(2); },
    // Day counts can be fractional (a 3h-off day is 0.62 work + 0.38 off).
    fmtDays(n) {
      return String(Math.round((Number(n) || 0) * 100) / 100);
    },

    // ---------- partial-day leave ----------------------------------------
    // Target hours in force on `iso`, from the date-effective schedule loaded with the
    // settings (falls back to the single current value before the settings arrive).
    targetForDate(iso) {
      const rows = this.settingsForm.daily_target_schedule || [];
      let hours = null;
      for (const r of rows) {
        if (r.effective_from <= iso) hours = Number(r.hours);
        else break;
      }
      if (hours === null && rows.length) hours = Number(rows[0].hours);
      return hours ?? (this.settingsForm.daily_target_hours || 8);
    },
    isPartial(e) {
      return !!e && e.day_type !== 'work' && e.fraction < 1;
    },
    // Pill text: "vacation" for a whole day, "vacation · 3h" for 3h of leave.
    pillLabel(e) {
      return this.isPartial(e) ? `${e.day_type} · ${this.fmtHours(e.leave_hours)}` : e.day_type;
    },
    // Calendar / heatmap / week cell colouring, shared by every calendar surface.
    // A partial day is split diagonally: leave colour for the leave share, then the
    // worked part's surplus colour (set inline, since the class colours are solid).
    _workedCls(e) {
      return e.surplus_hours > 0.01 ? 'hm-surplus' : e.surplus_hours < -0.01 ? 'hm-deficit' : 'hm-neutral';
    },
    entryCellCls(e) {
      if (!e) return 'hm-empty';
      if (e.day_type === 'work') return this._workedCls(e);
      return this.isPartial(e) ? 'hm-partial' : `hm-${e.day_type}`;
    },
    // A drafted (planned, not yet real) day: dashed outline in the type colour.
    draftCellCls(p) { return p ? `hm-ghost hm-ghost-${p.day_type}` : 'hm-empty'; },
    draftMap() {
      const m = {};
      for (const p of this.plans) if (!p.exists) m[p.date] = p;
      return m;
    },
    // Cell class for a date with a real entry, a draft, or nothing.
    dayCellCls(entry, draft) { return entry ? this.entryCellCls(entry) : this.draftCellCls(draft); },
    entryCellStyle(e) {
      if (!this.isPartial(e)) return '';
      const pct = Math.round(e.fraction * 100);
      const worked = { 'hm-surplus': 'var(--k-surplus)', 'hm-deficit': 'var(--k-deficit)', 'hm-neutral': 'var(--k-muted)' }[this._workedCls(e)];
      // Longhand on purpose: the `background` shorthand would reset the origin/repeat
      // that .hm-partial sets to keep the gradient from tiling into a cell's border.
      return `background-image: linear-gradient(135deg, var(--k-${e.day_type}) 0 ${pct}%, ${worked} ${pct}% 100%)`;
    },

    minutesToLabel(m) {
      if (m === null || m === undefined || isNaN(m) || m < 0) return '';
      m = Math.floor(m);
      const h = Math.floor(m / 60);
      const rem = m % 60;
      if (h && rem) return `${h}h ${rem}min`;
      if (h) return `${h}h`;
      return `${rem}min`;
    },

    parseHhmm(v) {
      if (!v || typeof v !== 'string') return null;
      const m = v.match(/^(\d{2}):(\d{2})$/);
      if (!m) return null;
      const h = parseInt(m[1], 10);
      const mm = parseInt(m[2], 10);
      if (h < 0 || h > 23 || mm < 0 || mm > 59) return null;
      return h * 60 + mm;
    },

    rangeMinutes(s, e) {
      const sm = this.parseHhmm(s);
      const em = this.parseHhmm(e);
      if (sm === null || em === null || em <= sm) return 0;
      return em - sm;
    },

    todayIso() { return this._dateIso(new Date()); },

    // =====================================================================
    // dashboard
    // =====================================================================
    async loadDashboard() {
      this.loading.dashboard = true;
      try {
        const year = new Date().getFullYear();
        // Five requests in flight at once: the entries + drafts (the week strip and
        // quick-log read them) and the streaks are independent of the dashboard numbers.
        const [dashboard, series, yoy] = await Promise.all([
          this.api('GET', '/api/dashboard'),
          this.api('GET', `/api/analytics/cumulative-series?year=${year}`),
          this.api('GET', '/api/analytics/yoy').catch(() => null),
          this.loadDays(),
          this.loadStreaks(),
          this.loadSources(),
        ]);
        // The freelance card (only with a source): the year's summary carries the share to
        // set aside and the after-tax rate; the week and month come from the blocks.
        if (this.hasFreelance() && (!this.flSummary || this._flStale || this.flSummary.year !== year)) { this.flYear = year; this.loadFlSummary(year); }
        this.weekStart = this._mondayIso(new Date());
        this.series = series;
        this.yoy = yoy;
        this.dashboard = dashboard;
        this.traj = this.buildTrajectory();
        this.$nextTick(() => this.tickUpDashboard());
      } catch (e) { this.error = e.message; }
      finally { this.loading.dashboard = false; }
    },

    // streaks & milestones
    async loadStreaks() {
      try {
        this.streakStats = await this.api('GET', '/api/streaks');
        this.checkMilestone(this.streakStats.total_logged_days);
      } catch (e) { /* non-critical widget — don't surface dashboard errors */ }
    },

    checkMilestone(totalLoggedDays) {
      const lastSeen = Number(localStorage.getItem('k-milestone-seen') || 0);
      const hit = this.MILESTONES.find(m => lastSeen < m && totalLoggedDays >= m);
      if (hit) {
        this.showToast(`🎉 Milestone: ${hit} days logged!`, 'neutral');
        localStorage.setItem('k-milestone-seen', String(hit));
      }
    },

    // ---------- hero captions --------------------------------------------
    // "Jan 2025": where the cumulative starts, as a caption rather than a sentence.
    sinceLabel() {
      const d = this.dashboard?.cumulative_start_date;
      if (!d) return '';
      return new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    },
    // "Tue 27 Oct · 08:42" — today and the live clock, in one chip.
    todayChip() {
      const d = this.dashboard ? new Date(this.dashboard.today + 'T12:00:00') : new Date();
      const label = d.toLocaleDateString('en-US', { weekday: 'short', day: 'numeric', month: 'short' });
      return this.nowDisplay ? `${label} · ${this.nowDisplay}` : label;
    },
    // "12.5 work days, 2 off" — the counts the old cards printed, now a tooltip.
    daysTitle(period) {
      return `${this.fmtDays(period.work_days)} work days, ${this.fmtDays(period.non_work_days)} off`;
    },
    yoyDelta() {
      if (!this.yoy) return 0;
      return Math.round((this.yoy.this_year.surplus_hours - this.yoy.last_year.surplus_hours) * 100) / 100;
    },
    // A bullet bar centred on zero: the fill grows right for a surplus, left for a deficit.
    bulletStyle(hours, range) {
      const w = Math.min(50, Math.abs(hours) / Math.max(range, Math.abs(hours)) * 50);
      return hours < 0 ? `left:${50 - w}%;width:${w}%` : `left:50%;width:${w}%`;
    },
    todayEntry() {
      const today = this.todayIso();
      return this.entries.find(e => e.date === today) || null;
    },

    // ---------- the trajectory ------------------------------------------
    // The cumulative balance day by day this year (solid), then a dashed line from today
    // to Dec 31 at the forecast's value. Built as markup: x-for cannot live inside <svg>.
    buildTrajectory() {
      const W = 620, H = 190, padL = 34, padR = 112, padT = 18, padB = 22;
      const today = new Date((this.dashboard?.today || this.todayIso()) + 'T12:00:00');
      const year = today.getFullYear();
      const jan1 = new Date(year, 0, 1);
      const daysInYear = (new Date(year, 11, 31) - jan1) / 86400000 + 1;
      const dayOf = iso => Math.round((new Date(iso + 'T12:00:00') - new Date(year, 0, 1, 12)) / 86400000);
      const todayIdx = dayOf(this._dateIso(today));
      const todayIso = this._dateIso(today);

      const s = this.series || { opening: 0, points: [], start: `${year}-01-01` };
      const opening = s.opening || 0;
      const startIdx = Math.max(0, s.start >= `${year}-01-01` ? dayOf(s.start) : 0);
      // Series: (startIdx, opening) then one point per logged day up to today.
      const pts = [[startIdx, opening]];
      for (const p of s.points) {
        if (p.date > todayIso) break;
        pts.push([dayOf(p.date), p.surplus_hours]);
      }
      const current = this.dashboard ? this.dashboard.cumulative.surplus_hours : pts[pts.length - 1][1];
      pts.push([todayIdx, current]);
      const fc = this.forecast();
      const projected = fc ? fc.projected : null;

      // Scale: always show zero; pad so the line never kisses the frame.
      const values = pts.map(p => p[1]).concat(projected === null ? [] : [projected], [0]);
      let lo = Math.min(...values), hi = Math.max(...values);
      const span = Math.max(hi - lo, 4);
      lo -= span * 0.12; hi += span * 0.12;
      const x = d => padL + (W - padL - padR) * d / (daysInYear - 1);
      const y = v => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo));
      const f = n => n.toFixed(1);

      // Ticks on the y axis: a "nice" step giving 3–5 labels.
      const rawStep = (hi - lo) / 5;
      const step = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500].find(v => v >= rawStep) || 1000;
      const ticks = [];
      for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);

      const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
      let svg = `<svg class="traj" viewBox="0 0 ${W} ${H}" aria-hidden="true">`;
      for (let m = 0; m < 12; m++) {
        const d0 = dayOf(this._dateIso(new Date(year, m, 1)));
        const d1 = m === 11 ? daysInYear - 1 : dayOf(this._dateIso(new Date(year, m + 1, 1)));
        svg += `<line class="traj-month" x1="${f(x(d0))}" y1="${padT}" x2="${f(x(d0))}" y2="${H - padB}"/>`;
        svg += `<text class="traj-mlabel" x="${f(x((d0 + d1) / 2))}" y="${H - 6}">${MONTHS[m]}</text>`;
      }
      for (const v of ticks) svg += `<text class="traj-ylabel" x="${padL - 6}" y="${f(y(v) + 3)}">${v > 0 ? '+' : ''}${v}</text>`;
      svg += `<line class="traj-zero" x1="${padL}" y1="${f(y(0))}" x2="${W - padR}" y2="${f(y(0))}"/>`;
      const line = pts.map(([d, v], i) => `${i ? 'L' : 'M'}${f(x(d))} ${f(y(v))}`).join('');
      const tone = current > 0.01 ? 'surplus' : current < -0.01 ? 'deficit' : 'neutral';
      svg += `<path class="traj-area ${tone}" d="${line}L${f(x(todayIdx))} ${f(y(0))}L${f(x(startIdx))} ${f(y(0))}Z"/>`;
      svg += `<path class="traj-line ${tone}" d="${line}"/>`;
      svg += `<line class="traj-today" x1="${f(x(todayIdx))}" y1="${padT}" x2="${f(x(todayIdx))}" y2="${H - padB}"/>`;
      if (projected !== null) {
        const ex = x(daysInYear - 1), ey = y(projected);
        svg += `<path class="traj-proj" d="M${f(x(todayIdx))} ${f(y(current))}L${f(ex)} ${f(ey)}"/>`;
        svg += `<circle class="traj-end-dot" cx="${f(ex)}" cy="${f(ey)}" r="3.5"/>`;
        svg += `<text class="traj-end" x="${f(ex + 8)}" y="${f(ey + 1)}">${this.formatSurplus(projected)}</text>`;
        svg += `<text class="traj-end-sub" x="${f(ex + 8)}" y="${f(ey + 11)}">DEC 31 · AT THIS RATE</text>`;
      }
      svg += `<circle class="traj-dot" cx="${f(x(todayIdx))}" cy="${f(y(current))}" r="4"/>`;
      svg += '</svg>';

      const aria = projected === null
        ? `Cumulative balance this year: ${this.formatSurplus(current)} today.`
        : `Cumulative balance this year: ${this.formatSurplus(current)} today, ${this.formatSurplus(projected)} by December 31 at this rate.`;
      return { svg, aria };
    },

    // Draw the line from Jan 1 to today, then fade the projection in after it.
    animateTrajectory(wrap) {
      const line = wrap.querySelector('.traj-line');
      if (!line) return;
      const tail = wrap.querySelectorAll('.traj-proj, .traj-end-dot, .traj-end, .traj-end-sub, .traj-dot');
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        tail.forEach(el => el.classList.add('traj-shown'));
        return;
      }
      const L = line.getTotalLength();
      line.style.strokeDasharray = String(L);
      line.style.strokeDashoffset = String(L);
      line.style.transition = 'none';
      requestAnimationFrame(() => {
        line.style.transition = 'stroke-dashoffset 1.4s cubic-bezier(.3,.7,.3,1) .1s';
        line.style.strokeDashoffset = '0';
        tail.forEach(el => el.classList.add('traj-shown'));
      });
    },

    // ---------- week strip -----------------------------------------------
    // Bar heights as a share of the strip's axis: the tallest of the week's days or
    // 1.25 × the target, so a normal day sits at four fifths and a long one still fits.
    weekAxisHours() {
      const days = this.weekDays();
      const target = Math.max(...days.map(d => d.target), this.dashboard?.daily_target_hours || 8);
      const tallest = Math.max(...days.map(d => d.barHours || 0));
      return Math.max(target * 1.25, tallest);
    },
    weekBarPct(hours) {
      const axis = this.weekAxisHours();
      return axis ? Math.min(100, Math.round(hours / axis * 1000) / 10) : 0;
    },

    // ---------- vacation notches ----------------------------------------
    // Drafted vacation after today, this year, on dates still free.
    plannedVacationDays() {
      const today = this.todayIso();
      const year = today.slice(0, 4);
      let days = 0;
      for (const p of this.plans) {
        if (p.exists || p.day_type !== 'vacation' || p.date <= today || !p.date.startsWith(year)) continue;
        days += p.fraction ?? 1;
      }
      return Math.round(days * 100) / 100;
    },
    vacationLeftAfterPlan() {
      const v = this.vacationStatus();
      if (!v) return 0;
      return Math.max(0, Math.round((v.remaining - this.plannedVacationDays()) * 100) / 100);
    },
    // One notch per budgeted day: used (filled, a fraction fills part of it), planned (dashed), left (hollow).
    vacationNotches() {
      const v = this.vacationStatus();
      if (!v) return [];
      const used = v.used, planned = this.plannedVacationDays();
      const total = Math.ceil(v.budget);
      const notches = [];
      for (let i = 0; i < total; i++) {
        let kind = 'left', style = '';
        if (i + 1 <= used) kind = 'used';
        else if (i < used) { kind = 'part'; style = `--fill:${Math.round((used - i) * 100)}%`; }
        else if (i < used + planned) kind = 'planned';
        // The last notch of a half-day budget (22.5) is itself a half.
        if (i === total - 1 && v.budget % 1) style += (style ? ';' : '') + `--notch:${Math.round((v.budget % 1) * 100)}%`;
        notches.push({ i, kind, style });
      }
      return notches;
    },

    // W1 — animate the two small metric values from 0 → real (ease-out cubic, 600ms). The big
    // balance is an odometer (odoSet) and rolls by itself.
    tickUpDashboard() {
      if (!this.dashboard) return;
      const targets = {
        week:       Math.abs(this.dashboard.week.surplus_hours),
        month:      Math.abs(this.dashboard.month.surplus_hours),
      };
      // Unchanged numbers (a background refresh) or a dashboard that isn't showing: no show.
      const settled = this.animWeek === targets.week && this.animMonth === targets.month;
      if (settled || this.tab !== 'dashboard' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.animWeek = targets.week; this.animMonth = targets.month;
        return;
      }
      this.animWeek = 0; this.animMonth = 0;
      const start = performance.now();
      const token = (this._tickToken = (this._tickToken || 0) + 1);
      const tick = (now) => {
        if (token !== this._tickToken) return;  // a newer animation took over
        const t = Math.min(1, (now - start) / 600);
        const e = 1 - Math.pow(1 - t, 3); // ease-out cubic
        this.animWeek       = targets.week       * e;
        this.animMonth      = targets.month      * e;
        if (t < 1) requestAnimationFrame(tick);
        else { this.animWeek = targets.week; this.animMonth = targets.month; }
      };
      requestAnimationFrame(tick);
    },

    // =====================================================================
    // log form
    // =====================================================================
    // `keepMonth`: the calendar stays where it was (a click on the day being edited, Escape), so
    // leaving an October day does not jump the calendar back to this month.
    openNewEntry({ keepMonth = false } = {}) {
      this.editingDate = null;
      this.notesOpen = false;
      const now = new Date();
      if (!keepMonth) { this.calYear = now.getFullYear(); this.calMonth = now.getMonth(); }
      this.form = {
        date: this.todayIso(),
        day_type: 'work',
        start_time: this.settingsForm.default_start_time || '09:00',
        end_time: this.settingsForm.default_end_time || '17:00',
        notes: '',
        breaks: [],
        leave_hours: null,
      };
    },

    // Day type changed in the form: a non-work type starts as a whole day (slider at the
    // date's target); the hours are kept when switching between types.
    onDayTypeChange() {
      if (this.form.day_type === 'work') { this.form.leave_hours = null; return; }
      const t = this.formTarget();
      if (this.form.leave_hours == null || this.form.leave_hours > t) this.form.leave_hours = t;
    },
    formTarget() { return this.targetForDate(this.form.date || this.todayIso()); },
    // Slider top: the target rounded up to the next quarter hour, so a target that isn't
    // a multiple of 0.25 (7.33h) still has a reachable "whole day" position.
    leaveSliderMax() { return Math.ceil(this.formTarget() * 4 - 1e-9) / 4; },
    // Fraction to send: leave hours over the date's target; at or above it, the whole day.
    formFraction() {
      if (this.form.day_type === 'work') return 1;
      const t = this.formTarget();
      const h = Number(this.form.leave_hours);
      if (!(h > 0) || h >= t - 1e-9) return 1;
      return Math.round((h / t) * 10000) / 10000;
    },
    formIsPartial() { return this.form.day_type !== 'work' && this.formFraction() < 1; },
    // Whether the start/end/breaks fields apply: work days and the worked part of a
    // partial leave day.
    formHasTimes() { return this.form.day_type === 'work' || this.formIsPartial(); },
    leaveSliderLabel() {
      const t = this.formTarget();
      if (!this.formIsPartial()) return `Full day (${this.fmtHours(t)})`;
      const off = Math.round(this.formFraction() * t * 100) / 100;
      return `${this.fmtHours(off)} off · ${this.fmtHours(t - off)} to work`;
    },

    // Check whether *dateStr* already has a saved entry.
    // If yes → populate the form and switch to edit mode (Save will PUT).
    // If no  → do nothing (form stays in new-entry mode).
    async probeDate(dateStr) {
      if (!dateStr) return;
      const seq = (this._probeSeq = (this._probeSeq || 0) + 1);
      const res = await fetch(`/api/entries/${dateStr}`, {
        headers: { Accept: 'application/json' },
      });
      if (seq !== this._probeSeq) return;  // the answer of an older click: a newer one took over
      if (res.status === 404) return;
      if (!res.ok) { this.error = `${res.status} ${res.statusText}`; return; }
      const entry = await res.json();
      if (seq !== this._probeSeq) return;
      this.editEntry(entry);
    },

    // ── Log calendar ──────────────────────────────────────────────────────────

    calMonthLabel() {
      return new Date(this.calYear, this.calMonth, 1)
        .toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    },

    calDays() {
      const year = this.calYear;
      const month = this.calMonth;
      const todayStr = this.todayIso();
      const selectedStr = this.form.date;
      const entryMap = {};
      for (const e of this.entries) entryMap[e.date] = e;
      const drafts = this.draftMap();
      const flDays = new Set(this.blocks.map(b => b.date));  // a brass dot marks freelance work
      const firstDow = (new Date(year, month, 1).getDay() + 6) % 7; // Mon-first
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const cells = [];
      for (let i = 0; i < firstDow; i++) cells.push({ padded: true, key: `pad-${i}` });
      for (let d = 1; d <= daysInMonth; d++) {
        const mm = String(month + 1).padStart(2, '0');
        const dd = String(d).padStart(2, '0');
        const dateStr = `${year}-${mm}-${dd}`;
        const entry = entryMap[dateStr] || null;
        cells.push({ padded: false, key: dateStr, date: dateStr, day: d,
          cls: this.dayCellCls(entry, drafts[dateStr]), style: this.entryCellStyle(entry),
          isToday: dateStr === todayStr, isSelected: dateStr === selectedStr,
          fl: flDays.has(dateStr) });
      }
      return cells;
    },

    // The Log calendar by rows: its week button (ISO number, range, whether the week has
    // anything to open) and the row's day cells, which are exactly calDays()'s.
    calWeeks() {
      const cells = this.calDays();
      const todayMonday = this._mondayIso(new Date());
      const selected = this.form.date;
      const rows = [];
      for (let i = 0; i < cells.length; i += 7) {
        const row = cells.slice(i, i + 7);
        const first = row.find(c => !c.padded);
        const monday = this._mondayIso(new Date(first.date + 'T12:00:00'));
        const sunday = this._addDaysIso(monday, 6);
        const no = this.isoWeekNo(monday);
        const range = this._weekRange(monday);
        rows.push({
          key: 'wk-' + monday, monday, no, range, cells: row,
          label: `Week ${no}, ${range}`, title: `W${no} · ${range}`,
          has: this.entries.some(e => e.date >= monday && e.date <= sunday)
            || this.blocks.some(b => b.date >= monday && b.date <= sunday),
          isCurrent: monday === todayMonday,
          isSelected: !!selected && selected >= monday && selected <= sunday,
        });
      }
      return rows;
    },

    // From a week button of the Log calendar to that week in Days: Employee when the week has an
    // entry (its separator, in view and flashed), else Freelance (its row, opened).
    async calOpenWeek(monday) {
      const sunday = this._addDaysIso(monday, 6);
      const mine = this.entries.filter(e => e.date >= monday && e.date <= sunday);
      if (!mine.length) {
        const blocks = this.blocks.filter(b => b.date >= monday && b.date <= sunday);
        if (!blocks.length) return;
        await this._openFlWeek(monday, [...new Set(blocks.map(b => b.source_id))], this._daysYearFor(blocks));
        return;
      }
      this.daysMode = 'employee';
      this.sortKey = 'date';
      this.notesQuery = '';
      this.daysWeekOpen = { ...this.daysWeekOpen, [monday]: true };
      this.daysYear = this._daysYearFor(mine);
      await this.go('days');
      // The Days tab scrolls to today once it has rendered; this scroll has to come after it.
      this.$nextTick(() => setTimeout(() => this._scrollToWeek(monday, 0), 350));
    },
    // Scrolls the line of a week into view and flashes it, in either mode (Employee `eweek-`, Freelance `wk-`).
    _scrollToWeek(monday, tries = 0) {
      const el = document.getElementById('eweek-' + monday) || document.getElementById('wk-' + monday);
      if (!el) { if (tries < 4) setTimeout(() => this._scrollToWeek(monday, tries + 1), 200); return; }
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      el.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'center' });
      this.daysFlashWeek = monday;
      setTimeout(() => { if (this.daysFlashWeek === monday) this.daysFlashWeek = ''; }, 2200);
    },
    // "all" stays "all"; a year filter becomes the one year of these rows, or "all" if they span two.
    _daysYearFor(rows) {
      if (this.daysYear === 'all') return 'all';
      const years = new Set(rows.map(r => r.date.slice(0, 4)));
      return years.size === 1 ? [...years][0] : 'all';
    },

    calPrev() {
      if (this.calMonth === 0) { this.calMonth = 11; this.calYear--; }
      else this.calMonth--;
    },

    calNext() {
      if (this.calMonth === 11) { this.calMonth = 0; this.calYear++; }
      else this.calMonth++;
    },
    calSetYear(y) { this.calYear = y; },

    async calSelectDay(dateStr) {
      if (this.editingDate === dateStr) { this.openNewEntry({ keepMonth: true }); return; }
      // Another day while editing: leave the edit (unsaved changes are discarded) and
      // start from a fresh form on that day.
      if (this.editingDate) this.openNewEntry({ keepMonth: true });
      this.form.date = dateStr;
      this.notesOpen = false;
      await this.probeDate(dateStr);
      if (this.form.date !== dateStr) return;  // a newer click took over while we waited
      // A drafted day with no entry yet: start the form from the draft.
      const draft = this.draftMap()[dateStr];
      if (!this.editingDate && draft) {
        this.form.day_type = draft.day_type;
        this.form.notes = draft.notes || '';
        this.form.leave_hours = draft.leave_hours;
      }
    },

    // ── Week strip (dashboard) ──────────────────────────────────────────────────
    // All figures come straight from /api/entries — summing a week's entries
    // reproduces the backend's `summarize()`, so the strip's total stays in lock-step
    // with the "This week" chip without a dedicated endpoint.

    // Local-date ISO (avoids the UTC drift of toISOString on date-only values).
    _dateIso(d) {
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${d.getFullYear()}-${mm}-${dd}`;
    },

    // Monday (ISO week start) of the week containing `d`.
    _mondayIso(d) {
      const dow = (d.getDay() + 6) % 7; // Mon=0…Sun=6
      return this._dateIso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - dow));
    },

    ensureWeekStart() {
      if (!this.weekStart) this.weekStart = this._mondayIso(new Date());
    },

    // Seven day objects (Mon→Sun) for the displayed week.
    weekDays() {
      this.ensureWeekStart();
      const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const todayStr = this.todayIso();
      const entryMap = {};
      for (const e of this.entries) entryMap[e.date] = e;
      const drafts = this.draftMap();
      const base = new Date(this.weekStart + 'T00:00:00');
      const days = [];
      for (let i = 0; i < 7; i++) {
        const d = new Date(base.getFullYear(), base.getMonth(), base.getDate() + i);
        const iso = this._dateIso(d);
        const entry = entryMap[iso] || null;
        const draft = entry ? null : (drafts[iso] || null);
        // The bar: hours worked plus hours off, so a day off stands as tall as a day worked.
        const barHours = entry ? Math.round((entry.net_hours + (entry.leave_hours || 0)) * 100) / 100 : 0;
        const target = entry ? Math.round((entry.target_hours + (entry.leave_hours || 0)) * 100) / 100
          : (this.dashboard?.daily_target_hours || 8);
        const flHours = this.blockHours(this.blocksOn(iso));
        days.push({
          iso, label: DOW[i], dayNum: d.getDate(), entry, draft, barHours, target, flHours,
          cls: this.dayCellCls(entry, draft), style: this.entryCellStyle(entry),
          isToday: iso === todayStr, isWeekend: i >= 5, isFuture: iso > todayStr,
        });
      }
      return days;
    },

    weekLabel() {
      this.ensureWeekStart();
      const base = new Date(this.weekStart + 'T00:00:00');
      const end = new Date(base.getFullYear(), base.getMonth(), base.getDate() + 6);
      const sameMonth = base.getMonth() === end.getMonth();
      const startLabel = base.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      const endLabel = end.toLocaleDateString('en-US', sameMonth ? { day: 'numeric' } : { month: 'short', day: 'numeric' });
      return `${startLabel} – ${endLabel}`;
    },

    // Week totals — sums the logged entries only, matching the backend summary.
    weekSummary() {
      let net = 0, target = 0, surplus = 0, workDays = 0, offDays = 0;
      for (const { entry } of this.weekDays()) {
        if (!entry) continue;
        net += entry.net_hours;
        target += entry.target_hours;
        surplus += entry.surplus_hours;
        // A partial leave day splits between the two counts.
        const off = entry.day_type === 'work' ? 0 : entry.fraction;
        workDays += 1 - off; offDays += off;
      }
      return {
        net: Math.round(net * 100) / 100,
        target: Math.round(target * 100) / 100,
        surplus: Math.round(surplus * 100) / 100,
        work_days: Math.round(workDays * 100) / 100, non_work_days: Math.round(offDays * 100) / 100,
      };
    },

    // Open a day in the Log tab — edit mode if it already has an entry, else new.
    async weekSelectDay(iso) { await this.openDayInLog(iso); },
    async openDayInLog(iso) {
      this.openNewEntry();
      this.form.date = iso;
      const d = new Date(iso + 'T00:00:00');
      this.calYear = d.getFullYear();
      this.calMonth = d.getMonth();
      await this.go('log');
      await this.probeDate(iso);
    },

    // ── Bulk log modal ─────────────────────────────────────────────────────────

    openBulkModal() {
      const now = new Date();
      this.bulkModal = { open: true, year: now.getFullYear(), month: now.getMonth(), selected: [], _dragging: false, _dragAnchor: null, _dragCurrent: null, _startX: 0, _startY: 0, submitting: false };
    },

    closeBulkModal() { this.bulkModal.open = false; },

    bulkCalLabel() {
      return new Date(this.bulkModal.year, this.bulkModal.month, 1)
        .toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    },

    bulkCalPrev() {
      if (this.bulkModal.month === 0) { this.bulkModal.month = 11; this.bulkModal.year--; }
      else this.bulkModal.month--;
    },

    bulkCalNext() {
      if (this.bulkModal.month === 11) { this.bulkModal.month = 0; this.bulkModal.year++; }
      else this.bulkModal.month++;
    },

    bulkCalDays() {
      const { year, month } = this.bulkModal;
      const todayStr = this.todayIso();
      const entryMap = {};
      for (const e of this.entries) entryMap[e.date] = e;
      const firstDow = (new Date(year, month, 1).getDay() + 6) % 7; // Mon-first
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const cells = [];
      for (let i = 0; i < firstDow; i++) cells.push({ padded: true, key: `bpad-${i}` });
      for (let d = 1; d <= daysInMonth; d++) {
        const mm = String(month + 1).padStart(2, '0');
        const dd = String(d).padStart(2, '0');
        const dateStr = `${year}-${mm}-${dd}`;
        const entry = entryMap[dateStr] || null;
        const dow = new Date(year, month, d).getDay();
        const weekend = dow === 0 || dow === 6;
        cells.push({ padded: false, key: dateStr, date: dateStr, day: d,
          cls: this.entryCellCls(entry), style: this.entryCellStyle(entry),
          isToday: dateStr === todayStr, weekend });
      }
      return cells;
    },

    _bulkRange(a, b) {
      const sa = new Date(a + 'T00:00:00'), sb = new Date(b + 'T00:00:00');
      const [start, end] = sa <= sb ? [sa, sb] : [sb, sa];
      const out = [];
      const cur = new Date(start);
      while (cur <= end) {
        const y = cur.getFullYear();
        const mo = String(cur.getMonth() + 1).padStart(2, '0');
        const d = String(cur.getDate()).padStart(2, '0');
        out.push(`${y}-${mo}-${d}`);
        cur.setDate(cur.getDate() + 1);
      }
      return out;
    },

    bulkIsHighlighted(dateStr) {
      if (!dateStr) return false;
      if (this.bulkModal.selected.includes(dateStr)) return true;
      if (this.bulkModal._dragging && this.bulkModal._dragAnchor && this.bulkModal._dragCurrent) {
        return this._bulkRange(this.bulkModal._dragAnchor, this.bulkModal._dragCurrent).includes(dateStr);
      }
      return false;
    },

    bulkMousedown(event, dateStr) {
      if (!dateStr) return;
      // Record anchor + start position but don't start dragging yet.
      // _dragging only becomes true once the pointer moves to a different cell,
      // preventing spurious Alpine re-render mouseover events from acting as drags.
      this.bulkModal._dragAnchor = dateStr;
      this.bulkModal._dragCurrent = dateStr;
      this.bulkModal._dragging = false;
      this.bulkModal._startX = event.clientX;
      this.bulkModal._startY = event.clientY;
    },

    bulkGridMove(event) {
      // Only track movement after 4px threshold to avoid micro-jitter false drags
      if (!this.bulkModal._dragAnchor) return;
      const dx = event.clientX - this.bulkModal._startX;
      const dy = event.clientY - this.bulkModal._startY;
      if (Math.sqrt(dx * dx + dy * dy) < 4) return;

      const btn = event.target.closest('[data-bdate]');
      const dateStr = btn?.dataset.bdate;
      if (!dateStr || dateStr === this.bulkModal._dragCurrent) return;
      this.bulkModal._dragging = true;
      this.bulkModal._dragCurrent = dateStr;
    },

    bulkMouseup() {
      const { _dragAnchor, _dragging, _dragCurrent, selected } = this.bulkModal;
      if (_dragAnchor) {
        if (_dragging) {
          // Drag ended: add full range (union with existing selection)
          for (const d of this._bulkRange(_dragAnchor, _dragCurrent)) {
            if (!selected.includes(d)) selected.push(d);
          }
        } else {
          // Simple click: toggle the anchor cell
          const idx = selected.indexOf(_dragAnchor);
          if (idx === -1) selected.push(_dragAnchor);
          else selected.splice(idx, 1);
        }
      }
      this.bulkModal._dragging = false;
      this.bulkModal._dragAnchor = null;
      this.bulkModal._dragCurrent = null;
    },

    async bulkSubmit(dayType) {
      if (!this.bulkModal.selected.length || this.bulkModal.submitting) return;
      this.bulkModal.submitting = true;
      try {
        const result = await this.api('POST', '/api/entries/batch', { dates: this.bulkModal.selected, day_type: dayType });
        await this.loadDays();
        this.closeBulkModal();
        const n = result.created.length;
        const s = result.skipped.length;
        this.showToast(
          s > 0 ? `${n} logged, ${s} skipped (already existed)` : `${n} day${n !== 1 ? 's' : ''} logged`,
          'neutral',
        );
      } catch (e) {
        this.error = e.message;
        this.bulkModal.submitting = false;
      }
    },

    // Returns {net_hours, target_hours, surplus_hours} from current form state,
    // or null when the form isn't complete enough to preview.
    logPreview() {
      const f = this.form;
      if (!this.formHasTimes()) return null;
      const netHours = this._formNetHours();
      if (f.day_type === 'work' && netHours === null) return null;
      return this._formNumbers(netHours ?? 0);
    },

    // Net hours from the form's times, or null while the span isn't usable yet.
    _formNetHours() {
      const f = this.form;
      if (!f.start_time || !f.end_time) return null;
      const [sh, sm] = f.start_time.split(':').map(Number);
      const [eh, em] = f.end_time.split(':').map(Number);
      const totalMins = (eh * 60 + em) - (sh * 60 + sm);
      if (totalMins <= 0) return null;
      const breakMins = f.breaks.reduce((s, b) => s + (Number(b.break_minutes) || 0), 0);
      return Math.round(Math.max(0, totalMins - breakMins) / 60 * 100) / 100;
    },
    // net / target / surplus for the form, mirroring the server's daily_target_for:
    // work and flex charge the whole target, other leave only the worked share.
    _formNumbers(netHours) {
      const t = this.formTarget();
      const frac = this.formFraction();
      const type = this.form.day_type;
      const target = type === 'work' || type === 'flex' ? t : Math.round(t * (1 - frac) * 100) / 100;
      return {
        net_hours: netHours,
        target_hours: target,
        surplus_hours: Math.round((netHours - target) * 100) / 100,
      };
    },

    // =====================================================================
    // the day ribbon (Log): the day drawn from 06:00 to midnight, and dragged
    // =====================================================================
    // The timed blocks of the selected day; an hours-only block has no place in the day.
    _drTimed() {
      if (!this.hasFreelance()) return [];
      const out = [];
      for (const b of this.flDayBlocks()) {
        const s = drMin(b.start_time), e = drMin(b.end_time);
        if (s !== null && e !== null && e > s) out.push({ b, s, e });
      }
      return out;
    },
    // The range is frozen while a drag is in progress: the strip must not rescale under the pointer.
    _drLo(d) { return _dr.active ? _dr.lo : drLo(d, this._drTimed().map(t => t.s)); },

    // Everything the ribbon draws, computed once per render: positions are percentages of the range.
    dayRibbon() {
      const d = drDay(this.form), timed = this._drTimed(), hh = drHHMM;
      const lo = _dr.active ? _dr.lo : drLo(d, timed.map(t => t.s));
      const pct = m => drPct(m, lo);
      const at = (m, w) => `left:${pct(m).toFixed(3)}%` + (w === undefined ? '' : `;width:${w.toFixed(3)}%`);
      const span = (a, z) => at(a, pct(z) - pct(a));
      const tagAt = m => `--x:${pct(m).toFixed(3)}%`;
      const p = this.logPreview(), live = this.drActive;
      const r = { lo, hasFl: this.hasFreelance(), ticks: drTicks(lo), items: [], flag: null, over: null, miss: null, now: null, blocks: [], ghost: null, tag: null };
      if (d.ok) {
        const lim = drLimits(d, lo), dash = drDashes(d);
        const on = (kind, i = -1) => !!live && live.kind === kind && live.i === i;
        const grip = (kind, i, m, label, text, range) => ({
          key: kind + i, kind, i, slider: true, cls: `dr-grip dr-grip--${kind}` + (on(kind, i) ? ' is-live' : ''),
          style: at(m), label, text, now: m, min: range[0], max: range[1],
        });
        r.items.push(grip('start', -1, d.s, 'Start time', `Start ${hh(d.s)}`, lim.start));
        r.items.push({
          key: 'bar', kind: 'bar', i: -1, slider: true, cls: 'dr-bar' + (on('bar') ? ' is-live' : ''), style: span(d.s, d.e),
          label: 'Day', text: `Day from ${hh(d.s)} to ${hh(d.e)}`, now: d.s, min: d.s + lim.day[0], max: d.s + lim.day[1],
        });
        for (const b of d.ranged) {
          const room = drRoom(d, b), name = `Break ${b.i + 1}`;
          r.items.push({
            key: 'nbody' + b.i, kind: 'nbody', i: b.i, slider: true, style: span(b.s, b.e), label: name,
            cls: 'dr-notch' + (on('nbody', b.i) ? ' is-live' : '') + (live && live.off && live.i === b.i && live.kind === 'nbody' ? ' is-off' : ''),
            text: `Break from ${hh(b.s)} to ${hh(b.e)}`, now: b.s, min: room[0], max: room[1] - (b.e - b.s),
          });
          r.items.push(grip('nstart', b.i, b.s, `${name} start`, `${name} start ${hh(b.s)}`, [room[0], b.e - DR_STEP]));
          r.items.push(grip('nend', b.i, b.e, `${name} end`, `${name} end ${hh(b.e)}`, [b.s + DR_STEP, room[1]]));
        }
        for (const k of dash) {
          r.items.push({
            key: 'dash' + k.i, kind: 'dash', i: k.i, slider: false, style: span(k.s, k.e),
            cls: 'dr-notch dr-notch--dash' + (on('dash', k.i) ? ' is-live' : '') + (live && live.off && live.i === k.i && live.kind === 'dash' ? ' is-off' : ''),
            title: `${this.minutesToLabel(k.min)} break, no time yet: drag it to place it`,
          });
        }
        r.items.push(grip('end', -1, d.e, 'End time', `End ${hh(d.e)}`, lim.end));

        const target = p ? p.target_hours : 0, reached = drFlag(d, dash, target);
        if (reached !== null) {
          r.flag = { style: at(reached), title: `Target reached at ${hh(reached)}` };
          if (reached < d.e - 0.01) r.over = { style: span(reached, d.e) };
        } else if (p && p.net_hours < target - 1e-6) {
          const short = Math.min((target - p.net_hours) * 60, DR_HI - d.e);
          if (short > 0.5) r.miss = { style: span(d.e, d.e + short), title: `${this.fmtHours(target - p.net_hours)} short of the target` };
        }

        if (live && live.kind !== 'flnew' && p) {
          const k = d.ranged.find(x => x.i === live.i);
          let mid = null, big = '';
          if (live.kind === 'start') { mid = d.s; big = hh(d.s); }
          else if (live.kind === 'end') { mid = d.e; big = hh(d.e); }
          else if (live.kind === 'nstart' && k) { mid = k.s; big = hh(k.s); }
          else if (live.kind === 'nend' && k) { mid = k.e; big = hh(k.e); }
          else if ((live.kind === 'nbody' || live.kind === 'dash') && k) { mid = (k.s + k.e) / 2; big = `${hh(k.s)}–${hh(k.e)}`; }
          else if (live.kind === 'bar' || live.kind === 'new') { mid = (d.s + d.e) / 2; big = `${hh(d.s)}–${hh(d.e)}`; }
          if (mid !== null && live.off) r.tag = { style: tagAt(mid), big: 'Remove', net: '', delta: '', cls: '' };
          else if (mid !== null) r.tag = { style: tagAt(mid), big, net: this.fmtHours(p.net_hours), delta: this.formatSurplus(p.surplus_hours), cls: this.surplusClass(p.surplus_hours) };
        }
      }
      r.blocks = timed.map(({ b, s, e }) => ({
        id: b.id, s, e, editing: this.flForm.id === b.id,
        style: span(s, e) + ';--src:' + this.sourceColor(b.source_id),
        label: `Edit block ${b.source_name} ${b.start_time} to ${b.end_time}`, title: `${b.source_name} · ${b.start_time}–${b.end_time}`,
      }));
      if (live && live.kind === 'flnew') {
        const s = drMin(this.flForm.start_time), e = drMin(this.flForm.end_time);
        if (s !== null && e !== null && e > s) {
          r.ghost = { style: span(s, e) };
          r.tag = { style: tagAt((s + e) / 2), big: `${hh(s)}–${hh(e)}`, net: this.fmtHours(this.flFormHours()), delta: '', cls: '' };
        }
      }
      if (this.form.date === this.todayIso()) {
        const now = drMin(this.nowDisplay);
        if (now !== null && now >= lo) r.now = { style: at(now), title: `Now ${this.nowDisplay}` };
      }
      _dr.cur = r;
      return r;
    },

    // ---------- the pointer ----------------------------------------------------------------
    // One code path for mouse, pen and finger. The handle nearest the pointer wins, within half of its hit
    // area (24px with a mouse, 44px with a finger). A finger on the body of the bar, on an empty stretch or on
    // a block waits until it has moved sideways by 6px: until then it may be a swipe that scrolls the page.
    drDown(ev) {
      if (_dr.active && !(_dr.field && _dr.field.isConnected)) _dr.active = false;  // the strip went away mid-drag
      if (_dr.active || (ev.pointerType === 'mouse' && ev.button !== 0)) return;
      const laneEl = ev.target.closest('.dr-lane'), r = _dr.cur;
      if (!laneEl || !r) return;
      const field = ev.currentTarget, box = field.getBoundingClientRect(), lane = laneEl.getBoundingClientRect();
      const lo = r.lo, d = drDay(this.form), dashes = drDashes(d);
      const x = ev.clientX - box.left, pm = lo + x / box.width * (DR_HI - lo);
      const px = m => (m - lo) / (DR_HI - lo) * box.width;
      const reach = ev.pointerType === 'mouse' ? 12 : 22;
      let hit = null;
      if (laneEl.dataset.lane === 'emp') {
        if (!d.ok) {
          hit = { kind: 'new' };
        } else {
          // `dir` points from a grip into its own span; `w` is that span in pixels. A grip reaches the whole
          // way outwards but only a third of its span inwards, so a short notch keeps a middle to be moved by.
          const bar = px(d.e) - px(d.s);
          const grips = [{ kind: 'start', i: -1, m: d.s, w: bar, dir: 1 }, { kind: 'end', i: -1, m: d.e, w: bar, dir: -1 }];
          for (const b of d.ranged) {
            const w = px(b.e) - px(b.s);
            grips.push({ kind: 'nstart', i: b.i, m: b.s, w, dir: 1 }, { kind: 'nend', i: b.i, m: b.e, w, dir: -1 });
          }
          let best = Infinity;
          for (const g of grips) {
            const gap = Math.abs(px(g.m) - x), inward = (x - px(g.m)) * g.dir > 0;
            if (gap <= (inward ? Math.min(reach, g.w / 3) : reach) && gap < best) { best = gap; hit = g; }
          }
          // inside a break, the break's body beats the bar's end grips: a break at the edge of the day stays movable
          const inside = d.ranged.find(b => pm > b.s && pm < b.e);
          if (hit && inside && (hit.kind === 'start' || hit.kind === 'end')) hit = { kind: 'nbody', i: inside.i };
          if (!hit) {
            const note = d.ranged.find(b => pm >= b.s && pm <= b.e), dash = dashes.find(k => pm >= k.s && pm <= k.e);
            if (note) hit = { kind: 'nbody', i: note.i };
            else if (dash) hit = { kind: 'dash', i: dash.i };
            else if (pm >= d.s && pm <= d.e) hit = { kind: 'bar' };
          }
        }
      } else {
        const b = r.blocks.find(t => x >= px(t.s) - 3 && x <= px(t.e) + 3);
        hit = b ? { kind: 'block', id: b.id } : { kind: 'flnew' };
      }
      if (!hit) return;
      Object.assign(_dr, {
        active: true, field, moved: false, kind: hit.kind, i: hit.i ?? -1, id: hit.id ?? null, pid: ev.pointerId,
        pending: ev.pointerType !== 'mouse' && ['bar', 'new', 'flnew', 'block'].includes(hit.kind),
        x0: ev.clientX, y0: ev.clientY, left: box.left, width: box.width, laneTop: lane.top, laneBottom: lane.bottom,
        lo, pm0: pm, off: hit.m === undefined ? 0 : hit.m - pm, base: d, dashes, flag0: !!r.flag,
        orig: { start_time: this.form.start_time, end_time: this.form.end_time, breaks: this.form.breaks.map(b => ({ ...b })), fl: { ...this.flForm } },
      });
      field.setPointerCapture(ev.pointerId);
    },
    drMove(ev) {
      if (!_dr.active || ev.pointerId !== _dr.pid) return;
      const at = x => _dr.lo + (x - _dr.left) / _dr.width * (DR_HI - _dr.lo);
      if (_dr.pending) {
        if (Math.abs(ev.clientX - _dr.x0) < 6) return;
        _dr.pending = false;
        _dr.pm0 = at(ev.clientX);  // the 6px it waited are not a jump
        _dr.x0 = ev.clientX;
        _dr.y0 = ev.clientY;
      } else if (!_dr.moved && Math.hypot(ev.clientX - _dr.x0, ev.clientY - _dr.y0) < 4) {
        return;
      }
      if (!_dr.moved) { _dr.moved = true; this.drActive = { kind: _dr.kind, i: _dr.i, off: false }; }
      const pm = at(ev.clientX), delta = drSnap(pm - _dr.pm0), before = this.logPreview()?.net_hours ?? null;
      let changed = false;
      switch (_dr.kind) {
        case 'start': case 'end': changed = this._drEdge(_dr.kind, drSnap(pm + _dr.off)); break;
        case 'bar': changed = this._drDay(delta, _dr.base); break;
        case 'nstart': case 'nend': changed = this._drBreakEdge(_dr.i, _dr.kind, drSnap(pm + _dr.off), _dr.base); break;
        case 'nbody': case 'dash': {
          // off the lane by more than 40px, a release takes the break away
          const off = ev.clientY < _dr.laneTop - 40 || ev.clientY > _dr.laneBottom + 40;
          if (this.drActive.off !== off) this.drActive = { ...this.drActive, off };
          if (!off) changed = _dr.kind === 'nbody' ? this._drBreakMove(_dr.i, delta, _dr.base) : this._drDash(_dr.i, delta);
          break;
        }
        case 'new': changed = this._drNew(drSnap(_dr.pm0), drSnap(pm)); break;
        case 'flnew': changed = this._drFl(drSnap(_dr.pm0), drSnap(pm)); break;
      }
      if (changed) this._drBuzz(before);
    },
    drUp(ev) {
      if (!_dr.active || ev.pointerId !== _dr.pid) return;
      const field = ev.currentTarget, { kind, moved, i } = _dr, away = !!this.drActive?.off;
      _dr.active = false;
      _dr.pending = false;
      try { field.releasePointerCapture(ev.pointerId); } catch { /* already let go */ }
      this.drActive = null;
      if (!moved) { this._drTap(ev, kind, field); return; }
      _dr.lastTap = { at: -1e9, x: 0 };
      if (away) this._drRemove(i, field);
      else this._drLand(kind, i, field);
    },
    // A press that did not move: a block opens in the editor, two quick ones on the bar add a break.
    _drTap(ev, kind, field) {
      if (kind === 'block') {
        const b = this.flDayBlocks().find(x => x.id === _dr.id);
        if (b) this.flEdit(b);
        return;
      }
      if (kind !== 'bar' && kind !== 'start' && kind !== 'end') return;  // the grips are part of the bar
      const last = _dr.lastTap;
      if (Math.abs(ev.clientX - last.x) <= 12 && ev.timeStamp - last.at < 450) {
        _dr.lastTap = { at: -1e9, x: 0 };
        this._drAddBreak(_dr.lo + (ev.clientX - _dr.left) / _dr.width * (DR_HI - _dr.lo), field);
      } else {
        _dr.lastTap = { at: ev.timeStamp, x: ev.clientX };
      }
    },
    // The browser took the gesture (a swipe that scrolls the page) or it was cut short: the day goes back.
    drCancel(ev) {
      if (!_dr.active || ev.pointerId !== _dr.pid) return;
      _dr.active = false;
      _dr.pending = false;
      this.drActive = null;
      const o = _dr.orig, f = this.form;
      f.start_time = o.start_time;
      f.end_time = o.end_time;
      o.breaks.forEach((b, i) => { if (f.breaks[i]) Object.assign(f.breaks[i], b); });
      if (_dr.kind === 'flnew') this.flForm = { ...o.fl };
    },
    // After a drag: the handle settles with a spring, the flag waves if the day just reached the target, and a
    // block dragged out on the freelance lane takes you to its editor, "+ Add block" ready.
    _drLand(kind, i, field) {
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const flag0 = _dr.flag0;
      this.$nextTick(() => {
        if (kind === 'flnew') {
          document.querySelector('.fl-editor')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'nearest' });
          this._bzFx(document.querySelector('.fl-submit'), 'bz-bump', 400);
          return;
        }
        const sel = { start: '[data-dr="start"]', end: '[data-dr="end"]', new: '[data-dr="end"]', bar: '[data-dr="bar"]' }[kind]
          || `[data-i="${i}"][data-dr="${kind === 'dash' ? 'nbody' : kind}"]`;
        this._bzFx(field.querySelector(sel), 'dr-pop', 520);
        if (!flag0) this._bzFx(field.querySelector('.dr-flag'), 'dr-wave', 900);
      });
    },

    // ---------- the keyboard ---------------------------------------------------------------
    // Left and Right step 15 minutes, Shift 60; Home and End go to the limits; Delete takes a break away.
    drKey(ev) {
      if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
      const el = ev.target.closest('[data-dr], [data-block]');
      if (!el) return;
      if (el.dataset.block !== undefined) {
        if (ev.key !== 'Enter' && ev.key !== ' ') return;
        ev.preventDefault();
        const blk = this.flDayBlocks().find(x => String(x.id) === el.dataset.block);
        if (blk) this.flEdit(blk);
        return;
      }
      const kind = el.dataset.dr, i = Number(el.dataset.i);
      const dir = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[ev.key] || 0;
      const end = ev.key === 'End' ? 1 : ev.key === 'Home' ? -1 : 0;
      const del = ev.key === 'Delete' || ev.key === 'Backspace';
      const d = drDay(this.form);
      if ((!dir && !end && !del) || !d.ok) return;
      ev.preventDefault();
      const b = d.ranged.find(x => x.i === i), room = b ? drRoom(d, b) : null;
      if (del) {
        if (!b) return;
        this._drRemove(i, el.closest('.dr-field'));
        this.$nextTick(() => document.querySelector('.dr-bar')?.focus());
        return;
      }
      const lim = drLimits(d, this._drLo(d)), step = (ev.shiftKey ? 60 : 15) * dir, before = this.logPreview()?.net_hours ?? null;
      const pick = (low, high, stepped) => (end ? (end < 0 ? low : high) : stepped);
      let changed = false;
      if (kind === 'start') changed = this._drEdge('start', pick(lim.start[0], lim.start[1], d.s + step));
      else if (kind === 'end') changed = this._drEdge('end', pick(lim.end[0], lim.end[1], d.e + step));
      else if (kind === 'bar') changed = this._drDay(pick(lim.day[0], lim.day[1], step), d);
      else if (b && kind === 'nbody') changed = this._drBreakMove(i, pick(room[0] - b.s, room[1] - b.e, step), d);
      else if (b && kind === 'nstart') changed = this._drBreakEdge(i, 'nstart', pick(room[0], b.e - DR_STEP, b.s + step), d);
      else if (b && kind === 'nend') changed = this._drBreakEdge(i, 'nend', pick(b.s + DR_STEP, room[1], b.e + step), d);
      if (changed) this._drBuzz(before);
    },

    // ---------- writes: the form's own fields, and nothing else -----------------------------
    _drPut(obj, key, m) {
      const t = drHHMM(m);
      if (obj[key] === t) return false;
      obj[key] = t;
      return true;
    },
    _drEdge(which, v) {
      const d = drDay(this.form);
      if (!d.ok) return false;
      const [a, z] = drLimits(d, this._drLo(d))[which];
      return this._drPut(this.form, which + '_time', drClamp(v, a, z));
    },
    // The whole day by `delta` minutes from `base`, its ranged breaks with it.
    _drDay(delta, base) {
      const k = drClamp(delta, this._drLo(base) - base.s, DR_END_MAX - base.e), f = this.form;
      let ch = this._drPut(f, 'start_time', base.s + k);
      ch = this._drPut(f, 'end_time', base.e + k) || ch;
      for (const b of base.ranged) {
        const row = f.breaks[b.i];
        if (!row) continue;
        ch = this._drPut(row, 'start_time', b.s + k) || ch;
        ch = this._drPut(row, 'end_time', b.e + k) || ch;
      }
      return ch;
    },
    _drBreakMove(i, delta, base) {
      const b = base.ranged.find(x => x.i === i), row = this.form.breaks[i];
      if (!b || !row) return false;
      const [a, z] = drRoom(base, b), k = drClamp(delta, a - b.s, z - b.e);
      const ch = this._drPut(row, 'start_time', b.s + k);
      return this._drPut(row, 'end_time', b.e + k) || ch;
    },
    _drBreakEdge(i, which, v, base) {
      const b = base.ranged.find(x => x.i === i), row = this.form.breaks[i];
      if (!b || !row) return false;
      const [a, z] = drRoom(base, b);
      const s = which === 'nstart' ? drClamp(v, a, b.e - DR_STEP) : b.s;
      const e = which === 'nend' ? drClamp(v, b.s + DR_STEP, z) : b.e;
      const ch = this._drPut(row, 'start_time', s);
      const ch2 = this._drPut(row, 'end_time', e);
      row.break_minutes = this.rangeMinutes(row.start_time, row.end_time);
      return ch || ch2;
    },
    // A break that was only minutes is dragged to a place in the day and keeps its minutes.
    _drDash(i, delta) {
      const seg = _dr.dashes.find(k => k.i === i), row = this.form.breaks[i];
      if (!seg || !row) return false;
      const [a, z] = drRoom(_dr.base, { i, s: seg.s, e: seg.e });
      if (z - a < seg.min) return false;
      const s = drClamp(drSnap(seg.s + delta), a, z - seg.min);
      const ch = this._drPut(row, 'start_time', s);
      return this._drPut(row, 'end_time', s + seg.min) || ch;
    },
    // A day with no bar yet: the drag draws it.
    _drNew(a, b) {
      const s = drClamp(Math.min(a, b), _dr.lo, DR_END_MAX - DR_STEP), e = drClamp(Math.max(a, b), s + DR_STEP, DR_END_MAX);
      const ch = this._drPut(this.form, 'start_time', s);
      return this._drPut(this.form, 'end_time', e) || ch;
    },
    // A drag across the empty freelance lane fills the block editor; it never saves.
    _drFl(a, b) {
      const s = drClamp(Math.min(a, b), _dr.lo, DR_END_MAX - DR_STEP), e = drClamp(Math.max(a, b), s + DR_STEP, DR_END_MAX);
      this.flForm.id = null;
      this.flForm.by = 'times';
      const ch = this._drPut(this.flForm, 'start_time', s);
      return this._drPut(this.flForm, 'end_time', e) || ch;
    },
    _drAddBreak(pm, field) {
      const d = drDay(this.form), s = d.ok ? drPlaceBreak(d, pm, 30) : null;
      if (s === null) return;
      this.form.breaks.push({ break_minutes: 30, start_time: drHHMM(s), end_time: drHHMM(s + 30) });
      const i = this.form.breaks.length - 1;
      try { navigator.vibrate?.(8); } catch { /* not allowed here */ }
      this.$nextTick(() => this._bzFx(field.querySelector(`[data-dr="nbody"][data-i="${i}"]`), 'dr-open', 460));
    },
    // The break goes, with a small puff where it was.
    _drRemove(i, field) {
      const el = field && field.querySelector(`[data-i="${i}"]:is([data-dr="nbody"], [data-dr="dash"])`);
      if (el && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const puff = document.createElement('i');
        puff.className = 'dr-puff';
        puff.style.cssText = el.style.cssText;
        el.parentElement.appendChild(puff);
        setTimeout(() => puff.remove(), 460);
      }
      this.form.breaks.splice(i, 1);
      try { navigator.vibrate?.(8); } catch { /* not allowed here */ }
    },
    // A tick at every snap, a longer one where the day's net crosses its target.
    _drBuzz(before) {
      const p = this.logPreview();
      const crossed = !!p && before !== null && (before >= p.target_hours) !== (p.net_hours >= p.target_hours);
      try { navigator.vibrate?.(crossed ? 20 : 8); } catch { /* not allowed here */ }
    },

    editEntry(e) {
      this.editingDate = e.date;
      this.notesOpen = false;
      const d = new Date(e.date + 'T00:00:00');
      this.calYear = d.getFullYear();
      this.calMonth = d.getMonth();
      this.form = {
        date: e.date,
        day_type: e.day_type,
        start_time: e.start_time || '09:00',
        end_time: e.end_time || '17:00',
        notes: e.notes || '',
        breaks: (e.breaks || []).map(b => ({ break_minutes: b.break_minutes, start_time: b.start_time || '', end_time: b.end_time || '' })),
        leave_hours: e.day_type === 'work' ? null : e.leave_hours,
      };
      this.tab = 'log';
      if (location.hash.replace('#', '') !== 'log') location.hash = 'log';  // as go() does
      this.error = null;
    },

    // Notes are optional: a button opens one textarea in place; a day that has notes is
    // always open. Opening focuses the field; leaving it (or Escape) while empty folds it away.
    notesShown() { return this.notesOpen || !!(this.form.notes && this.form.notes.length); },
    openNotes() {
      this.notesOpen = true;
      this.$nextTick(() => {
        const ta = this.$refs.notes;
        if (!ta) return;
        ta.focus();
        this.autosizeNotes(ta);
      });
    },
    closeNotesIfEmpty(ev) {
      if (this.form.notes && this.form.notes.length) return;
      // Leaving for a button below the field (Create entry on a narrow screen): fold up only
      // after the press is over, or the button moves out from under the pointer mid-click.
      if (ev && ev.relatedTarget && ev.relatedTarget.closest?.('button, summary')) {
        window.addEventListener('pointerup', () => this.closeNotesIfEmpty(), { once: true });
        return;
      }
      this.notesOpen = false;
    },
    // `field-sizing: content` grows the field by itself; this is the fallback for browsers
    // that lack it.
    autosizeNotes(ta) {
      if (CSS.supports('field-sizing', 'content')) return;
      ta.style.height = 'auto';
      ta.style.height = ta.scrollHeight + 'px';
    },

    // The day's result as a bar: net hours over the target, capped at the full width.
    impactPct() {
      const p = this.logPreview();
      if (!p) return 0;
      if (!(p.target_hours > 0)) return p.net_hours > 0 ? 100 : 0;
      return Math.round(Math.max(0, Math.min(1, p.net_hours / p.target_hours)) * 1000) / 10;
    },
    // Quick pulse on a figure whenever its value changes (the first value just appears).
    pulse(el, value) {
      const first = !('_pulseSeen' in el);
      const changed = el._pulseSeen !== value;
      el._pulseSeen = value;
      if (first || !changed) return;
      el.classList.remove('pulse');
      void el.offsetWidth;
      el.classList.add('pulse');
    },

    // =====================================================================
    // brass surprises: the odometer, the stamp, the seal, the coins, the bead
    // =====================================================================
    _reduced() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; },

    // The sign and two decimals of a balance, as the big number on the Dashboard shows it.
    heroHours(h) {
      const v = Number(h) || 0;
      return `${v > 0.01 ? '+' : v < -0.01 ? '\u2212' : '\u00b1'}${Math.abs(v).toFixed(2)}h`;
    },

    // `el` becomes an odometer that shows `text`: every digit is a reel of 0-9 that turns to its
    // value (the rightmost fastest, with a small overshoot), everything else stays still. The real
    // text stays in the element, visually hidden, for screen readers and for innerText; the reels
    // are aria-hidden and draw their digits with CSS, so they add no text. It rolls on its first
    // text and whenever the text changes; a text that has not changed does nothing.
    odoSet(el, text) {
      if (!el) return;
      text = String(text ?? '');
      if (el.dataset.odo === text) return;
      const reduced = this._reduced();
      const shape = text.replace(/\d/g, '#');
      el.dataset.odo = text;
      el.classList.add('odo');
      if (el.dataset.odoShape !== shape) {
        el.dataset.odoShape = shape;
        el.textContent = '';
        const sr = document.createElement('span');
        sr.className = 'odo-sr';
        el.appendChild(sr);
        let right = (text.match(/\d/g) || []).length;
        for (const ch of text) {
          const part = document.createElement('span');
          part.setAttribute('aria-hidden', 'true');
          if (/\d/.test(ch)) {
            right--;
            part.className = 'odo-reel';
            part.style.setProperty('--odo-t', `${430 + 120 * Math.min(right, 6)}ms`);
            part.style.setProperty('--d', reduced ? ch : '0');
            part.appendChild(document.createElement('i'));
          } else {
            part.className = 'odo-ch';  // drawn from data-ch by CSS, so it adds no text either
          }
          el.appendChild(part);
        }
        void el.offsetWidth;  // the reels stand on 0 before they turn
      }
      const parts = el.children;
      el.firstElementChild.textContent = text;
      let i = 1;
      for (const ch of text) {
        const part = parts[i++];
        if (part.classList.contains('odo-reel')) part.style.setProperty('--d', ch);
        else if (part.dataset.ch !== ch) part.dataset.ch = ch;
      }
      this.pulse(el, text);
    },

    // A day saved in Log takes a brass stamp on its calendar cell (once, on that cell only).
    stampDay(iso) {
      if (this._reduced()) return;
      this.$nextTick(() => {
        const cell = document.querySelector(`.log-cal-day[aria-label="${iso}"]`);
        if (!cell) return;
        this._bzFx(cell, 'cal-stamp', 900);
        try {
          if (window.matchMedia('(pointer: coarse)').matches && navigator.userActivation?.hasBeenActive) navigator.vibrate?.(12);
        } catch { /* a browser without vibration */ }
      });
    },

    // The week this save has just completed, or null: every work day of the week has an entry, the
    // saved day was not one yet, the week is the current or the previous one and it has not been
    // sealed before in this browser. Returns the week id and the week's delta.
    _sealFor(saved, wasNew) {
      if (!saved || !wasNew) return null;
      const work = this.settingsForm.work_week_days || [];
      if (!work.length) return null;
      const day = new Date(saved.date + 'T12:00:00');
      if (!work.includes((day.getDay() + 6) % 7)) return null;
      const monday = this._mondayIso(day), thisMonday = this._mondayIso(new Date());
      if (monday !== thisMonday && monday !== this._addDaysIso(thisMonday, -7)) return null;
      const sunday = this._addDaysIso(monday, 6);
      const week = this.entries.filter(x => x.date >= monday && x.date <= sunday && x.date !== saved.date).concat([saved]);
      const have = new Set(week.map(x => x.date));
      if (!work.every(i => have.has(this._addDaysIso(monday, i)))) return null;
      let done = [];
      try { done = JSON.parse(localStorage.getItem('k-week-sealed') || '[]'); } catch { done = []; }
      if (!Array.isArray(done)) done = [];
      if (done.includes(monday)) return null;
      try { localStorage.setItem('k-week-sealed', JSON.stringify([...done, monday].slice(-80))); } catch { /* storage blocked */ }
      return { id: this.weekId(monday), delta: this._r2(week.reduce((t, x) => t + (x.surplus_hours || 0), 0)) };
    },

    // A payout saved in Days > Freelance: coins arc from its field to the Selected card, one per 100 of
    // the payout (rounded, at least 1, at most 40). The last one lands by 1.6s whatever their number, the arcs
    // vary a little so a big payout reads as a shower, and the card's amount bumps once when the last one
    // lands (with a brass glint when the payout is above the estimate). They are fixed elements clamped to the
    // viewport, gone when they land.
    payCoins(input, amount, above) {
      if (this._reduced() || !input) return;
      const target = document.querySelector('[data-testid="days-fl-total"] b');
      if (!target) return;
      const vw = document.documentElement.clientWidth, vh = window.innerHeight;
      const clamp = (v, hi) => Math.max(10, Math.min(hi - 10, v));
      const a = input.getBoundingClientRect(), b = target.getBoundingClientRect();
      const x0 = clamp(a.left + a.width / 2, vw), y0 = clamp(a.top + a.height / 2, vh);
      const x1 = clamp(b.left + b.width / 2, vw), y1 = clamp(b.top + b.height / 2, vh);
      const n = Math.max(1, Math.min(40, Math.round((Number(amount) || 0) / 100)));
      const dur = 700, gap = n > 1 ? Math.min(120, 900 / (n - 1)) : 0;  // the last one leaves by 0.9s, lands by 1.6s
      const spread = (a, b) => (n > 1 ? a + Math.random() * (b - a) : 0);
      let end = 0;
      for (let i = 0; i < n; i++) {
        const coin = document.createElement('span');
        const t = n > 1 ? Math.round(560 + Math.random() * (dur - 560)) : dur;
        const sx = clamp(x0 + spread(-14, 14), vw), ex = clamp(x1 + spread(-10, 10), vw);
        const up = -Math.min(n > 1 ? 34 + Math.random() * 70 : 40, Math.max(0, Math.min(y0, y1) - 14));
        coin.className = 'coin-fly';
        coin.setAttribute('aria-hidden', 'true');
        coin.style.cssText = `left:${sx}px;top:${y0}px;--dx:${ex - sx}px;--dy:${y1 - y0}px;--up:${up}px;--t:${t}ms;animation-delay:${Math.round(i * gap)}ms`;
        coin.appendChild(document.createElement('i'));
        document.body.appendChild(coin);
        const gone = () => coin.remove();
        coin.addEventListener('animationend', (ev) => { if (ev.target === coin) gone(); });
        setTimeout(gone, i * gap + t + 400);
        end = Math.max(end, i * gap + t);
      }
      setTimeout(() => {
        const card = document.querySelector('[data-testid="days-fl-total"] b');
        this._bzFx(card, 'coin-bump', 820);
        if (above) this._bzFx(card, 'coin-glint', 820);
      }, end);
    },

    // Where the bead sits on the hairline under the header: 06:00 at the left edge, 24:00 at the right.
    dayBeadFrac() {
      const [h, m] = (this.nowDisplay || '00:00').split(':').map(Number);
      const mins = (h || 0) * 60 + (m || 0);
      return Math.max(0, Math.min(1, (mins - 360) / 1080));
    },

    // Everything the hairline draws: the bead and its title and, when today has a start, the lit stretch from the
    // start to the bead and the tick where today reaches its target. The target time is the ribbon's flag
    // (drFlag) on today's entry, the day left open when it has no end yet. Minutes-only breaks have no place in
    // the day, so they count as taken before the target. It follows nowDisplay and today's entry: no timers.
    dayBead() {
      // a part that is not drawn carries display:none in its style (x-show would lose to the :style binding)
      const off = 'display:none';
      const out = { frac: this.dayBeadFrac(), title: `Now ${this.nowDisplay || ''}`.trim(), litStyle: off, overStyle: off, goalStyle: off };
      const e = this.todayEntry();
      const start = e ? drMin(e.start_time) : null;
      if (start === null) return out;
      const at = m => Math.max(0, Math.min(1, (m - 360) / 1080));
      const d = drDay({ start_time: e.start_time, end_time: e.end_time || '23:59', breaks: e.breaks });
      const loose = d.dashes.reduce((t, k) => t + k.min, 0);
      const reached = drFlag(d, [], (Number(e.target_hours) || 0) + loose / 60);
      const a = at(start), b = out.frac, g = reached === null ? null : at(reached);
      out.title += ` \u00b7 in since ${drHHMM(start)}` + (reached === null ? '' : ` \u00b7 target at ${drHHMM(reached)}`);
      if (g !== null) out.goalStyle = `--g:${g.toFixed(4)}`;
      const cut = g !== null && g > a && g < b ? g : b;
      if (cut > a + 1e-6) out.litStyle = `--a:${a.toFixed(4)};--b:${cut.toFixed(4)}`;
      if (g !== null && b > g + 1e-6) out.overStyle = `--a:${Math.max(a, g).toFixed(4)};--b:${b.toFixed(4)}`;
      return out;
    },

    // W3 — break rows slide in/out; new input focused at frame 0 (before animation)
    addBreak() {
      this.form.breaks.push({ break_minutes: 30, start_time: '', end_time: '' });
      this.$nextTick(() => {
        const rows = document.querySelectorAll('.break-row');
        const row = rows[rows.length - 1];
        if (!row) return;
        row.querySelector('input[type=number]')?.focus();
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          row.classList.add('entering');
          requestAnimationFrame(() => requestAnimationFrame(() => row.classList.remove('entering')));
        }
      });
    },
    removeBreak(i) {
      const rows = document.querySelectorAll('.break-row');
      const row = rows[i];
      if (!row || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.form.breaks.splice(i, 1); return;
      }
      row.classList.add('leaving');
      let done = false;
      const finish = () => { if (done) return; done = true; row.removeEventListener('transitionend', finish); this.form.breaks.splice(i, 1); };
      row.addEventListener('transitionend', finish);
      setTimeout(finish, 280); // safety net if transitionend misfires
    },

    // E2: compute a local entry object from the current form — used for
    // optimistic insertion before the server round-trip completes.
    _buildOptimisticEntry() {
      const f = this.form;
      const hasTimes = this.formHasTimes();
      const netHours = hasTimes ? (this._formNetHours() ?? 0) : 0;
      const nums = this._formNumbers(netHours);
      const frac = this.formFraction();
      return {
        date: f.date,
        day_type: f.day_type,
        fraction: frac,
        leave_hours: f.day_type === 'work' ? 0 : Math.round(frac * this.formTarget() * 100) / 100,
        start_time: hasTimes ? (f.start_time || null) : null,
        end_time: hasTimes ? (f.end_time || null) : null,
        notes: f.notes || null,
        breaks: hasTimes ? f.breaks.filter(b => Number(b.break_minutes) > 0).map(b => ({ break_minutes: Number(b.break_minutes), start_time: b.start_time || null, end_time: b.end_time || null })) : [],
        total_break_minutes: hasTimes ? f.breaks.reduce((s, b) => s + (Number(b.break_minutes) || 0), 0) : 0,
        net_hours: nums.net_hours,
        target_hours: nums.target_hours,
        surplus_hours: nums.surplus_hours,
        _saving: true, // marker stripped once server confirms
      };
    },

    async saveEntry() {
      if (this.saving) return; // a second submit while one is in flight is ignored
      this.saving = true;
      this.error = null;
      const body = { day_type: this.form.day_type, fraction: this.formFraction(), notes: this.form.notes || null };
      if (this.formHasTimes()) {
        // Work day, or the hours worked in the rest of a partial leave day (optional there).
        body.start_time = this.form.start_time || null;
        body.end_time = this.form.end_time || null;
        // Drop any break rows left empty rather than failing the >= 1 validation.
        body.breaks = this.form.breaks
          .filter(b => Number(b.break_minutes) > 0)
          .map(b => ({ break_minutes: Number(b.break_minutes), start_time: b.start_time || null, end_time: b.end_time || null }));
      } else {
        body.breaks = [];
      }

      // ── Optimistic update ──────────────────────────────────────────────
      const optimistic = this._buildOptimisticEntry();
      const prevEntries = [...this.entries];
      let editIdx = -1;

      if (this.editingDate) {
        editIdx = this.entries.findIndex(e => e.date === this.editingDate);
        if (editIdx !== -1) this.entries[editIdx] = optimistic;
      } else {
        body.date = this.form.date;
        this.entries = [optimistic, ...this.entries];
      }

      // The user stays in the Log tab: the toast is the confirmation, and the calendar cell
      // of the day colours as soon as the optimistic entry is in.
      this.error = null;

      try {
        let saved;
        if (this.editingDate) {
          saved = await this.api('PUT', `/api/entries/${this.editingDate}`, body);
        } else {
          saved = await this.api('POST', '/api/entries', body);
        }

        // Swap optimistic row with server-confirmed data
        const realIdx = this.entries.findIndex(e => e._saving && e.date === (saved?.date || optimistic.date));
        if (realIdx !== -1) {
          this.entries[realIdx] = saved;
        } else {
          // User navigated away and loadDays() already ran — refresh to stay consistent
          this.loadDays();
        }

        // Reload dashboard in background — no await, UI stays responsive
        this.loadDashboard();

        // Logging a day you had drafted consumes the draft.
        if (saved && this.plans.some(p => p.date === saved.date)) {
          this.api('DELETE', `/api/plans/${saved.date}`).then(() => {
            this.plans = this.plans.filter(p => p.date !== saved.date);
          }).catch(() => {});
        }

        // W5 ribbon
        if (saved) {
          const seal = this._sealFor(saved, !prevEntries.some(x => x.date === saved.date));
          if (seal) {
            this.showToast(`${seal.id} sealed ${this.formatSurplus(seal.delta)}`, this.surplusClass(seal.delta), null, seal.id);
          } else {
            const dow = new Date(saved.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long' });
            this.showToast(`Saved — ${dow} is ${this.formatSurplus(saved.surplus_hours)}`, this.surplusClass(saved.surplus_hours));
          }
        }

        this.openNewEntry({ keepMonth: true });
        if (saved) this.stampDay(saved.date);
      } catch (e) {
        // Revert the optimistic change; the user never left the form
        this.entries = prevEntries;
        this.error = e.message;
      } finally {
        this.saving = false;
      }
    },

    async deleteEntry(dateIso) {
      if (!confirm(`Delete the entry for ${dateIso}?`)) return;
      try {
        await this.api('DELETE', `/api/entries/${dateIso}`);
        this.entries = this.entries.filter(e => e.date !== dateIso); // the cell empties at once
        this.loadDays(); // plans, blocks and payouts follow; fire-and-forget like go('log')
        this.openNewEntry({ keepMonth: true });
        this.showToast(`Deleted ${dateIso}`, 'neutral');
        await this.loadDashboard();
      } catch (e) { this.error = e.message; }
    },

    // =====================================================================
    // days list
    // =====================================================================
    async loadDays() {
      this.loading.days = true;
      try {
        const [entries, plans, blocks, payouts] = await Promise.all([
          this.api('GET', '/api/entries'), this.api('GET', '/api/plans'),
          this.api('GET', '/api/freelance/blocks').catch(() => this.blocks),
          this.api('GET', '/api/freelance/payouts').catch(() => this.payouts),
        ]);
        this.entries = entries;
        this.plans = plans;
        this.blocks = blocks;
        this.payouts = payouts;
      }
      catch (e) { this.error = e.message; }
      finally { this.loading.days = false; }
    },

    sortBy(k) {
      if (this.sortKey === k) this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
      else { this.sortKey = k; this.sortDir = 'desc'; }
    },

    yearsWithData() {
      const years = [...new Set(this.entries.map(e => e.date.slice(0, 4)))].sort().reverse();
      return years;
    },
    // Days: "All" or one year; the stepper shows the year it would go back to.
    get daysLastYear() {
      if (this.daysYear !== 'all') return Number(this.daysYear);
      return this._daysYearMemo || Number(this.yearsWithData()[0]) || new Date().getFullYear();
    },
    daysToggleAll() {
      if (this.daysYear === 'all') { this.daysYear = String(this.daysLastYear); return; }
      this._daysYearMemo = Number(this.daysYear);
      this.daysYear = 'all';
    },
    daysStepYear(d) {
      const y = this.daysYear === 'all' ? this.daysLastYear : Number(this.daysYear) + d;
      this._daysYearMemo = y;
      this.daysYear = String(y);
    },

    sortedEntries() {
      // Apply year filter for display (entries array is always the full unfiltered list).
      let source = this.daysYear === 'all'
        ? this.entries
        : this.entries.filter(e => e.date.startsWith(this.daysYear));

      // Apply notes search filter.
      const q = this.notesQuery.trim().toLowerCase();
      if (q) source = source.filter(e => e.notes?.toLowerCase().includes(q));

      // Compute running cumulative in chronological order within the filtered set.
      const byDate = [...source].sort((a, b) => a.date < b.date ? -1 : 1);
      let running = 0;
      const cumMap = {};
      for (const e of byDate) {
        running = Math.round((running + e.surplus_hours) * 100) / 100;
        cumMap[e.date] = running;
      }
      // Apply display sort, carrying cumulative as a display-only field.
      const k = this.sortKey;
      const dir = this.sortDir === 'asc' ? 1 : -1;
      // Anchor: most recent logged date ≤ today (auto-scroll target)
      const today = this.todayIso();
      const anchorDate = byDate.filter(e => e.date <= today).slice(-1)[0]?.date ?? null;

      const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      return byDate.sort((a, b) => {
        const av = a[k]; const bv = b[k];
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      }).map(e => ({
        ...e,
        _cumulative: cumMap[e.date],
        _isAnchor: e.date === anchorDate,
        _dow: DOW[new Date(e.date + 'T12:00:00').getDay()],
      }));
    },

    // The table's rows: entries, with a separator (and that month's subtotal) ahead of each
    // month while sorted by date — under a net-hours sort a month boundary means nothing. Each
    // week is one line that is always there; only an open week lists its days.
    daysRows() {
      const entries = this.sortedEntries();
      if (this.sortKey !== 'date') return entries.map(e => ({ kind: 'entry', key: e.date, e }));
      const totals = {}, weeks = {}, mondayOf = {};
      for (const e of entries) {
        const ym = e.date.slice(0, 7);
        const m = (totals[ym] ||= { count: 0, net: 0, target: 0, surplus: 0 });
        m.count++; m.net += e.net_hours; m.target += e.target_hours; m.surplus += e.surplus_hours;
        const monday = (mondayOf[e.date] = this._mondayIso(new Date(e.date + 'T12:00:00')));
        const w = (weeks[monday] ||= { count: 0, net: 0, target: 0, surplus: 0, last: '', cum: 0 });
        w.count++; w.net += e.net_hours; w.target += e.target_hours; w.surplus += e.surplus_hours;
        // the running Σ at the last day of the week inside the filter, whichever way the rows are sorted
        if (e.date > w.last) { w.last = e.date; w.cum = e._cumulative; }
      }
      const rows = [];
      const thisMonday = this._mondayIso(new Date());
      let current = null, currentWeek = null, currentOpen = true;
      for (const e of entries) {
        const ym = e.date.slice(0, 7);
        if (ym !== current) {
          current = ym;
          const m = totals[ym];
          rows.push({
            kind: 'sep', key: 'sep-' + ym,
            label: new Date(ym + '-01T12:00:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' }),
            count: m.count,
            net: Math.round(m.net * 100) / 100,
            target: Math.round(m.target * 100) / 100,
            surplus: Math.round(m.surplus * 100) / 100,
          });
        }
        const monday = mondayOf[e.date];
        if (monday !== currentWeek) {
          currentWeek = monday;
          currentOpen = this.daysWeekIsOpen(monday);
          const w = weeks[monday];
          rows.push({
            kind: 'wk', key: 'wk-' + monday, week: monday,
            id: this.weekId(monday), range: this._weekRange(monday),
            open: currentOpen, current: monday === thisMonday, cumulative: w.cum,
            count: w.count,
            net: Math.round(w.net * 100) / 100,
            target: Math.round(w.target * 100) / 100,
            surplus: Math.round(w.surplus * 100) / 100,
          });
        }
        if (currentOpen) rows.push({ kind: 'entry', key: e.date, e, week: monday });
      }
      return rows;
    },
    // The Mondays of the weeks Days > Employee lists (the filters applied).
    _empWeekKeys() {
      return [...new Set(this.sortedEntries().map(e => this._mondayIso(new Date(e.date + 'T12:00:00'))))];
    },

    // ── Days · ⚡ Freelance: the blocks, filtered by year, note and the sources ticked ──
    setDaysMode(mode) {
      this.daysMode = mode;
      if (mode === 'freelance') this._daysSourcesReady();
    },
    // Every source is in until the user unticks one.
    _daysSourcesReady() {
      if (!this._daysSourcesInit) { this.daysSources = this.sources.map(s => s.id); this._daysSourcesInit = true; }
    },
    daysToggleSource(id) {
      this._daysSourcesReady();
      this.daysSources = this.daysSources.includes(id) ? this.daysSources.filter(x => x !== id) : [...this.daysSources, id];
    },
    daysSourcesAll(on) { this._daysSourcesInit = true; this.daysSources = on ? this.sources.map(s => s.id) : []; },
    // The blocks of the year and the note search, before the source filter.
    daysBlocksAll() {
      let list = this.daysYear === 'all' ? this.blocks : this.blocks.filter(b => b.date.startsWith(this.daysYear));
      const q = this.notesQuery.trim().toLowerCase();
      if (q) list = list.filter(b => (b.notes || '').toLowerCase().includes(q));
      return list;
    },
    daysBlocks() {
      const on = new Set(this.daysSources);
      return this.daysBlocksAll().filter(b => on.has(b.source_id)).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id));
    },
    // The year filter as a date range for flLines ({} = every year).
    _daysRange() {
      return this.daysYear === 'all' ? {} : { from: `${this.daysYear}-01-01`, to: `${this.daysYear}-12-31` };
    },
    // Lines of the sources ticked: the blocks shown and the payouts of the weeks without blocks.
    _daysLines(blocks, extra = {}) {
      return this.flLines(blocks, { sources: new Set(this.daysSources), ...this._daysRange(), ...extra });
    },
    daysSourceRows() {
      const all = this.daysBlocksAll();
      return this.sources.map(s => {
        const mine = all.filter(b => b.source_id === s.id);
        return { id: s.id, name: s.name, archived: s.archived, on: this.daysSources.includes(s.id), blocks: mine.length, hours: this.blockHours(mine), eur: this.blockEur(mine, { sources: new Set([s.id]), ...this._daysRange() }) };
      });
    },
    daysFlTotals() {
      const list = this.daysBlocks();
      const lines = this._daysLines(list);
      const hours = this.blockHours(list), eur = this.lineEur(lines);
      return { blocks: list.length, hours, eur, rate: hours ? Math.round(eur / hours * 100) / 100 : 0, missing: this.lineMissing(lines) };
    },

    // ---------- the weeks of Days > Freelance ------------------------------------
    // ISO week number of a Monday (the week of its Thursday).
    isoWeekNo(mondayIso) {
      const d = new Date(mondayIso + 'T12:00:00');
      d.setDate(d.getDate() + 3);
      const jan4 = new Date(d.getFullYear(), 0, 4, 12);
      jan4.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));
      return 1 + Math.round((d - jan4) / (7 * 86400000));
    },
    _shortDay(iso) { return new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); },
    // "Nov 2 – 8", or "Oct 26 – Nov 1" across a month end
    _weekRange(mondayIso) {
      const sunday = this._addDaysIso(mondayIso, 6);
      const end = mondayIso.slice(5, 7) === sunday.slice(5, 7) ? String(Number(sunday.slice(8))) : this._shortDay(sunday);
      return `${this._shortDay(mondayIso)} – ${end}`;
    },
    _addDaysIso(iso, n) { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return this._dateIso(d); },
    // "W44"
    weekId(mondayIso) { return 'W' + String(this.isoWeekNo(mondayIso)).padStart(2, '0'); },
    payKey(sourceId, weekStart) { return `${sourceId}|${weekStart}`; },
    payoutOf(sourceId, weekStart) { return this.payouts.find(p => p.source_id === sourceId && p.week_start === weekStart) || null; },
    // "$2,100" (cents only when there are some)
    payAmountLabel(p) { return this.fmtMoney(p.amount, p.currency, Number.isInteger(p.amount) ? 0 : 2); },
    // "Open" means the week shows its day rows; the week's numbers are always there. While the
    // notes search has text the weeks answer to their own map and default to open.
    daysWeekIsOpen(key) {
      if (this.notesQuery.trim()) return key in this.daysWeekOpenQ ? this.daysWeekOpenQ[key] : true;
      return key in this.daysWeekOpen ? this.daysWeekOpen[key] : key === this._mondayIso(new Date());
    },
    // The one place that writes open weeks: the search's own map while it has text, the main map otherwise.
    // Only the weeks named change; every other key keeps its state.
    daysWeekSet(keys, open) {
      const q = !!this.notesQuery.trim();
      const next = { ...(q ? this.daysWeekOpenQ : this.daysWeekOpen) };
      for (const k of keys) next[k] = open;
      if (q) this.daysWeekOpenQ = next;
      else this.daysWeekOpen = next;
    },
    daysWeekToggle(key) { this.daysWeekSet([key], !this.daysWeekIsOpen(key)); },
    // The weeks of the mode on screen; the other mode's weeks keep their state.
    daysWeeksSetAll(open) {
      this.daysWeekSet(this.daysMode === 'employee' ? this._empWeekKeys() : this.daysWeeks().map(w => w.key), open);
    },

    // ---------- the bezel: a tick per week over the Days table ---------------------------------------
    // The ticks of the mode on screen, oldest first, from the same filtered weeks the table lists (year,
    // notes, and in Freelance the sources ticked). A year has a slot for every Monday from the week holding
    // Jan 1 to the week holding Dec 31; "All" from the first week with data to the last; a slot with nothing
    // is an empty tick. `height` is 0..1 of the largest absolute value in view. [] when there is nothing to
    // show. The strip runs it once per render, never once per tick.
    daysBezel() {
      const freelance = this.daysMode === 'freelance';
      const data = {};  // Monday -> { value, paid }
      if (freelance) {
        for (const w of this.daysWeeks()) data[w.key] = { value: w.eur, paid: w.tag === 'paid out' };
      } else {
        if (this.sortKey !== 'date') return [];
        for (const e of this.sortedEntries()) {
          const m = this._mondayIso(new Date(e.date + 'T12:00:00'));
          data[m] = { value: (data[m] ? data[m].value : 0) + e.surplus_hours, paid: false };
        }
        for (const m of Object.keys(data)) data[m].value = this._r2(data[m].value);
      }
      const keys = Object.keys(data).sort();
      if (!keys.length) return [];
      const all = this.daysYear === 'all';
      let first = keys[0], last = keys[keys.length - 1];
      if (!all) {
        const a = this._mondayIso(new Date(this.daysYear + '-01-01T12:00:00'));
        const b = this._mondayIso(new Date(this.daysYear + '-12-31T12:00:00'));
        if (a < first) first = a;
        if (b > last) last = b;
      }
      const thisMonday = this._mondayIso(new Date());
      const max = Math.max(...keys.map(k => Math.abs(data[k].value)));
      const ticks = [];
      let prev = '';
      for (let m = first; m <= last; m = this._addDaysIso(m, 7)) {
        const d = data[m];
        const t = {
          monday: m, id: this.weekId(m), range: this._weekRange(m), empty: !d,
          value: d ? d.value : 0, height: d && max ? Math.abs(d.value) / max : 0,
          open: d ? this.daysWeekIsOpen(m) : false, paid: d ? d.paid : false,
          current: m === thisMonday, future: m > thisMonday, text: '', label: '', labEnd: false,
        };
        if (d) t.text = `${t.id} · ${t.range} · ${freelance ? this.fmtMoney(t.value) : this.formatSurplus(t.value)}`;
        // a label sits at the first tick of its month (a year) or year ("All"), by the week's Thursday
        const thu = this._addDaysIso(m, 3);
        if (all) {
          if (thu.slice(0, 4) !== prev) { prev = thu.slice(0, 4); t.label = prev; }
        } else if (thu.startsWith(this.daysYear) && thu.slice(5, 7) !== prev) {
          prev = thu.slice(5, 7);
          t.label = 'JFMAMJJASOND'[Number(prev) - 1];
        }
        ticks.push(t);
      }
      // a long label near the right end hangs to the left, so it never pushes the page sideways
      ticks.slice(-4).forEach(t => { t.labEnd = t.label.length > 1; });
      return ticks;
    },
    // What the strip draws from the ticks: [] to hide it, else one view with the counts.
    daysBezelView(ticks) {
      const data = ticks.filter(t => !t.empty);
      if (!data.length) return [];
      const rove = data.some(t => t.monday === _bz.rove) ? _bz.rove : data[0].monday;
      return [{ mode: this.daysMode, ticks, total: data.length, open: data.filter(t => t.open).length, rove }];
    },
    _bzTickAt(x, y) {
      const el = document.elementFromPoint(x, y);
      return el ? el.closest('.bz-tick') : null;
    },
    // A burst of the same class on an element, restarted each time (a sweep of light, a bump).
    _bzFx(el, cls, ms) {
      if (!el) return;
      el.classList.remove(cls);
      void el.offsetWidth;
      el.classList.add(cls);
      setTimeout(() => el.classList.remove(cls), ms);
    },
    // After + or -: the weeks that change get a delay each, left to right and 380ms at most in all.
    _bzWave(mondays) {
      if (!mondays.length) return;
      const step = Math.min(16, 380 / mondays.length);
      const wave = {};
      [...mondays].sort().forEach((m, i) => { wave[m] = Math.round(i * step); });
      this.daysWave = wave;
      clearTimeout(_bz.waveTimer);
      _bz.waveTimer = setTimeout(() => { this.daysWave = {}; }, 1200);
    },
    _bzTip(tick) {
      const strip = document.querySelector('.bz-strip');
      const tip = strip && strip.querySelector('.bz-tip');
      if (!tip) return;
      if (!tick || tick.classList.contains('empty')) { tip.classList.remove('show'); return; }
      tip.textContent = tick.getAttribute('aria-label');
      tip.classList.add('show');
      const half = tip.offsetWidth / 2 + 1;
      const middle = tick.offsetLeft + tick.offsetWidth / 2;
      tip.style.left = Math.max(half, Math.min(strip.clientWidth - half, middle)) + 'px';
    },
    _bzRove(tick) {
      const strip = tick.closest('.bz-strip');
      strip.querySelectorAll('.bz-tick[tabindex="0"]').forEach(t => t.setAttribute('tabindex', '-1'));
      tick.setAttribute('tabindex', '0');
      _bz.rove = tick.dataset.monday;
    },
    _bzOpenJump(monday) { this.$nextTick(() => this._scrollToWeek(monday, 0)); },
    // Pressing a tick with data toggles it; dragging gives every tick crossed the first one's new state.
    // A finger waits: until it moves sideways or lifts, it may be a swipe that scrolls the page and touches nothing.
    bzDown(ev) {
      if (ev.button > 0) return;
      const tick = ev.target.closest('.bz-tick');
      if (!tick || tick.classList.contains('empty')) return;
      const monday = tick.dataset.monday;
      Object.assign(_bz, { start: monday, crossed: false, last: ev.clientX, paintTo: !this.daysWeekIsOpen(monday), pending: true });
      ev.currentTarget.setPointerCapture(ev.pointerId);
      this._bzRove(tick);
      if (ev.pointerType !== 'touch') this._bzPaintStart();
    },
    _bzPaintStart() {
      if (!_bz.pending) return;
      _bz.pending = false;
      this.daysWeekSet([_bz.start], _bz.paintTo);
    },
    bzMove(ev) {
      this._bzTip(this._bzTickAt(ev.clientX, ev.clientY));
      if (_bz.paintTo === null) return;
      if (_bz.pending && Math.abs(ev.clientX - _bz.last) < 6) return;
      this._bzPaintStart();
      // a quick drag can skip ticks between two events: look at the points in between too. Only the x counts,
      // read along the middle of the strip, so a hand that wanders above or below it keeps painting.
      const x0 = _bz.last, box = ev.currentTarget.getBoundingClientRect(), y = box.top + box.height / 2;
      const n = Math.max(1, Math.ceil(Math.abs(ev.clientX - x0) / 3));
      _bz.last = ev.clientX;
      for (let i = 1; i <= n; i++) {
        const tick = this._bzTickAt(x0 + (ev.clientX - x0) * i / n, y);
        if (!tick) continue;
        const monday = tick.dataset.monday;
        if (monday !== _bz.start) _bz.crossed = true;
        if (tick.classList.contains('empty')) continue;
        if (this.daysWeekIsOpen(monday) !== _bz.paintTo) this.daysWeekSet([monday], _bz.paintTo);
      }
    },
    bzUp() {
      this._bzPaintStart();
      if (_bz.paintTo === true && !_bz.crossed) this._bzOpenJump(_bz.start);
      _bz.paintTo = null;
    },
    bzCancel() { _bz.paintTo = null; _bz.pending = false; },
    bzLeave() {
      if (_bz.paintTo === null && !document.querySelector('.bz-tick:focus-visible')) this._bzTip(null);
    },
    bzFocusIn(ev) {
      const tick = ev.target.closest('.bz-tick');
      if (!tick) return;
      this._bzRove(tick);
      if (tick.matches(':focus-visible')) this._bzTip(tick);  // a click focuses too: its tooltip goes with the pointer
    },
    bzFocusOut() { this._bzTip(null); },
    // One tab stop: the arrows move between the ticks with data, Enter and Space toggle (and jump on opening).
    bzKey(ev) {
      const tick = ev.target.closest('.bz-tick');
      if (!tick || tick.classList.contains('empty')) return;
      const list = [...ev.currentTarget.querySelectorAll('.bz-tick:not(.empty)')];
      const at = list.indexOf(tick);
      const move = { ArrowRight: list[at + 1], ArrowLeft: list[at - 1], Home: list[0], End: list[list.length - 1] };
      if (ev.key in move) {
        ev.preventDefault();
        if (move[ev.key]) move[ev.key].focus();
      } else if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        const monday = tick.dataset.monday, wasOpen = this.daysWeekIsOpen(monday);
        this.daysWeekSet([monday], !wasOpen);
        if (!wasOpen) this._bzOpenJump(monday);
      }
    },
    // The chip's + and -: every week in view, then the wave, one sweep of light and a bump of the count.
    bzAll(open, ev) {
      const btn = ev.currentTarget;
      if (btn.getAttribute('aria-disabled') === 'true') return;
      const bz = btn.closest('.bz');
      const changed = [...bz.querySelectorAll('.bz-tick:not(.empty)')]
        .filter(t => (t.getAttribute('aria-pressed') === 'true') !== open).map(t => t.dataset.monday);
      this.daysWeeksSetAll(open);
      this._bzWave(changed);
      this._bzFx(bz.querySelector('.bz-chip'), 'bz-glint', 600);
      this._bzFx(bz.querySelector('.bz-count'), 'bz-bump', 320);
    },
    // One entry per ISO week (newest first) that has a block shown or a payout of a ticked
    // source with no blocks; `lines` has one entry per source with blocks or a payout that week.
    daysWeeks() {
      const on = new Set(this.daysSources);
      const range = this._daysRange();
      const byWeek = {};
      const slot = key => (byWeek[key] ||= { key, blocks: [], payouts: [] });
      for (const b of this.daysBlocks()) slot(this._mondayIso(new Date(b.date + 'T12:00:00'))).blocks.push(b);
      for (const p of this.payouts) {
        if (!on.has(p.source_id)) continue;
        if (p.blocks === 0 && (!range.from || (p.week_end >= range.from && p.week_end <= range.to))) slot(p.week_start);
      }
      for (const p of this.payouts) if (on.has(p.source_id) && byWeek[p.week_start]) byWeek[p.week_start].payouts.push(p);
      const thisMonday = this._mondayIso(new Date()), today = this._dateIso(new Date());
      return Object.values(byWeek).sort((a, b) => (a.key < b.key ? 1 : -1)).map(w => {
        const sunday = this._addDaysIso(w.key, 6);
        const lines = [];
        for (const s of this.sources) {
          const mine = w.blocks.filter(b => b.source_id === s.id);
          const p = w.payouts.find(x => x.source_id === s.id) || null;
          if (!mine.length && !p) continue;
          const minutes = p ? p.minutes : mine.reduce((t, b) => t + b.minutes, 0);
          const estimate = p ? p.estimate_amount : this._r2(mine.reduce((t, b) => t + b.amount, 0));
          // A payout in another currency than the one billed has its gap in euros: received minus billed.
          const swapped = !!p && p.billed_currency !== undefined && p.currency !== p.billed_currency;
          const gapUnknown = swapped && (p.amount_eur === null || p.billed_eur === null);
          let gap = null;
          if (p && p.minutes > 0) gap = gapUnknown ? 0 : swapped ? this._r2(p.amount_eur - p.billed_eur) : this._r2(p.amount - p.estimate_amount);
          lines.push({ key: s.id, source: s, currency: s.currency, hours: this._r2(minutes / 60), estimate, payout: p,
            gapCur: swapped ? 'EUR' : s.currency, gapUnknown, gapTitle: swapped ? 'Received minus billed, in euros' : null,
            noHours: !!p && p.blocks === 0, gap, eph: p && p.minutes > 0 && p.amount_eur !== null ? this._r2(p.amount_eur / (p.minutes / 60)) : null });
        }
        const paid = lines.filter(l => l.payout).length;
        const money = this.flLines(w.blocks, { sources: on, from: w.key, to: sunday });
        const months = [...new Set(money.map(l => l.date.slice(0, 7)))].sort();
        const mname = d => d.toLocaleDateString('en-US', { month: 'short' });
        return {
          key: w.key, id: this.weekId(w.key), range: `${this._shortDay(w.key)} – ${this._shortDay(sunday)}`,
          current: w.key === thisMonday, blocks: w.blocks, lines,
          hours: this.blockHours(w.blocks), eur: this.lineEur(money), missing: this.lineMissing(money),
          tag: paid === lines.length ? 'paid out' : paid ? 'part paid out' : 'estimated',
          awaiting: sunday < today && lines.some(l => !l.payout),
          splits: months.length > 1 ? `splits ${mname(new Date(months[0] + '-01T12:00:00'))}/${mname(new Date(months[months.length - 1] + '-01T12:00:00'))}` : '',
          open: this.daysWeekIsOpen(w.key),
        };
      });
    },
    // Rows of the table: a month separator ahead of the weeks whose Monday falls in it; each
    // week is one line (with a line per source under it when it has several sources) and, only
    // when the week is open, a header for the block columns and then its block rows.
    daysFlRows() {
      const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      const rows = [];
      const weeks = this.daysWeeks();
      let current = null;
      for (const w of weeks) {
        const ym = w.key.slice(0, 7);
        if (ym !== current) {
          current = ym;
          // The money of a month is what is dated in it (as on the Freelance tab); a week stays
          // listed under its Monday's month, and the part that spills over is named.
          const first = ym + '-01', last = ym + '-31';
          const inMonth = weeks.flatMap(x => x.blocks).filter(b => b.date.slice(0, 7) === ym);
          const lines = this._daysLines(inMonth, { from: first, to: last });
          const from = [];
          for (const x of weeks) {
            if (x.key.slice(0, 7) === ym) continue;
            const sunday = this._addDaysIso(x.key, 6);
            const part = this._daysLines(x.blocks.filter(b => b.date.slice(0, 7) === ym), { from: first > x.key ? first : x.key, to: last < sunday ? last : sunday });
            if (part.length) from.push({ id: x.id, eur: this.lineEur(part) });
          }
          rows.push({ kind: 'sep', key: 'sep-' + ym, label: new Date(ym + '-01T12:00:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' }), count: inMonth.length,
            hours: this.blockHours(inMonth), eur: this.lineEur(lines), from });
        }
        rows.push({ ...w, kind: 'week', key: 'w-' + w.key, week: w.key });
        if (w.open && w.blocks.length) rows.push({ kind: 'bhead', key: 'h-' + w.key, week: w.key });
        if (w.open) w.blocks.forEach((b, i) => rows.push({ kind: 'block', key: 'b-' + b.id, week: w.key, b, last: i === w.blocks.length - 1, dow: DOW[new Date(b.date + 'T12:00:00').getDay()] }));
      }
      return rows;
    },
    // ---------- typing a payout (autosave like Settings) ------------------------------
    payText(sourceId, weekStart, p) {
      const k = this.payKey(sourceId, weekStart);
      return k in this.payDraft ? this.payDraft[k] : (p ? String(p.amount) : '');
    },
    payTyped(sourceId, weekStart, text) {
      const k = this.payKey(sourceId, weekStart);
      this.payDraft = { ...this.payDraft, [k]: text };
      clearTimeout(this._autosave['pay-' + k]);
      this._autosave['pay-' + k] = setTimeout(() => this._queued('payout', () => this._paySave(sourceId, weekStart)), 600);
    },
    async reloadFlData() {
      try {
        const [blocks, payouts] = await Promise.all([this.api('GET', '/api/freelance/blocks'), this.api('GET', '/api/freelance/payouts')]);
        this.blocks = blocks;
        this.payouts = payouts;
      } catch (e) { this.error = e.message; }
      this._flStale = true;  // a block's effective money depends on its week's payout
    },
    async _paySave(sourceId, weekStart) {
      const k = this.payKey(sourceId, weekStart), st = 'wk-' + weekStart;
      if (!(k in this.payDraft)) return;
      const text = String(this.payDraft[k]).trim();
      const existing = this.payoutOf(sourceId, weekStart);
      const src = this.sourceById(sourceId);
      const drop = () => { const d = { ...this.payDraft }; delete d[k]; this.payDraft = d; const a = { ...this.payAcct }; delete a[k]; this.payAcct = a; };
      const acct = this.payAccountId(sourceId, weekStart, existing);
      const acctChanged = !!existing && (existing.account_id ?? null) !== acct;
      if (text === '') {
        if (!existing) { drop(); this._setStatus(st, ''); return; }
        this._setStatus(st, 'busy');
        try {
          await this.api('DELETE', `/api/freelance/payouts/${existing.id}`);
          drop();
          await this.reloadFlData();
          this._setStatus(st, 'saved');
          this.showToast(`Payout deleted — ${this.weekId(weekStart)} ${src ? src.name : ''}`.trim(), 'neutral', {
            label: 'Undo',
            run: async () => {
              const body = { source_id: existing.source_id, week_start: existing.week_start, amount: existing.amount, note: existing.note };
              if (existing.account_id != null) {
                // the account's currency and the value it had: typed by hand, or the rate of the day it was paid
                body.account_id = existing.account_id;
                if (existing.rate_source === 'manual' && existing.amount_eur !== null) body.eur_amount = existing.amount_eur;
                else if (existing.rate_date) body.paid_on = existing.rate_date;
              } else if (existing.fx_rate) body.fx_rate = existing.fx_rate;
              try { await this.api('POST', '/api/freelance/payouts', body); await this.reloadFlData(); this.showToast('Payout restored', 'neutral'); }
              catch (e) { this.error = e.message; }
            },
          });
        } catch (e) { this.error = e.message; this._setStatus(st, 'error'); }
        return;
      }
      const amount = Number(text.replace(/[,\s]/g, ''));
      if (!(amount > 0)) { this._setStatus(st, 'invalid'); return; }
      if (existing && existing.amount === amount && !acctChanged) { drop(); this._setStatus(st, ''); return; }
      this._setStatus(st, 'busy');
      try {
        const body = { source_id: sourceId, week_start: weekStart, amount };
        if (acct !== null) body.account_id = acct;
        if (existing) await this.api('PUT', `/api/freelance/payouts/${existing.id}`, { ...body, account_id: acct, note: existing.note });
        else await this.api('POST', '/api/freelance/payouts', body);
        const field = document.activeElement?.classList.contains('payin') ? document.activeElement : null;
        const input = field || [...document.querySelectorAll('.payin')].find(x => x.getAttribute('aria-label') === `Payout ${src?.name} ${this.weekId(weekStart)}`);
        drop();
        await this.reloadFlData();
        this._setStatus(st, 'saved');
        const mine = this.payoutOf(sourceId, weekStart);
        // one coin per 100 euros that landed; the glint says the payout beat the week's estimate
        if (mine) {
          const swapped = mine.currency !== mine.billed_currency;
          const euros = mine.amount_eur ?? mine.amount;
          this.payCoins(input, euros, swapped ? (mine.amount_eur ?? 0) > (mine.billed_eur ?? Infinity) : mine.amount > mine.estimate_amount);
        }
      } catch (e) { this.error = e.message; this._setStatus(st, 'error'); }
    },
    payStatus(weekStart) { return this.settingsStatusText('wk-' + weekStart); },
    payStatusCls(weekStart) { return this.settingsStatusCls('wk-' + weekStart); },
    // The exchange rate of a USD payout: the pencil opens a small input.
    fxEdit(p) { this.fxEditing = p.id; },
    async fxSave(p, value) {
      if (this.fxEditing !== p.id) return;
      this.fxEditing = null;
      const v = Number(value);
      if (!(v > 0) || v === p.fx_rate) return;
      const st = 'wk-' + p.week_start;
      this._setStatus(st, 'busy');
      try {
        await this.api('PUT', `/api/freelance/payouts/${p.id}`, { source_id: p.source_id, week_start: p.week_start, amount: p.amount, fx_rate: v, note: p.note });
        await this.reloadFlData();
        this._setStatus(st, 'saved');
      } catch (e) { this.error = e.message; this._setStatus(st, 'error'); }
    },
    // ---------- accounts in the payout row --------------------------------------------
    activeAccounts() { return this.accounts.filter(a => !a.archived); },
    accountById(id) { return this.accounts.find(a => a.id === id) || null; },
    // The account a payout goes to: the one picked, else the payout's own (none for a payout from before
    // accounts), else for a week with no payout the source's default account, else the default account.
    payAccountId(sourceId, weekStart, p) {
      const k = this.payKey(sourceId, weekStart);
      if (k in this.payAcct) return this.payAcct[k];
      if (p) return p.account_id ?? null;
      const live = this.activeAccounts();
      const src = this.sourceById(sourceId);
      const mine = src && live.find(a => a.id === src.default_account_id);
      return (mine || live.find(a => a.is_default) || { id: null }).id;
    },
    payCurrency(sourceId, weekStart, p, billed) {
      const id = this.payAccountId(sourceId, weekStart, p);
      const a = id === null ? null : this.accountById(id);
      return a ? a.currency : (p ? p.currency : billed);
    },
    payAccountOptions(sourceId, weekStart, p, billed) {
      const chosen = this.payAccountId(sourceId, weekStart, p);
      const rows = this.accounts.filter(a => !a.archived || a.id === chosen).map(a => ({ id: a.id, label: a.name, selected: a.id === chosen }));
      rows.push({ id: null, label: `As billed (${billed})`, selected: chosen === null });
      return rows;
    },
    async paySetAccount(sourceId, weekStart, value, p) {
      const k = this.payKey(sourceId, weekStart);
      this.payAcct = { ...this.payAcct, [k]: value === '' ? null : Number(value) };
      if (!p) return;  // nothing to save until an amount is typed
      if (!(k in this.payDraft)) this.payDraft = { ...this.payDraft, [k]: String(p.amount) };
      clearTimeout(this._autosave['pay-' + k]);
      await this._queued('payout', () => this._paySave(sourceId, weekStart));
    },
    // "worth €": what a payout in another currency was worth in euros, typed when no rate can be had
    // (or when the user wants their own). It is sent as `eur_amount`.
    async worthSave(p, value) {
      this.worthOpen = null;
      const v = Number(String(value).replace(/[,\s]/g, ''));
      if (!(v > 0) || v === p.amount_eur) return;
      const st = 'wk-' + p.week_start;
      this._setStatus(st, 'busy');
      try {
        await this.api('PUT', `/api/freelance/payouts/${p.id}`, { source_id: p.source_id, week_start: p.week_start, amount: p.amount, note: p.note, account_id: p.account_id, eur_amount: v });
        await this.reloadFlData();
        this._setStatus(st, 'saved');
      } catch (e) { this.error = e.message; this._setStatus(st, 'error'); }
    },
    // The FX chip: what the exchange and the fees cost, in plain words.
    fxHasCost(p) { return p.fx_cost_eur !== null && p.fx_cost_eur !== undefined; },
    _fxRateText(r) { return r >= 0.01 ? r.toFixed(4) : Number(r.toPrecision(4)).toString(); },
    fxStory(p) {
      const bc = p.billed_currency;
      let billed = `Billed ${this.fmtMoney(p.billed_amount, bc)}`;
      if (bc !== 'EUR' && p.billed_eur) {
        const exact = this.fxRates[`${bc}|${p.rate_date}`];
        const rate = this._fxRateText(exact || p.billed_amount / p.billed_eur);
        billed += ` · ${this.isCoin(bc) ? 'CoinGecko' : 'ECB'} rate ${rate} on ${this._shortDay(p.rate_date)} → ${this.fmtMoney(p.billed_eur)}`;
      }
      const parts = [billed];
      parts.push(`You received ${this.fmtMoney(p.amount, p.currency)}` + (p.currency !== 'EUR' && p.amount_eur !== null ? ` (${this.fmtMoney(p.amount_eur)})` : ''));
      const cost = p.fx_cost_eur, share = p.billed_eur ? ` (${(Math.abs(cost) / p.billed_eur * 100).toFixed(1)}%)` : '';
      parts.push(cost < 0 ? `Exchange and fees left you ${this.fmtMoney(-cost)} ahead${share}` : `Exchange and fees cost you ${this.fmtMoney(cost)}${share}`);
      if (p.effective_rate) parts.push(`Your rate was ${this._fxRateText(p.effective_rate)}`);
      return parts.join(' · ');
    },
    // hover and focus show it, a tap (or a click) pins it, Escape or a click elsewhere closes it
    _fxTipStyle(el) {
      const r = el.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight;
      const left = Math.max(8, Math.min(r.left, vw - 8 - Math.min(22 * 16, vw - 16)));
      const place = r.bottom + 150 > vh ? `bottom:${Math.round(vh - r.top + 6)}px` : `top:${Math.round(r.bottom + 6)}px`;
      return `left:${Math.round(left)}px;${place}`;
    },
    // a scroll or a resize moves the chip: the tip follows it, and goes when the chip is gone
    fxTipFollow() {
      if (!this.fxTip.open) return;
      if (!this._fxEl || !this._fxEl.isConnected) { this.fxTipClose(true); return; }
      this.fxTip.style = this._fxTipStyle(this._fxEl);
    },
    async fxTipOpen(p, el, pin = false) {
      this._fxEl = el;
      this.fxTip = { open: true, pinned: pin || (this.fxTip.open && this.fxTip.id === p.id && this.fxTip.pinned), id: p.id, text: this.fxStory(p), style: this._fxTipStyle(el) };
      const bc = p.billed_currency, key = `${bc}|${p.rate_date}`;
      if (bc !== 'EUR' && !this.isCoin(bc) && p.rate_date && !(key in this.fxRates)) {
        try {
          const a = await this.api('GET', `/api/fx?date=${p.rate_date}&currency=${bc}`);
          const v = a.available ? (a.per_eur ?? a.usd_per_eur) : null;
          this.fxRates = { ...this.fxRates, [key]: v || 0 };
          if (this.fxTip.open && this.fxTip.id === p.id) this.fxTip.text = this.fxStory(p);
        } catch { this.fxRates = { ...this.fxRates, [key]: 0 }; }
      }
    },
    fxTipClick(p, el) {
      if (this.fxTip.open && this.fxTip.id === p.id && this.fxTip.pinned) { this.fxTipClose(true); return; }
      this.fxTipOpen(p, el, true);
    },
    fxTipClose(force = false) { if (force || !this.fxTip.pinned) this.fxTip = { ...this.fxTip, open: false, pinned: false }; },
    // "+$300" / "-€50": the payout against the estimate, in the source's currency.
    payGapLabel(gap, currency) {
      return (gap < 0 ? '-' : '+') + this.fmtMoney(Math.abs(gap), currency, Number.isInteger(gap) ? 0 : 2);
    },
    // The payouts of the week of the day open in Log (its ⚡ card shows them read-only).
    flDayPayouts() {
      if (!this.form.date) return [];
      const monday = this._mondayIso(new Date(this.form.date + 'T12:00:00'));
      return this.payouts.filter(p => p.week_start === monday);
    },
    // From the Log card to that week in Days > Freelance, opened and in view.
    async openWeekInDays(p) {
      const year = this.daysYear !== 'all' && this.daysYear !== p.week_start.slice(0, 4) ? p.week_start.slice(0, 4) : this.daysYear;
      await this._openFlWeek(p.week_start, [p.source_id], year);
    },
    // Days > Freelance with the week of `monday` opened and in view, its sources ticked.
    async _openFlWeek(monday, sourceIds, year) {
      this.daysWeekOpen = { ...this.daysWeekOpen, [monday]: true };
      this.daysMode = 'freelance';
      this._daysSourcesReady();
      for (const id of sourceIds) if (!this.daysSources.includes(id)) this.daysSources = [...this.daysSources, id];
      this.daysYear = year;
      await this.go('days');
      this.$nextTick(() => document.getElementById('wk-' + monday)?.scrollIntoView({ block: 'center' }));
    },
    // A block's row opens its day in Log with the block in the editor.
    async openBlockInLog(b) {
      await this.openDayInLog(b.date);
      this.$nextTick(() => { const fresh = this.blocks.find(x => x.id === b.id) || b; this.flEdit(fresh); });
    },

    scrollToToday() {
      const today = this.todayIso();
      const source = this.daysYear === 'all'
        ? this.entries
        : this.entries.filter(e => e.date.startsWith(this.daysYear));
      const anchorDate = source.filter(e => e.date <= today).map(e => e.date).sort().slice(-1)[0] ?? null;
      if (!anchorDate) return;
      const el = document.getElementById('day-row-' + anchorDate);
      if (!el) {
        // the anchor's week is closed: its line stands in for the day
        if (this.daysMode === 'employee' && this.sortKey === 'date') this._scrollToWeek(this._mondayIso(new Date(anchorDate + 'T12:00:00')), 0);
        return;
      }
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('today-flash');
      setTimeout(() => el.classList.remove('today-flash'), 2400);
    },

    // Projected year-end surplus based on current average daily surplus.
    // Counts actual work days (Mon=0…Sun=6) using the configured work week,
    // then subtracts planned vacation days and surplus-banked days so the
    // remaining count (and projection) reflects days you'll actually work.
    forecast() {
      if (!this.dashboard) return null;
      const { surplus_hours, work_days } = this.dashboard.cumulative;
      if (!work_days) return null;
      const dailyTarget = this.dashboard.daily_target_hours || 8;
      const workWeek = new Set(this.dashboard.work_week_days ?? [0,1,2,3,4]);
      const today = new Date(this.dashboard.today + 'T12:00:00');
      const yearEnd = new Date(today.getFullYear(), 11, 31);

      // 1. Raw calendar work days left
      let workDaysLeft = 0;
      const d = new Date(today);
      d.setDate(d.getDate() + 1); // start counting from tomorrow
      while (d <= yearEnd) {
        if (workWeek.has((d.getDay() + 6) % 7)) workDaysLeft++; // Mon=0…Sun=6
        d.setDate(d.getDate() + 1);
      }

      // 2. Vacation days still to take this year (only when a budget is set)
      // Fractional: partial vacation days count their share. When time off has been
      // drafted in the planner, the drafts replace the assumption that the whole
      // remaining budget will be taken (and drafted flex drains the pool).
      const budget = this.dashboard.vacation_budget_days ?? 0;
      const used = this.dashboard.vacation_days_used ?? 0;
      const planned = this.dashboard.planned_days_remaining ?? 0;
      const plannedFlexHours = this.dashboard.planned_flex_hours ?? 0;
      const vacationRemaining = planned > 0 ? 0
        : budget > 0 ? Math.max(0, Math.round((budget - used) * 100) / 100) : 0;

      // 3. Surplus-banked days: each full daily-target of surplus = 1 day you
      //    can take off without falling below zero.
      const bankedDays = Math.max(0, Math.floor(surplus_hours / dailyTarget));

      // 4. Effective days you'll actually work
      const adjustedWorkDays = Math.max(0, Math.round((workDaysLeft - vacationRemaining - planned - bankedDays) * 100) / 100);

      const avgDaily = surplus_hours / work_days;
      const projected = Math.round((surplus_hours - plannedFlexHours + avgDaily * adjustedWorkDays) * 100) / 100;
      return { projected, workDaysLeft, adjustedWorkDays, vacationRemaining, planned, bankedDays };
    },

    // Vacation budget status: used/remaining/pct for the current year.
    vacationStatus() {
      if (!this.dashboard) return null;
      const budget = this.dashboard.vacation_budget_days ?? 0;
      if (!budget) return null;
      const used = this.dashboard.vacation_days_used ?? 0;
      const remaining = Math.max(Math.round((budget - used) * 100) / 100, 0);
      const pct = Math.round((used / budget) * 100);
      return { budget, used, remaining, pct };
    },

    // Yearly breakdown enriched with carry-in surplus from previous years.
    yearlyWithCarryover() {
      if (!this.yearly.length) return [];
      const sorted = [...this.yearly].sort((a, b) => a.year - b.year);
      let cum = 0;
      const rows = sorted.map(r => {
        const carry_in = Math.round(cum * 100) / 100;
        cum = Math.round((cum + r.surplus_hours) * 100) / 100;
        return { ...r, carry_in };
      });
      return rows.reverse(); // newest first for display
    },

    // =====================================================================
    // analytics — the range
    // =====================================================================
    // Entries inside the chart's visible range, ascending.
    anVisible() {
      const { x0, x1 } = this.an;
      return this.entries
        .filter(e => { const t = this._ms(e.date); return t >= x0 && t < x1; })
        .sort((a, b) => (a.date < b.date ? -1 : 1));
    },
    _ms(iso) { return +new Date(iso + 'T00:00:00'); },
    _r2(n) { return Math.round(n * 100) / 100; },

    anSummary() {
      const vis = this.anVisible();
      if (!vis.length) return null;
      let net = 0, target = 0, workDays = 0, offDays = 0, vacation = 0, sick = 0;
      for (const e of vis) {
        net += e.net_hours; target += e.target_hours;
        const off = e.day_type === 'work' ? 0 : e.fraction;
        workDays += 1 - off; offDays += off;
        if (e.day_type === 'vacation') vacation += e.fraction;
        if (e.day_type === 'sick') sick += e.fraction;
      }
      const surplus = this._r2(net - target);
      return {
        net: this._r2(net), target: this._r2(target), surplus,
        perDay: workDays ? this._r2(surplus / workDays) : 0,
        workDays: this._r2(workDays), offDays: this._r2(offDays),
        vacation: this._r2(vacation), sick: this._r2(sick), logged: vis.length,
      };
    },

    // Average Δ per weekday (Mon–Sun) over the work days in range, and when they start and end.
    weekdayPattern() {
      const work = this.anVisible().filter(e => e.day_type === 'work');
      if (!work.length) return null;
      const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const buckets = Array.from({ length: 7 }, () => ({ sum: 0, count: 0, start: 0, end: 0, timed: 0 }));
      const mins = s => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));
      const hhmm = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(Math.round(m % 60)).padStart(2, '0')}`;
      for (const e of work) {
        const dow = (new Date(e.date + 'T12:00:00').getDay() + 6) % 7; // Mon=0
        const b = buckets[dow];
        b.sum += e.surplus_hours; b.count++;
        if (e.start_time && e.end_time) { b.start += mins(e.start_time); b.end += mins(e.end_time); b.timed++; }
      }
      const maxAbs = Math.max(0.25, ...buckets.map(b => b.count ? Math.abs(b.sum / b.count) : 0));
      return labels.map((label, i) => {
        const { sum, count, start, end, timed } = buckets[i];
        const avg = count ? Math.round((sum / count) * 100) / 100 : null;
        // One decimal everywhere; the sign follows the rounded value, so a tiny
        // average reads 0.0h rather than −0.0h.
        const r = avg === null ? null : Math.round(avg * 10) / 10;
        const text = r === null ? '—' : `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toFixed(1)}h`;
        const times = timed ? `${hhmm(start / timed)}\n${hhmm(end / timed)}` : '';
        const barStyle = avg === null ? '' : `height:${Math.round(Math.abs(avg) / maxAbs * 50)}%`;
        return { label, avg, count, text, times, barStyle,
          title: avg === null ? `${label}: no data` : `${label}: avg ${text} (${count} days)${times ? ' · ' + times.replace('\n', '→') : ''}` };
      });
    },

    // Daily surplus of the work days in range, in half-hour buckets from −3h to +3h.
    anHistogram() {
      const work = this.anVisible().filter(e => e.day_type === 'work');
      if (!work.length) return null;
      const counts = Array(12).fill(0);
      let clipped = 0, within = 0;
      for (const e of work) {
        const i = Math.floor((e.surplus_hours + 3) / 0.5);
        if (i < 0 || i > 11) clipped++; else counts[i]++;
        if (Math.abs(e.surplus_hours) <= 0.5) within++;
      }
      const max = Math.max(1, ...counts);
      const buckets = counts.map((n, i) => {
        const lo = -3 + i * 0.5;
        return { lo, pct: Math.round(n / max * 100), title: `${this.formatSurplus(lo)} to ${this.formatSurplus(lo + 0.5)}: ${n} day${n !== 1 ? 's' : ''}` };
      });
      const caption = `${work.length} work day${work.length !== 1 ? 's' : ''} · ${Math.round(within / work.length * 100)}% within ±30 min of the target`
        + (clipped ? ` · ${clipped} beyond ±3h` : '');
      return { buckets, caption };
    },

    // Months in range: { key, net, target, surplus }.
    anMonths(vis) {
      const m = {};
      for (const e of vis) {
        const k = e.date.slice(0, 7);
        const row = (m[k] ||= { key: k, net: 0, target: 0, surplus: 0 });
        row.net += e.net_hours; row.target += e.target_hours; row.surplus += e.surplus_hours;
      }
      return Object.values(m).map(r => ({ ...r, net: this._r2(r.net), target: this._r2(r.target), surplus: this._r2(r.surplus) }));
    },

    // Records for the range. "Worst" rows only when negative: a positive "most deficit month"
    // is not bad (the user's rule, 2026-10-02).
    anRecords() {
      const vis = this.anVisible();
      if (!vis.length) return [];
      const work = vis.filter(e => e.day_type === 'work');
      const best = (arr, key) => arr.reduce((a, x) => (!a || x[key] > a[key] ? x : a), null);
      const worst = (arr, key) => arr.reduce((a, x) => (!a || x[key] < a[key] ? x : a), null);
      const months = this.anMonths(vis);
      const years = {};
      for (const e of vis) { const y = e.date.slice(0, 4); years[y] = this._r2((years[y] || 0) + e.surplus_hours); }
      const yearRows = Object.entries(years).map(([label, surplus]) => ({ label, surplus }));
      // Longest run of days with the running balance above zero, within the range.
      let run = 0, bestRun = 0, cum = 0;
      for (const e of vis) { cum += e.surplus_hours; if (cum > 0.005) { run++; bestRun = Math.max(bestRun, run); } else run = 0; }
      const timed = work.filter(e => e.start_time && e.end_time);
      const rows = [];
      const add = (label, value, when, cls) => rows.push({ label, value, when, cls });
      const longest = best(work, 'net_hours'), shortest = worst(work, 'net_hours');
      if (longest) add('Longest day', longest.net_hours + 'h', longest.date);
      if (shortest) add('Shortest day', shortest.net_hours + 'h', shortest.date);
      const lm = best(months, 'net'), sm = best(months, 'surplus'), dm = worst(months, 'surplus');
      if (lm) add('Longest month', lm.net + 'h', lm.key);
      if (sm) add('Most surplus month', this.formatSurplus(sm.surplus), sm.key, this.surplusClass(sm.surplus));
      if (dm && dm.surplus < 0) add('Most deficit month', this.formatSurplus(dm.surplus), dm.key, 'deficit');
      add('Longest positive streak', `${bestRun} day${bestRun !== 1 ? 's' : ''}`, 'in the black', bestRun ? 'surplus' : '');
      const by = best(yearRows, 'surplus'), wy = worst(yearRows, 'surplus');
      if (by) add('Best year', this.formatSurplus(by.surplus), by.label, this.surplusClass(by.surplus));
      if (wy && wy.surplus < 0) add('Worst year', this.formatSurplus(wy.surplus), wy.label, 'deficit');
      if (timed.length) {
        const early = timed.reduce((a, e) => (e.start_time < a.start_time ? e : a));
        const late = timed.reduce((a, e) => (e.end_time > a.end_time ? e : a));
        add('Earliest start', early.start_time, early.date);
        add('Latest end', late.end_time, late.date);
      }
      return rows;
    },

    // =====================================================================
    // analytics — the chart
    // =====================================================================
    AN_W: 620, AN_H: 300, AN_PADL: 40, AN_PADR: 14, AN_PADT: 14, AN_PADB: 24,
    DAY_MS: 86400000,

    // The whole history: from the cumulative start or the first entry, to tomorrow.
    anFull() {
      const today = this._ms(this.todayIso());
      const first = this.entries.length ? Math.min(...this.entries.map(e => this._ms(e.date))) : today;
      const start = this.anSeries ? Math.min(first, this._ms(this.anSeries.start)) : first;
      return [Math.min(start, today - 30 * this.DAY_MS), today + this.DAY_MS];
    },
    anX(t) { return this.AN_PADL + (this.AN_W - this.AN_PADL - this.AN_PADR) * (t - this.an.x0) / (this.an.x1 - this.an.x0); },
    anT(x) { return this.an.x0 + (x - this.AN_PADL) / (this.AN_W - this.AN_PADL - this.AN_PADR) * (this.an.x1 - this.an.x0); },

    anSetRange(x0, x1, preset = null) {
      const [f0, f1] = this.anFull();
      const min = 7 * this.DAY_MS;
      if (x1 - x0 < min) { const c = (x0 + x1) / 2; x0 = c - min / 2; x1 = c + min / 2; }
      if (x0 < f0) { x1 += f0 - x0; x0 = f0; }
      if (x1 > f1) { x0 -= x1 - f1; x1 = f1; }
      this.an.x0 = Math.max(f0, x0); this.an.x1 = Math.min(f1, x1); this.an.preset = preset;
      this.anRender();
    },
    anPreset(p) {
      const today = new Date(this.todayIso() + 'T00:00:00'), y = today.getFullYear(), m = today.getMonth();
      const end = +today + this.DAY_MS;
      const start = {
        month: +new Date(y, m, 1), '3m': +new Date(y, m - 2, 1), year: +new Date(y, 0, 1),
        '12m': +new Date(y - 1, m + 1, 1), all: this.anFull()[0],
      }[p];
      this.anSetRange(start, end, p);
    },
    anSetMode(mode) { this.an.mode = mode; this.anRender(); },
    anRangeLabel() {
      if (!this.an.x1) return '';
      const f = d => d.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
      const days = Math.round((this.an.x1 - this.an.x0) / this.DAY_MS);
      return `${f(new Date(this.an.x0))} – ${f(new Date(this.an.x1 - 1))} · ${days} days`;
    },
    anBrushWinStyle() {
      const [f0, f1] = this.anFull();
      return `left:${(this.an.x0 - f0) / (f1 - f0) * 100}%;width:${(this.an.x1 - this.an.x0) / (f1 - f0) * 100}%`;
    },

    // Axis labels that fit the span: quarters, months, Mondays, or days.
    anXTicks() {
      const { x0, x1 } = this.an, span = (x1 - x0) / this.DAY_MS, out = [];
      const y0 = new Date(x0).getFullYear(), y1 = new Date(x1).getFullYear();
      const mon = t => new Date(t).toLocaleDateString('en-US', { month: 'short' }).toUpperCase();
      if (span > 400) {
        for (let y = y0; y <= y1; y++) for (let m = 0; m < 12; m += 3) { const t = +new Date(y, m, 1); if (t >= x0 && t <= x1) out.push([t, m === 0 ? String(y) : mon(t)]); }
      } else if (span > 70) {
        for (let y = y0 - 1; y <= y1; y++) for (let m = 0; m < 12; m++) { const t = +new Date(y, m, 1); if (t >= x0 && t <= x1) out.push([t, mon(t) + (m === 0 ? ' ' + y : '')]); }
      } else {
        const day0 = new Date(x0); day0.setHours(0, 0, 0, 0);
        for (let d = day0; +d <= x1; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
          if (span <= 14 || d.getDay() === 1) out.push([+d, d.toLocaleDateString('en-US', { day: 'numeric', month: 'short' })]);
        }
      }
      return out;
    },

    anRender() {
      if (!this.an.x1) return;
      const W = this.AN_W, H = this.AN_H, PADL = this.AN_PADL, PADR = this.AN_PADR, PADT = this.AN_PADT, PADB = this.AN_PADB;
      const f = n => n.toFixed(1), X = t => this.anX(t), DAY = this.DAY_MS;
      const vis = this.anVisible(), target = this.dashboard?.daily_target_hours || this.settingsForm.daily_target_hours || 8;
      const today = this._ms(this.todayIso());
      // freelance hours per day / per month in the window, stacked on the employee's bars
      const flVis = this.hasFreelance() ? this.anFlVisible() : [];
      const flByDay = {};
      for (const b of flVis) flByDay[b.date] = (flByDay[b.date] || 0) + b.minutes / 60;
      const flMonths = this.anFlMonths(flVis), flMonthMap = Object.fromEntries(flMonths.map(m => [m.key, m]));
      let lo = 0, hi = 0, series = [], s = '';
      if (this.an.mode === 'income') {
        lo = 0; hi = Math.max(1, ...flMonths.map(m => m.eur));
      } else if (this.an.mode === 'balance') {
        // the balance at the left edge of the window, then each logged day inside it
        const pts = (this.anSeries?.points || []);
        let open = this.anSeries?.opening || 0;
        for (const p of pts) { if (this._ms(p.date) < this.an.x0) open = p.surplus_hours; else break; }
        series = [[this.an.x0, open]];
        for (const p of pts) { const t = this._ms(p.date); if (t >= this.an.x0 && t < this.an.x1) series.push([t + DAY / 2, p.surplus_hours]); }
        const last = series[series.length - 1][1];
        series.push([Math.min(this.an.x1, today + DAY / 2), last]);
        lo = Math.min(0, ...series.map(p => p[1])); hi = Math.max(0, ...series.map(p => p[1]));
      } else if (this.an.mode === 'day') {
        const flOnly = Object.keys(flByDay).filter(d => !vis.some(e => e.date === d)).map(d => flByDay[d]);
        lo = 0; hi = Math.max(target, ...vis.map(e => e.net_hours + (e.leave_hours || 0) + (flByDay[e.date] || 0)), ...flOnly);
      } else {
        lo = 0; hi = Math.max(1, ...this.anMonths(vis).map(m => Math.max(m.net + (flMonthMap[m.key]?.hours || 0), m.target)), ...flMonths.map(m => m.hours));
      }
      const span = Math.max(hi - lo, 2); lo -= span * 0.08; hi += span * 0.08;
      const Y = v => PADT + (H - PADT - PADB) * (1 - (v - lo) / (hi - lo));
      const rawStep = (hi - lo) / 5;
      const step = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500].find(v => v >= rawStep) || 1000;
      const money = this.an.mode === 'income';
      if (money) {
        // euros on the axis: a nice step of its own
        const rawStepM = (hi - lo) / 5;
        const stepM = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000].find(v => v >= rawStepM) || 100000;
        for (let v = 0; v <= hi; v += stepM) s += `<line class="an-grid" x1="${PADL}" x2="${W - PADR}" y1="${f(Y(v))}" y2="${f(Y(v))}"/><text class="an-yl" x="${PADL - 6}" y="${f(Y(v) + 3)}">${v >= 1000 ? Math.round(v / 100) / 10 + 'k' : v}</text>`;
      } else for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
        s += `<line class="an-grid" x1="${PADL}" x2="${W - PADR}" y1="${f(Y(v))}" y2="${f(Y(v))}"/><text class="an-yl" x="${PADL - 6}" y="${f(Y(v) + 3)}">${v > 0 ? '+' : ''}${Math.round(v * 10) / 10}</text>`;
      }
      for (const [t, l] of this.anXTicks()) s += `<line class="an-grid" x1="${f(X(t))}" x2="${f(X(t))}" y1="${PADT}" y2="${H - PADB}"/><text class="an-xl" x="${f(X(t))}" y="${H - 8}">${l}</text>`;
      if (lo < 0 && hi > 0) s += `<line class="an-zero" x1="${PADL}" x2="${W - PADR}" y1="${f(Y(0))}" y2="${f(Y(0))}"/>`;
      if (this.an.mode === 'balance') {
        const last = series[series.length - 1][1], tone = this.surplusClass(last);
        const path = series.map(([t, v], i) => `${i ? 'L' : 'M'}${f(X(t))} ${f(Y(v))}`).join('');
        s += `<path class="an-area ${tone}" d="${path}L${f(X(series[series.length - 1][0]))} ${f(Y(0))}L${f(X(series[0][0]))} ${f(Y(0))}Z"/><path class="an-line ${tone}" d="${path}"/>`;
      } else if (this.an.mode === 'day') {
        const bw = Math.max(1, (W - PADL - PADR) / ((this.an.x1 - this.an.x0) / DAY) * 0.7);
        const drawn = new Set();
        for (const e of vis) {
          const t = this._ms(e.date), h = e.net_hours + (e.leave_hours || 0);
          const style = this.entryCellStyle(e);
          s += `<rect class="an-bar ${this.entryCellCls(e)}" x="${f(X(t + DAY / 2) - bw / 2)}" width="${f(bw)}" y="${f(Y(h))}" height="${f(Math.max(0, Y(0) - Y(h)))}"${style ? ` style="${style.replace(/"/g, "'")}"` : ''}><title>${e.date} · ${this.pillLabel(e)} · ${e.net_hours}h · ${this.formatSurplus(e.surplus_hours)}</title></rect>`;
          const fl = flByDay[e.date];
          if (fl) { drawn.add(e.date); s += `<rect class="an-bar an-bar-fl" x="${f(X(t + DAY / 2) - bw / 2)}" width="${f(bw)}" y="${f(Y(h + fl))}" height="${f(Math.max(0, Y(h) - Y(h + fl)))}"><title>${e.date} · ⚡ ${this.fmtHours(fl)} freelance</title></rect>`; }
        }
        // freelance on a day without an employee entry (a Saturday): its own bar
        for (const [d, fl] of Object.entries(flByDay)) {
          if (drawn.has(d)) continue;
          const t = this._ms(d);
          s += `<rect class="an-bar an-bar-fl" x="${f(X(t + DAY / 2) - bw / 2)}" width="${f(bw)}" y="${f(Y(fl))}" height="${f(Math.max(0, Y(0) - Y(fl)))}"><title>${d} · ⚡ ${this.fmtHours(fl)} freelance</title></rect>`;
        }
        s += `<line class="an-target" x1="${PADL}" x2="${W - PADR}" y1="${f(Y(target))}" y2="${f(Y(target))}"/>`;
      } else if (this.an.mode === 'income') {
        for (const m of flMonths) {
          const [y, mo] = m.key.split('-').map(Number);
          const t0 = Math.max(this.an.x0, +new Date(y, mo - 1, 1)), t1 = Math.min(this.an.x1, +new Date(y, mo, 1));
          const x0 = X(t0) + 3, x1 = X(t1) - 3;
          s += `<rect class="an-bar an-bar-fl" x="${f(x0)}" width="${f(Math.max(1, x1 - x0))}" y="${f(Y(m.eur))}" height="${f(Math.max(0, Y(0) - Y(m.eur)))}"><title>${m.key} · ${this.fmtMoney(m.eur)} · ${this.fmtHours(m.hours)}</title></rect>`;
          if (x1 - x0 > 34) s += `<text class="an-bar-lbl" x="${f((x0 + x1) / 2)}" y="${f(Y(m.eur) - 4)}">${this.fmtMoney0(m.eur)}</text>`;
        }
      } else {
        for (const m of this.anMonths(vis)) {
          const [y, mo] = m.key.split('-').map(Number);
          const t0 = Math.max(this.an.x0, +new Date(y, mo - 1, 1)), t1 = Math.min(this.an.x1, +new Date(y, mo, 1));
          const x0 = X(t0) + 3, x1 = X(t1) - 3;
          s += `<rect class="an-bar hm-${this.surplusClass(m.surplus)}" x="${f(x0)}" width="${f(Math.max(1, x1 - x0))}" y="${f(Y(m.net))}" height="${f(Math.max(0, Y(0) - Y(m.net)))}"><title>${m.key} · ${m.net}h / ${m.target}h · ${this.formatSurplus(m.surplus)}</title></rect>`;
          const fl = flMonthMap[m.key];
          if (fl) s += `<rect class="an-bar an-bar-fl" x="${f(x0)}" width="${f(Math.max(1, x1 - x0))}" y="${f(Y(m.net + fl.hours))}" height="${f(Math.max(0, Y(m.net) - Y(m.net + fl.hours)))}"><title>${m.key} · ⚡ ${this.fmtHours(fl.hours)} freelance · ${this.fmtMoney(fl.eur)}</title></rect>`;
          s += `<line class="an-target" x1="${f(x0)}" x2="${f(x1)}" y1="${f(Y(m.target))}" y2="${f(Y(m.target))}"/>`;
        }
        for (const fl of flMonths) {
          if (this.anMonths(vis).some(m => m.key === fl.key)) continue;
          const [y, mo] = fl.key.split('-').map(Number);
          const t0 = Math.max(this.an.x0, +new Date(y, mo - 1, 1)), t1 = Math.min(this.an.x1, +new Date(y, mo, 1));
          const x0 = X(t0) + 3, x1 = X(t1) - 3;
          s += `<rect class="an-bar an-bar-fl" x="${f(x0)}" width="${f(Math.max(1, x1 - x0))}" y="${f(Y(fl.hours))}" height="${f(Math.max(0, Y(0) - Y(fl.hours)))}"><title>${fl.key} · ⚡ ${this.fmtHours(fl.hours)} freelance</title></rect>`;
        }
      }
      if (today >= this.an.x0 && today <= this.an.x1) s += `<line class="an-today" x1="${f(X(today + DAY / 2))}" x2="${f(X(today + DAY / 2))}" y1="${PADT}" y2="${H - PADB}"/>`;
      const d = this.an.drag;
      if (d && d.kind === 'select') { const a = Math.min(d.a, d.b), b = Math.max(d.a, d.b); s += `<rect class="an-sel" x="${f(a)}" y="${PADT}" width="${f(b - a)}" height="${H - PADT - PADB}"/>`; }
      if (this.an.hover !== null && this.an.mode === 'balance' && !d) {
        const t = this.an.hover; let v = series[0][1]; for (const [pt, pv] of series) { if (pt <= t) v = pv; else break; }
        s += `<line class="an-hover-x" x1="${f(X(t))}" x2="${f(X(t))}" y1="${PADT}" y2="${H - PADB}"/><circle class="an-hover-dot" cx="${f(X(t))}" cy="${f(Y(v))}" r="3.5"/>`;
        s += `<text class="an-hover-lbl" x="${f(Math.min(X(t) + 8, W - PADR - 70))}" y="${f(Y(v) - 8)}">${this.formatSurplus(v)} · ${new Date(t).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })}</text>`;
      }
      const svg = `<svg class="an-chart" viewBox="0 0 ${W} ${H}" aria-hidden="true">${s}</svg>`;
      const sum = this.anSummary(), flSum = this.anFlSummary();
      const aria = `${this.anRangeLabel()}: ${sum ? this.formatSurplus(sum.surplus) + ' over ' + sum.net + 'h worked' : 'nothing logged'}`
        + (flSum && flSum.hours ? `; ${this.fmtHours(flSum.hours)} freelance, ${this.fmtMoney(flSum.eur)}.` : '.');
      this.anChart = { svg, brush: this.anChart.brush, aria };
    },

    // The strip under the chart: the whole history's balance, once per load.
    anRenderBrush() {
      const pts = this.anSeries?.points || [];
      const [f0, f1] = this.anFull();
      const vals = pts.map(p => p.surplus_hours).concat([0]);
      const lo = Math.min(...vals), hi = Math.max(...vals);
      const x = t => (t - f0) / (f1 - f0) * 620, y = v => 2 + 30 * (1 - (v - lo) / (hi - lo || 1));
      let path = `M${x(f0).toFixed(1)} ${y(0).toFixed(1)}`;
      for (const p of pts) path += `L${x(this._ms(p.date)).toFixed(1)} ${y(p.surplus_hours).toFixed(1)}`;
      this.anChart.brush = `<svg viewBox="0 0 620 34" preserveAspectRatio="none" aria-hidden="true"><path d="${path}" class="an-brush-line" vector-effect="non-scaling-stroke"/></svg>`;
    },

    // Pointer handling, attached once to the wrap (the svg inside is replaced on every render):
    // drag = rectangle zoom, shift+drag = pan, wheel = zoom at the cursor, double-click = reset;
    // on touch one finger pans and two pinch. The brush strip pans by dragging its window.
    anInit(wrap) {
      const px = ev => { const r = wrap.querySelector('svg')?.getBoundingClientRect(); return r ? (ev.clientX - r.left) / r.width * this.AN_W : 0; };
      const pointers = new Map();
      wrap.addEventListener('pointerdown', ev => {
        if (ev.button !== undefined && ev.button !== 0) return;
        wrap.setPointerCapture(ev.pointerId);
        pointers.set(ev.pointerId, ev.clientX);
        if (pointers.size === 2) {
          const [a, b] = [...pointers.values()];
          this.an.pinch = { d: Math.abs(a - b), x0: this.an.x0, x1: this.an.x1 };
          this.an.drag = null;
          return;
        }
        const x = px(ev);
        const pan = ev.shiftKey || ev.pointerType === 'touch';
        this.an.drag = { kind: pan ? 'pan' : 'select', a: x, b: x, x0: this.an.x0, x1: this.an.x1 };
        ev.preventDefault();
      });
      wrap.addEventListener('pointermove', ev => {
        if (pointers.has(ev.pointerId)) pointers.set(ev.pointerId, ev.clientX);
        if (this.an.pinch && pointers.size === 2) {
          const [a, b] = [...pointers.values()], d = Math.abs(a - b) || 1;
          const k = this.an.pinch.d / d, c = (this.an.pinch.x0 + this.an.pinch.x1) / 2, half = (this.an.pinch.x1 - this.an.pinch.x0) / 2 * k;
          this.anSetRange(c - half, c + half);
          return;
        }
        const d = this.an.drag;
        if (d) {
          const x = px(ev);
          if (d.kind === 'select') { d.b = x; this.anRender(); }
          else {
            const dt = (x - d.a) / (this.AN_W - this.AN_PADL - this.AN_PADR) * (d.x1 - d.x0);
            this.anSetRange(d.x0 - dt, d.x1 - dt);
          }
          return;
        }
        if (ev.pointerType !== 'touch') { this.an.hover = this.anT(px(ev)); if (this.an.mode === 'balance') this.anRender(); }
      });
      const up = ev => {
        pointers.delete(ev.pointerId);
        if (pointers.size < 2) this.an.pinch = null;
        const d = this.an.drag;
        if (!d) return;
        this.an.drag = null;
        if (d.kind === 'select' && Math.abs(d.b - d.a) > 4) this.anSetRange(this.anT(Math.min(d.a, d.b)), this.anT(Math.max(d.a, d.b)));
        else this.anRender();
      };
      wrap.addEventListener('pointerup', up);
      wrap.addEventListener('pointercancel', up);
      wrap.addEventListener('pointerleave', () => { if (!this.an.drag) { this.an.hover = null; this.anRender(); } });
      wrap.addEventListener('wheel', ev => {
        ev.preventDefault();
        const t = this.anT(px(ev)), k = ev.deltaY < 0 ? 0.8 : 1.25;
        this.anSetRange(t - (t - this.an.x0) * k, t + (this.an.x1 - t) * k);
      }, { passive: false });
      wrap.addEventListener('dblclick', () => this.anPreset('year'));
      // the brush strip
      this.$nextTick(() => {
        const brush = this.$refs.anBrush;
        if (!brush) return;
        let drag = null;
        brush.addEventListener('pointerdown', ev => { brush.setPointerCapture(ev.pointerId); drag = { x: ev.clientX, w: brush.getBoundingClientRect().width, x0: this.an.x0, x1: this.an.x1 }; ev.preventDefault(); });
        brush.addEventListener('pointermove', ev => {
          if (!drag) return;
          const [f0, f1] = this.anFull();
          const dt = (ev.clientX - drag.x) / drag.w * (f1 - f0);
          this.anSetRange(drag.x0 + dt, drag.x1 + dt);
        });
        const end = () => { drag = null; };
        brush.addEventListener('pointerup', end); brush.addEventListener('pointercancel', end);
      });
    },

    // ── year at a glance: the pin ───────────────────────────────────────────
    // Once the full year has scrolled out through the top of the viewport, a compact copy is
    // shown fixed at the top. Fixed, not sticky: it takes no room in the page, so showing it
    // never moves the content under the scroll (a shrinking sticky block did, and bounced).
    anPinInit(root) {
      if (this._anPinObserver) this._anPinObserver.disconnect();
      this.anStuck = false;
      const glance = root.querySelector('.an-glance');
      if (!glance || !('IntersectionObserver' in window)) return;
      this._anPinObserver = new IntersectionObserver(([en]) => {
        this.anStuck = !en.isIntersecting && en.boundingClientRect.top < 0;
        if (this.anStuck) this.hmTip.show = false;
      }, { threshold: 0 });
      this._anPinObserver.observe(glance);
    },
    // Where a year does not fit (a phone), the heatmap opens on today's month, and its right edge
    // fades while there is more to see. The cells render a moment after the box, so it tries again.
    anHeatmapStart(el) {
      let tries = 0;
      const place = () => {
        const today = el.querySelector('.hm-today');
        if (!today) { if (tries++ < 10) setTimeout(place, 60); return; }
        if (el.scrollWidth > el.clientWidth + 1) {
          const left = today.getBoundingClientRect().left - el.getBoundingClientRect().left + el.scrollLeft;
          el.scrollLeft = Math.max(0, left - (el.clientWidth - today.offsetWidth) / 2);
        }
        this.anHeatmapFade(el);
      };
      this.$nextTick(place);
    },
    anHeatmapFade(el) {
      el.classList.toggle('more-r', el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
    },
    // The year of the heatmap, one step at a time (any year; an empty one shows empty).
    anStepYear(d) { this.analyticsYear = String(Number(this.analyticsYear) + d); },
    anUnstick() { window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); },

    // ── year at a glance: tooltip + click ──────────────────────────────────
    hmHover(ev) {
      const cell = ev.target.closest('.hm-cell');
      if (!cell || !cell.dataset.date) { this.hmTip.show = false; return; }
      const date = cell.dataset.date;
      const e = this.entries.find(x => x.date === date), draft = this.draftMap()[date];
      const d = new Date(date + 'T12:00:00');
      const title = d.toLocaleDateString('en-US', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
      let body = '', note = '', hint = 'click → log it';
      if (e) {
        const pill = `<span class="day-pill ${e.day_type}">${this.pillLabel(e)}</span>`;
        const hours = `${e.start_time || '—'}–${e.end_time || '—'} · <b>${e.net_hours}h</b> · <b class="${this.surplusClass(e.surplus_hours)}">${this.formatSurplus(e.surplus_hours)}</b>`;
        body = e.day_type === 'work' ? hours : this.isPartial(e) ? `${pill} · ${hours}` : pill;
        note = e.notes || '';
        hint = 'click → open in Log';
      } else if (draft) {
        body = `<span class="day-pill ghost ${draft.day_type}">${draft.day_type}</span> · planned`;
        note = draft.notes || '';
      } else {
        body = '<span class="muted">no entry</span>';
      }
      // The freelance blocks of the day, whatever the switch shows: a mixed day is shown whole.
      const fl = this.blocksOn(date);
      if (fl.length) {
        const lines = fl.map(b => `<span class="hm-tip-fl-dot" style="background:${this.sourceColor(b.source_id)}"></span>${String(b.source_name).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')} · ${this.fmtHours(b.hours)} · ${b.amount_eur === null ? 'no rate' : this.fmtMoney(b.amount_eur)}`);
        body += `<div class="hm-tip-fl">⚡ ${lines.join('<br>')}</div>`;
      }
      this.hmTip = { show: true, x: Math.min(window.innerWidth - 280, ev.clientX + 14), y: ev.clientY + 14, title, body, note, hint };
    },
    hmClick(ev) {
      const cell = ev.target.closest('.hm-cell');
      if (cell && cell.dataset.date) { this.hmTip.show = false; this.openDayInLog(cell.dataset.date); }
    },

    // ISO-8601 week number for a given date.
    isoWeekNumber(y, mo, dom) {
      const d = new Date(Date.UTC(y, mo, dom));
      const day = (d.getUTCDay() + 6) % 7;
      d.setUTCDate(d.getUTCDate() - day + 3);
      const firstThu = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
      const firstDay = (firstThu.getUTCDay() + 6) % 7;
      firstThu.setUTCDate(firstThu.getUTCDate() - firstDay + 3);
      return 1 + Math.round((d - firstThu) / (7 * 86400000));
    },

    // Year-at-a-glance heatmap cells for the selected year.
    // Returns { cells, colTemplate } where day cells have { key, type:'day', date, row, col, cls, title, weekend },
    // month label cells have { key, type:'label', label, row:8, col }, and week number cells have
    // { key, type:'week', label, row:9, col } — a week split across a month boundary gets the same
    // ISO week number on both sides.
    heatmapCells() {
      if (!this.entries.length && !this.blocks.length) return null;
      const year = parseInt(
        this.analyticsYear === 'all' ? new Date().getFullYear() : this.analyticsYear
      );
      const map = {};
      for (const e of this.entries) {
        if (e.date.startsWith(String(year))) map[e.date] = e;
      }
      const drafts = this.draftMap();

      const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

      // Pass 1: build raw day list. A day's column is the index of its week
      // *within its own month*, so a week split across two months no longer
      // drags the new month's first days into the previous month's block.
      const rawDays = [];
      const weeksInMonth = [];
      for (let mo = 0; mo < 12; mo++) {
        const offset = (new Date(year, mo, 1).getDay() + 6) % 7;   // Mon=0…Sun=6
        const daysInMonth = new Date(year, mo + 1, 0).getDate();
        weeksInMonth[mo] = Math.ceil((offset + daysInMonth) / 7);
        const mm = String(mo + 1).padStart(2, '0');
        for (let dom = 1; dom <= daysInMonth; dom++) {
          rawDays.push({
            iso: `${year}-${mm}-${String(dom).padStart(2, '0')}`,
            month: mo,
            dom,
            week: Math.floor((offset + dom - 1) / 7),
            row: (offset + dom - 1) % 7,
          });
        }
      }

      // Pass 2: lay the months out left to right with a narrow gap column between
      const monthStartCol = [];
      const finalColIsGap = {};
      let finalCol = 0;
      for (let mo = 0; mo < 12; mo++) {
        if (mo > 0) {
          finalCol++;
          finalColIsGap[finalCol] = true;
        }
        monthStartCol[mo] = finalCol + 1;
        finalCol += weeksInMonth[mo];
      }
      const totalFinalCols = finalCol;

      // Pass 3: build cells array
      const cells = [];

      // Month label cells at the first column of each month
      for (let mo = 0; mo < 12; mo++) {
        cells.push({ key: `label-${mo}`, type: 'label', label: MONTH_NAMES[mo], row: 8, col: monthStartCol[mo], cls: '', style: '', title: '', weekend: false });
      }

      // Week number cells, one per non-gap column, below the month labels
      for (let mo = 0; mo < 12; mo++) {
        for (let w = 0; w < weeksInMonth[mo]; w++) {
          const day = rawDays.find(d => d.month === mo && d.week === w);
          const col = monthStartCol[mo] + w;
          cells.push({ key: `week-${col}`, type: 'week', label: this.isoWeekNumber(year, mo, day.dom), row: 9, col, cls: '', style: '', title: '', weekend: false });
        }
      }

      // Day cells — the employee's day, or (the switch) the freelance hours of the day
      const flMode = this.hmMode === 'freelance' && this.hasFreelance();
      const flByDay = {};
      if (flMode) for (const b of this.blocks) if (b.date.startsWith(String(year))) flByDay[b.date] = (flByDay[b.date] || 0) + b.minutes / 60;
      for (const day of rawDays) {
        const entry = map[day.iso];
        const draft = entry ? null : drafts[day.iso];
        let cls, style = '', title;
        if (flMode) {
          const h = Math.round((flByDay[day.iso] || 0) * 100) / 100;
          cls = this.flLevelCls(h);
          title = h ? `${day.iso} · ${this.fmtHours(h)} freelance` : day.iso;
        } else {
          cls = this.dayCellCls(entry, draft);
          style = this.entryCellStyle(entry);
          const sign = entry && entry.surplus_hours > 0 ? '+' : '';
          title = entry ? `${day.iso} · ${this.pillLabel(entry)} · ${sign}${entry.surplus_hours}h`
            : draft ? `${day.iso} · ${draft.day_type} · planned` : day.iso;
        }
        const today = day.iso === this.todayIso();
        cells.push({ key: day.iso, type: 'day', date: day.iso, row: day.row + 1, col: monthStartCol[day.month] + day.week, cls, style, title, weekend: day.row >= 5, today });
      }

      // Build CSS grid-template-columns string
      const parts = [];
      for (let fc = 1; fc <= totalFinalCols; fc++) {
        parts.push(finalColIsGap[fc] ? 'var(--hm-g, 5px)' : 'var(--hm-c, 13px)');
      }

      return { cells, colTemplate: parts.join(' ') };
    },

    // =====================================================================
    // analytics
    // =====================================================================
    async loadAnalytics() {
      this.loading.analytics = true;
      try {
        const [yearly, series] = await Promise.all([
          this.api('GET', '/api/analytics/yearly'),
          this.api('GET', '/api/analytics/cumulative-series?all=true'),
        ]);
        this.yearly = yearly;
        this.anSeries = series;
        // Entries feed the heatmap and everything the chart's range drives.
        if (!this.entries.length) await this.loadDays();
        await this.loadSources();
        if (this.hasFreelance() && (!this.flSummary || this._flStale)) this.loadFlSummary(new Date().getFullYear());
        if (this.an.mode === 'income' && !this.hasFreelance()) this.an.mode = 'balance';
        if (!this.yearsWithData().includes(this.analyticsYear)) this.analyticsYear = this.yearsWithData()[0] || this.analyticsYear;
        this.anRenderBrush();
        if (this.an.preset) this.anPreset(this.an.preset); else this.anSetRange(this.an.x0, this.an.x1);
      } catch (e) { this.error = e.message; }
      finally { this.loading.analytics = false; }
    },

    // =====================================================================
    // settings
    // =====================================================================
    async loadSettings() {
      this.loading.settings = true;
      try {
        const cfg = await this.api('GET', '/api/config');
        // Give each timeline row a stable client key so x-for doesn't reuse/rebind
        // the wrong <input> when a middle row is removed.
        cfg.daily_target_schedule = this._keyedSchedule(cfg.daily_target_schedule);
        this.settingsForm = { ...cfg };
        this._settingsSaved = JSON.parse(JSON.stringify(cfg));
      } catch (e) { this.error = e.message; }
      finally { this.loading.settings = false; }
    },

    // Autosaves of one thing run one after the other: two PUTs in flight could land in the
    // wrong order and leave the older value in the database.
    _queued(key, fn) {
      const chain = (this._saveChain ||= {});
      const run = (chain[key] || Promise.resolve()).then(fn, fn);
      chain[key] = run.catch(() => {});
      return run;
    },
    // Save one section's fields (autosave), or every dirty field (Ctrl+Enter, with a toast).
    saveSettings(section, opts = {}) { return this._queued('config', () => this._saveSettings(section, opts)); },
    async _saveSettings(section, { quiet = false } = {}) {
      const sections = section ? this.SETTINGS_SECTIONS.filter(s => s.id === section) : this.SETTINGS_SECTIONS;
      const body = {};
      for (const s of sections) for (const k of s.fields) body[k] = this.settingsForm[k];
      if (!Object.keys(body).length) return;
      if (section) this._setStatus(section, 'busy');
      try {
        await this.api('PUT', '/api/config', body);
        for (const k of Object.keys(body)) this._settingsSaved[k] = JSON.parse(JSON.stringify(body[k]));
        if (section) this._setStatus(section, 'saved'); else if (!quiet) this.showToast('Settings saved', 'neutral');
        this.loadDashboard();  // the target or the start date may have moved every number
        if ('freelance_hours_per_week' in body) this._flStale = true;  // the projection moved
      } catch (e) { this.error = e.message; if (section) this._setStatus(section, 'error'); }
    },
    // A field of a section changed: save it half a second after the last keystroke (a switch or
    // a picker at once), only when something is dirty and the card's fields are valid. The
    // target timeline inside the Work card saves through its own endpoint.
    settingsTouched(section, event, immediate = false) {
      const el = event?.target;
      if (el && el.closest('.target-schedule')) { this.timelineTouched(immediate); return; }
      clearTimeout(this._autosave[section]);
      const run = () => {
        if (!this.settingsDirty(section)) { if (this.settingsStatus[section] === 'invalid') this._setStatus(section, ''); return; }
        const form = document.getElementById('settings-' + section);
        if (form && form.checkValidity && !form.checkValidity()) { this._setStatus(section, 'invalid'); return; }
        this.saveSettings(section, { quiet: true });
      };
      if (immediate) run(); else this._autosave[section] = setTimeout(run, 600);
    },
    _setStatus(section, status) {
      this.settingsStatus = { ...this.settingsStatus, [section]: status };
      clearTimeout(this._autosave['fade-' + section]);
      if (status === 'saved') this._autosave['fade-' + section] = setTimeout(() => { if (this.settingsStatus[section] === 'saved') this._setStatus(section, ''); }, 2200);
    },
    settingsStatusText(section) {
      return { busy: '…', saved: 'saved ✓', invalid: 'check the value', error: 'not saved' }[this.settingsStatus[section]] || '';
    },
    settingsStatusCls(section) { return this.settingsStatus[section] ? 'is-' + this.settingsStatus[section] : ''; },
    // Flush every pending autosave (leaving Settings, switching the group or a tax year).
    settingsFlush() {
      for (const s of this.SETTINGS_SECTIONS) if (this._autosave[s.id]) { clearTimeout(this._autosave[s.id]); this._autosave[s.id] = null; if (this.settingsDirty(s.id)) this.saveSettings(s.id, { quiet: true }); }
      if (this._autosave.timeline) { clearTimeout(this._autosave.timeline); this._autosave.timeline = null; this.timelineTouched(true); }
      if (this._autosave.taxes) { clearTimeout(this._autosave.taxes); this._autosave.taxes = null; if (this.taxDirty()) this.saveTaxYear({ quiet: true }); }
    },

    settingsDirty(section) {
      if (!this._settingsSaved) return false;
      const s = this.SETTINGS_SECTIONS.find(x => x.id === section);
      return s.fields.some(k => JSON.stringify(this.settingsForm[k]) !== JSON.stringify(this._settingsSaved[k]));
    },

    // The index follows the scroll: the topmost card in view is the active section.
    initSettingsSpy(root) {
      if (this._settingsSpy) this._settingsSpy.disconnect();
      const cards = [...root.querySelectorAll('.settings-card[id]')];
      if (!('IntersectionObserver' in window) || !cards.length) return;
      const visible = new Map();
      this._settingsSpy = new IntersectionObserver(entries => {
        for (const en of entries) visible.set(en.target.id, en.isIntersecting);
        const first = cards.find(c => visible.get(c.id));
        if (first) this.settingsActive = first.id.replace('settings-', '');
      }, { rootMargin: '-10% 0px -60% 0px', threshold: 0 });
      cards.forEach(c => this._settingsSpy.observe(c));
    },
    settingsJump(id) {
      const section = this.SETTINGS_SECTIONS.find(s => s.id === id);
      if (section && section.group !== this.settingsGroup) {
        this.setSettingsGroup(section.group, id);
        return;
      }
      this.settingsActive = id;
      document.getElementById('settings-' + id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    // The first level: switching the group swaps the cards; the index follows.
    setSettingsGroup(id, section = null) {
      this.settingsFlush();
      this.settingsGroup = id;
      localStorage.setItem('k-settings-group', id);
      this.settingsActive = section || this.settingsSections(id)[0].id;
      this.loadSettingsGroupData();
      this.$nextTick(() => {
        const root = document.querySelector('.settings-layout');
        if (root) this.initSettingsSpy(root);
        if (section) document.getElementById('settings-' + section)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    },
    // The brass tick beside the open group's links: it slides to the current link (like the tab bar's
    // ink and the bezel's lit tick). The links' own boxes are measured, so it follows any wrap.
    settingsTick(box) {
      const link = box.querySelector('a.active');
      if (!link || box.offsetParent === null) { box.style.setProperty('--tick-h', '0px'); return; }
      box.style.setProperty('--tick-y', link.offsetTop + 'px');
      box.style.setProperty('--tick-h', link.offsetHeight + 'px');
    },
    settingsSections(group = this.settingsGroup) { return this.SETTINGS_SECTIONS.filter(s => s.group === group); },
    settingsGroupLabel() { return this.SETTINGS_GROUPS.find(g => g.id === this.settingsGroup)?.label || ''; },
    // What the Freelance group shows that the config does not carry: the sources, the year's
    // tax inputs and the ECB rate (asked for here because this view shows it).
    loadSettingsGroupData() {
      if (this.settingsGroup !== 'freelance') return;
      this.loadSources();
      this.loadTaxYear(this.taxYear);
      this.loadFx();
    },

    // ---------- date-effective daily target ------------------------------
    _keyedSchedule(rows) {
      return (rows || []).map(r => ({
        _k: ++this._scheduleKeySeq,
        effective_from: r.effective_from,
        hours: r.hours,
      }));
    },
    addTargetChange() {
      const sched = this.settingsForm.daily_target_schedule || [];
      const last = sched[sched.length - 1];
      this.settingsForm.daily_target_schedule = [
        ...sched,
        {
          _k: ++this._scheduleKeySeq,
          effective_from: this.todayIso(),
          hours: last ? last.hours : (this.settingsForm.daily_target_hours || 8),
        },
      ];
    },
    removeTargetChange(i) {
      const sched = [...(this.settingsForm.daily_target_schedule || [])];
      sched.splice(i, 1);
      this.settingsForm.daily_target_schedule = sched;
      this.timelineTouched(true);
    },
    _timelineRows() {
      return (this.settingsForm.daily_target_schedule || []).map(r => ({ effective_from: r.effective_from, hours: Number(r.hours) }));
    },
    timelineDirty() {
      return JSON.stringify(this._timelineRows()) !== JSON.stringify((this._settingsSaved?.daily_target_schedule || []).map(r => ({ effective_from: r.effective_from, hours: Number(r.hours) })));
    },
    // The timeline saves itself once every row has a date and hours (a half-typed date waits).
    timelineTouched(immediate = false) {
      clearTimeout(this._autosave.timeline);
      const run = () => {
        const rows = this._timelineRows();
        if (!rows.length || !this.timelineDirty()) return;
        if (!rows.every(r => /^\d{4}-\d{2}-\d{2}$/.test(r.effective_from || '') && r.hours > 0 && r.hours <= 24)) { this._setStatus('timeline', 'invalid'); return; }
        this.saveDailyTargetSchedule({ quiet: true });
      };
      if (immediate) run(); else this._autosave.timeline = setTimeout(run, 800);
    },
    saveDailyTargetSchedule(opts = {}) { return this._queued('timeline', () => this._saveDailyTargetSchedule(opts)); },
    async _saveDailyTargetSchedule({ quiet = false } = {}) {
      const rows = this._timelineRows();
      if (!rows.length) { this.error = 'Add at least one target row.'; return; }
      this._setStatus('timeline', 'busy');
      try {
        const saved = await this.api('PUT', '/api/config/daily-target-schedule', { rows });
        // The server sorts and dedupes; keep the rows as typed (no re-keying under the
        // cursor) but take the current target and the saved copy from the answer.
        const last = saved.rows[saved.rows.length - 1];
        this.settingsForm.daily_target_hours = last.hours;
        if (this._settingsSaved) { this._settingsSaved.daily_target_hours = last.hours; this._settingsSaved.daily_target_schedule = saved.rows.map(r => ({ ...r })); }
        this._setStatus('timeline', 'saved');
        if (!quiet) this.showToast('Target timeline saved', 'neutral');
        this.loadDashboard();  // cumulative/surplus numbers may shift
      } catch (e) { this.error = e.message; this._setStatus('timeline', 'error'); }
    },

    // =====================================================================
    // public holidays
    // =====================================================================
    // Country + region lists are proxied through the backend so the browser
    // never calls the external holiday API directly. Loaded lazily when the
    // Settings tab opens; the country list is cached across visits.
    async loadHolidayData() {
      if (!this.holidayCountries.length) {
        try { this.holidayCountries = await this.api('GET', '/api/holidays/countries'); }
        catch { this.holidayCountries = []; }
      }
      await this.loadHolidaySubdivisions();
      await this.loadHolidayPreview();
    },

    async loadHolidaySubdivisions() {
      const c = this.settingsForm.holiday_country;
      if (!c) { this.holidaySubdivisions = []; return; }
      try {
        this.holidaySubdivisions = await this.api(
          'GET', `/api/holidays/subdivisions?country=${c}&year=${this.holidayYear}`
        );
      } catch { this.holidaySubdivisions = []; }
      // Drop a stale region that no longer appears in the list.
      if (this.settingsForm.holiday_region && !this.holidaySubdivisions.includes(this.settingsForm.holiday_region)) {
        this.settingsForm.holiday_region = '';
      }
    },

    async loadHolidayPreview() {
      const c = this.settingsForm.holiday_country;
      if (!c) { this.holidayPreview = []; return; }
      const region = this.settingsForm.holiday_region;
      try {
        this.holidayPreview = await this.api(
          'GET', `/api/holidays/preview?country=${c}&year=${this.holidayYear}`
            + (region ? `&region=${encodeURIComponent(region)}` : '')
        );
      } catch (e) {
        // Say why (e.g. Spain's BOE list for this year isn't known yet), not just an empty calendar.
        this.holidayPreview = [];
        this.error = e.message;
      }
    },

    async onHolidayCountryChange() {
      this.settingsForm.holiday_region = '';
      await this.loadHolidaySubdivisions();
      await this.loadHolidayPreview();
    },

    // Summary line: "9 national · 3 regional · 2 already logged".
    holidayPreviewSummary() {
      const nat = this.holidayPreview.filter(h => !h.regional).length;
      const reg = this.holidayPreview.filter(h => h.regional).length;
      const logged = this.holidayPreview.filter(h => h.exists).length;
      const parts = [`${nat} national`];
      if (reg) parts.push(`${reg} regional`);
      if (logged) parts.push(`${logged} already logged`);
      return parts.join(' · ');
    },

    holidayImportLabel() {
      if (this.holidayImporting) return 'Importing…';
      if (!this.holidayPreview.length) return 'Import holidays';
      const n = this.holidayPreview.filter(h => !h.exists).length;
      if (!n) return 'All holidays already logged';
      return `Import ${n} holiday${n !== 1 ? 's' : ''}`;
    },

    // Nothing left to import when every previewed holiday already exists.
    holidayNothingToImport() {
      return this.holidayPreview.length > 0 && this.holidayPreview.every(h => h.exists);
    },

    // Group the preview into per-month mini-calendars (Mon-first), holidays coloured.
    holidayMonths() {
      const MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December'];
      const DOW = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
      const byMonth = {};
      for (const h of this.holidayPreview) {
        const ym = h.date.slice(0, 7);
        (byMonth[ym] ||= {})[h.date] = h;
      }
      return Object.keys(byMonth).sort().map(ym => {
        const [y, mo] = ym.split('-').map(Number);
        const holidayMap = byMonth[ym];
        const firstDow = (new Date(y, mo - 1, 1).getDay() + 6) % 7; // Mon-first
        const daysInMonth = new Date(y, mo, 0).getDate();
        const cells = [];
        for (let i = 0; i < firstDow; i++) cells.push({ key: `${ym}-pad${i}`, cls: 'holiday-pad', label: '', title: '' });
        for (let d = 1; d <= daysInMonth; d++) {
          const iso = `${ym}-${String(d).padStart(2, '0')}`;
          const h = holidayMap[iso];
          const cls = !h ? '' : h.exists ? 'is-logged' : 'is-holiday';
          const title = h ? `${iso} · ${h.name}${h.regional ? ' (regional)' : ''}${h.exists ? ' — already logged' : ''}` : '';
          cells.push({ key: iso, cls, label: String(d), title });
        }
        return { key: ym, label: `${MONTH_NAMES[mo - 1]} ${y}`, dow: DOW, cells };
      });
    },

    // The previewed holidays as date-ordered rows for the list under the legend.
    holidayListItems() {
      return [...this.holidayPreview]
        .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
        .map(h => ({
          date: h.date,
          label: new Date(h.date + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }),
          name: h.name,
          regional: h.regional,
          exists: h.exists,
        }));
    },

    async importHolidays() {
      const country = this.settingsForm.holiday_country;
      if (!country) { this.error = 'Pick a country first.'; return; }
      this.holidayImporting = true;
      this.error = null;
      try {
        // Persist the selection so it's remembered next visit.
        await this.api('PUT', '/api/config', {
          holiday_country: country,
          holiday_region: this.settingsForm.holiday_region || '',
        });
        const region = this.settingsForm.holiday_region;
        const url = `/api/holidays/import?country=${country}&year=${this.holidayYear}`
          + (region ? `&region=${encodeURIComponent(region)}` : '');
        const result = await this.api('POST', url);
        this._resetCachedViews();
        await this.loadDashboard();
        await this.loadHolidayPreview(); // refresh so imported dates now show as logged
        const n = result.imported.length;
        const s = result.skipped.length;
        this.showToast(
          `${n} holiday${n !== 1 ? 's' : ''} imported${s ? `, ${s} skipped` : ''}`,
          'neutral',
        );
      } catch (e) {
        this.error = e.message;
      } finally {
        this.holidayImporting = false;
      }
    },

    // =====================================================================
    // fun zone
    // =====================================================================
    // =====================================================================
    // backup / restore
    // =====================================================================
    downloadBackup() {
      // GET /api/backup returns Content-Disposition: attachment — clicking a
      // temporary <a> triggers the browser's file-save dialog without a page nav.
      const a = document.createElement('a');
      a.href = '/api/backup';
      a.download = ''; // use the server-supplied filename
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    },

    async restoreFromFile(event) {
      const file = event.target.files[0];
      event.target.value = ''; // reset so the same file can be re-selected
      if (!file) return;

      let payload;
      try {
        payload = JSON.parse(await file.text());
      } catch {
        this.error = 'Could not parse the selected file as JSON.';
        return;
      }

      const count = payload.entries?.length ?? 0;
      const msg = `Restore ${count} entr${count === 1 ? 'y' : 'ies'} from "${file.name}"?\n\nAll current entries will be wiped first. This cannot be undone.`;
      if (!confirm(msg)) return;

      this.error = null;
      try {
        const result = await this.api('POST', '/api/restore', payload);
        this._resetCachedViews();
        await this.loadSettings();
        await this.loadSources();
        await this.loadDashboard();
        this.showToast(`Restored ${result.restored_entries} entries`, 'neutral');
        this.go('dashboard');
      } catch (e) {
        this.error = `Restore failed: ${e.message}`;
      }
    },

    async importCsvFromFile(event) {
      const file = event.target.files[0];
      event.target.value = ''; // reset so the same file can be re-selected
      if (!file) return;

      this.error = null;
      try {
        const content = await file.text();
        const result = await this.api('POST', '/api/import/csv', { content });
        this._resetCachedViews();
        await this.loadDashboard();

        const n = result.imported.length;
        const s = result.skipped.length;
        const e = result.errors.length;
        let msg = `${n} imported`;
        if (s) msg += `, ${s} skipped`;
        if (e) msg += `, ${e} error${e !== 1 ? 's' : ''}`;
        this.showToast(msg, e ? 'deficit' : 'neutral');
        if (e) {
          const shown = result.errors.slice(0, 8).join('; ');
          this.error = `Import: ${shown}${result.errors.length > 8 ? ' …' : ''}`;
        }
        this.go('dashboard');
      } catch (err) {
        this.error = `Import failed: ${err.message}`;
      }
    },

    async wipeData() {
      this.error = null;
      try {
        await this.api('DELETE', '/api/data');
        this.wipeConfirming = false;
        this.wipeInput = '';
        this._resetCachedViews();
        await this.loadDashboard();
        this.go('dashboard');
      } catch (e) { this.error = e.message; }
    },

    async seedData() {
      this.error = null;
      try {
        await this.api('POST', '/api/data/seed');
        this.seedConfirming = false;
        this.seedInput = '';
        this._resetCachedViews();
        await this.loadDashboard();
        this.go('dashboard');
      } catch (e) { this.error = e.message; }
    },

    _resetCachedViews() {
      this.entries = [];
      this.blocks = [];
      this.payouts = [];
      this.anSeries = null;
      this._flStale = true;
    },

    // =====================================================================
    // W5 — save ribbon
    // =====================================================================
    // `action` is optional: { label, run } adds a button to the ribbon (Undo), which then
    // stays a little longer so there is time to press it.
    // `seal` (a week id) puts a small brass seal in the ribbon, which then stays a little longer.
    showToast(msg, kind, action = null, seal = null) {
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this.toast = { msg, kind: kind || 'neutral', show: false, action, seal };
      this.$nextTick(() => {
        this.toast.show = true;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const delay = action ? 5000 : seal ? 3200 : reduced ? 1200 : 1800;
        this._toastTimer = setTimeout(() => { this.toast.show = false; }, delay);
      });
    },
    async toastAction() {
      const a = this.toast.action;
      this.toast.show = false;
      this.toast.action = null;
      if (a) await a.run();
    },

    // =====================================================================
    // freelance — sources, blocks on the Log tab, the ECB rate
    // =====================================================================
    // The freelance side exists once an income source does: the tab, the dashboard card,
    // the Log panel and the Analytics switches all hang off this.
    hasFreelance() { return this.sources.length > 0; },
    liveSources() { return this.sources.filter(s => !s.archived); },
    defaultSource() { return this.liveSources().find(s => s.is_default) || this.liveSources()[0] || null; },
    sourceById(id) { return this.sources.find(s => s.id === id) || null; },
    // A stable colour per source from a small palette, by position — nothing to store.
    SRC_COLORS: ['var(--k-brass)', 'var(--k-ink)', 'var(--k-flex)', 'var(--k-sick)', 'var(--k-surplus)', 'var(--k-deficit)'],
    sourceColor(id) {
      const i = this.sources.findIndex(s => s.id === id);
      return this.SRC_COLORS[(i < 0 ? 0 : i) % this.SRC_COLORS.length];
    },
    async loadSources() {
      await Promise.all([
        (async () => { try { this.sources = await this.api('GET', '/api/freelance/sources'); } catch { /* keep what we had */ } })(),
        this.loadAccounts(),
      ]);
      if (this.flForm.source_id == null || !this.sourceById(this.flForm.source_id)) this.flForm.source_id = this.defaultSource()?.id ?? null;
    },

    // ---------- money --------------------------------------------------------
    fmtMoney(n, currency = 'EUR', digits = 2) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      // a coin keeps up to eight decimals with the trailing zeros trimmed: "0.0105 BTC"
      if (this.isCoin(currency)) {
        const body = new Intl.NumberFormat('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 8 }).format(Math.abs(n));
        return `${n < 0 ? '-' : ''}${body} ${currency}`;
      }
      return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
    },
    COIN_CODES: ['BTC', 'ETH', 'USDC', 'USDT', 'SOL'],
    isCoin(code) { return this.COIN_CODES.includes(code) || this.currencyList.some(c => c.code === code && c.kind === 'crypto'); },
    // The mark before an amount field: €, $, ₿ or the code.
    curMark(code) { return code === 'EUR' ? '€' : code === 'USD' ? '$' : code === 'BTC' ? '₿' : code; },
    // "€1,234": only inside charts, where a label has no room for the cents. Everywhere else money
    // reads "€1,289.71" (fmtMoney).
    fmtMoney0(n, currency = 'EUR') { return this.fmtMoney(n, currency, 0); },
    // The Calculator speaks Spanish decimals, like its inputs do in an es browser: "€28.687,41".
    calcMoney(n, currency = 'EUR') {
      if (n === null || n === undefined || isNaN(n)) return '—';
      const body = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: 'always' }).format(Math.abs(n));
      return `${n < 0 ? '-' : ''}${currency === 'USD' ? '$' : '€'}${body}`;
    },
    // "+€170.07" / "−€12.00"
    fmtMoneySigned(n, currency = 'EUR') { return (n < 0 ? '−' : '+') + this.fmtMoney(Math.abs(n), currency); },
    pct(x, digits = 1) { return `${(Number(x) * 100).toFixed(digits)}%`; },

    // ---------- blocks of a day ------------------------------------------------
    blocksOn(iso) { return this.blocks.filter(b => b.date === iso); },
    blockHours(list) { return Math.round(list.reduce((s, b) => s + b.minutes, 0) / 60 * 100) / 100; },
    // The one money rule of the client (the server's): a block counts its effective_eur (its
    // share of the week's payout when there is one), and a payout for a week with no blocks
    // counts as a line of its own, dated on the week's Sunday. `opts` ({sources: Set|null,
    // from, to}) says which of those payout-only lines belong; without it there are none.
    flLines(blocks, opts = null) {
      const lines = blocks.map(b => ({ date: b.date, source_id: b.source_id, minutes: b.minutes, eur: b.effective_eur ?? null, paid: b.payout_id != null, block: b }));
      if (!opts) return lines;
      for (const p of this.payouts) {
        if (p.blocks !== 0) continue;
        if (opts.sources && !opts.sources.has(p.source_id)) continue;
        if (opts.from && p.week_end < opts.from) continue;
        if (opts.to && p.week_end > opts.to) continue;
        lines.push({ date: p.week_end, source_id: p.source_id, minutes: 0, eur: p.amount_eur, paid: true, block: null });
      }
      return lines;
    },
    // A missing rate is null: it adds nothing and is counted, never read as zero euros silently.
    lineEur(lines) { return Math.round(lines.reduce((s, l) => s + (l.eur || 0), 0) * 100) / 100; },
    lineMissing(lines) { return lines.filter(l => l.eur === null).length; },
    blockEur(list, opts = null) { return this.lineEur(this.flLines(list, opts)); },
    // The same lines split by where their money comes from: a payout, or the blocks' estimates.
    lineSplit(lines) {
      const paid = Math.round(lines.filter(l => l.paid).reduce((s, l) => s + (l.eur || 0), 0) * 100) / 100;
      return { paid, est: Math.round((this.lineEur(lines) - paid) * 100) / 100 };
    },
    // The dashboard card shows estimated and paid out side by side only once a payout exists.
    flPaidOn() { return this.payouts.length > 0; },
    // One period of the card: the blocks' own estimates, what was paid out (payout-only lines
    // included) and the gap of the paid part against its own estimate.
    flPeriod(blocks, range) {
      const lines = this.flLines(blocks, range);
      const paidLines = lines.filter(l => l.paid);
      const paid = this.lineEur(paidLines);
      const paidEst = this.lineEur(paidLines.map(l => ({ eur: l.block ? l.block.amount_eur : 0 })));
      return {
        hours: this.blockHours(blocks), eur: this.lineEur(lines),
        blockEst: this.lineEur(blocks.map(b => ({ eur: b.amount_eur }))),
        paid, hasPaid: paidLines.length > 0, gap: Math.round((paid - paidEst) * 100) / 100,
      };
    },
    // The Freelance hero splits its year only once a payout counts in it.
    flSplitOn() { return (this.flSummary?.total.paid_out_eur || 0) > 0; },
    flSplitPct() {
      const t = this.flSummary?.total;
      const all = t ? (t.paid_out_eur || 0) + (t.estimated_eur || 0) : 0;
      return all > 0 ? Math.round(t.paid_out_eur / all * 1000) / 10 : 0;
    },
    flAwaitingLabel() {
      const n = this.flSummary?.awaiting_payout || 0;
      return `${n} week${n !== 1 ? 's' : ''} awaiting a payout`;
    },
    // From the Freelance tab to the weeks still without a payout: Days > Freelance.
    async openAwaitingInDays() {
      this.daysMode = 'freelance';
      this._daysSourcesReady();
      await this.go('days');
    },
    hasBlocks(iso) { return this.blocks.some(b => b.date === iso); },
    flDayBlocks() { return this.blocksOn(this.form.date); },
    flDayLabel() {
      if (!this.form.date) return '';
      return new Date(this.form.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', day: 'numeric', month: 'short' });
    },
    flDayTotal(iso = this.form.date) {
      const list = this.blocksOn(iso);
      const lines = this.flLines(list, { from: iso, to: iso });
      if (!lines.length) return null;
      return { hours: this.blockHours(list), eur: this.lineEur(lines), missing: this.lineMissing(lines) };
    },
    // "3h · €270", or "3h · no rate yet" while every block of the day lacks its exchange rate.
    flTotalLabel(t) {
      if (!t) return '';
      return `${this.fmtHours(t.hours)} · ${t.eur > 0 || !t.missing ? this.fmtMoney(t.eur) : 'no rate yet'}`;
    },
    blockDuration(b) { return b.start_time ? `${b.start_time}–${b.end_time}` : ''; },
    blockAmountLabel(b) {
      if (b.currency === 'EUR') return this.fmtMoney(b.amount);
      return this.fmtMoney(b.amount, 'USD') + (b.amount_eur === null ? ' · no rate' : ` → ${this.fmtMoney(b.amount_eur)}`);
    },

    // ---------- the block editor (Log tab) -------------------------------------
    flReset() {
      const keepBy = this.flForm.by;
      this.flForm = { id: null, source_id: this.defaultSource()?.id ?? null, by: keepBy || 'hours', hours: 1, start_time: '18:00', end_time: '19:00', notes: '', rate: null, fx_rate: null };
    },
    flCancelEdit() { this.flReset(); },
    // From the header chip straight to the panel, the hours field ready.
    flJump() {
      const panel = document.querySelector('.fl-card');
      if (!panel) return;
      panel.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
      setTimeout(() => panel.querySelector('.fl-hours, .fl-times input')?.focus({ preventScroll: true }), 450);
    },
    flEdit(b) {
      this.flForm = { id: b.id, source_id: b.source_id, by: b.start_time ? 'times' : 'hours', hours: b.hours,
        start_time: b.start_time || '18:00', end_time: b.end_time || '19:00', notes: b.notes || '', rate: b.rate, fx_rate: b.fx_rate };
      this.$nextTick(() => document.querySelector('.fl-editor')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    },
    // Quarter-hour steps on the hours field; the buttons are the phone's way in.
    flStep(d) {
      const h = Math.round((Number(this.flForm.hours) || 0) * 4) / 4 + d;
      this.flForm.hours = Math.min(24, Math.max(0.25, h));
    },
    flFormHours() {
      if (this.flForm.by === 'times') return Math.round(this.rangeMinutes(this.flForm.start_time, this.flForm.end_time) / 60 * 100) / 100;
      return Number(this.flForm.hours) || 0;
    },
    // What the block will bill, from the source's rate (or the rate kept on an edited block).
    flFormPreview() {
      const src = this.sourceById(this.flForm.source_id);
      if (!src) return null;
      const rate = this.flForm.id && this.flForm.rate != null ? Number(this.flForm.rate) : src.hourly_rate;
      const currency = this.flForm.id ? (this.blocks.find(b => b.id === this.flForm.id)?.currency || src.currency) : src.currency;
      const amount = Math.round(rate * this.flFormHours() * 100) / 100;
      return { amount, currency, rate };
    },
    flFormValid() {
      return !!this.flForm.source_id && this.flFormHours() > 0 && this.flFormHours() <= 24 && !!this.form.date;
    },
    async flSave() {
      if (!this.flFormValid() || this.flBusy) return;
      this.flBusy = true;
      const f = this.flForm;
      const body = { date: this.form.date, source_id: f.source_id, notes: f.notes.trim() || null };
      if (f.by === 'times') { body.start_time = f.start_time; body.end_time = f.end_time; } else { body.hours = Number(f.hours); }
      try {
        let saved;
        if (f.id) {
          // Editing keeps the block's own rate and exchange rate (the past is not rewritten
          // by a newer source rate); they are sent as shown, so a hand edit goes through.
          if (f.rate != null) body.rate = Number(f.rate);
          if (f.fx_rate) body.fx_rate = Number(f.fx_rate);
          saved = await this.api('PUT', `/api/freelance/blocks/${f.id}`, body);
          this.blocks = this.blocks.map(b => b.id === saved.id ? saved : b);
        } else {
          saved = await this.api('POST', '/api/freelance/blocks', body);
          this.blocks = [...this.blocks, saved];
        }
        await this.reloadFlData();  // the year moved, and the week's payout may now split differently
        this.flReset();
        this.flFloatMoney(saved);
        this.showToast(`${f.id ? 'Block saved' : 'Block added'} — ${this.flDayLabel()} is ${this.flTotalLabel(this.flDayTotal())} freelance`, 'neutral');
        if (saved.currency === 'USD' && saved.fx_rate === null) this.error = 'No exchange rate was available for that day — the block counts its hours but not its money until you set one (✎).';
      } catch (e) { this.error = e.message; }
      finally { this.flBusy = false; }
    },
    // A block gone is a block gone, but the ribbon offers to put it back for a few seconds.
    async flRemove(b) {
      if (this.flBusy) return;
      this.flBusy = true;
      const row = document.querySelector(`.fl-block[data-id="${b.id}"]`);
      if (row && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        row.classList.add('leaving');
        await new Promise(r => setTimeout(r, 220));
      }
      try {
        await this.api('DELETE', `/api/freelance/blocks/${b.id}`);
        this.blocks = this.blocks.filter(x => x.id !== b.id);
        await this.reloadFlData();
        if (this.flForm.id === b.id) this.flReset();
        this.showToast(`Removed ${this.fmtHours(b.hours)} of ${b.source_name}`, 'neutral', {
          label: 'Undo',
          run: async () => {
            const body = { date: b.date, source_id: b.source_id, notes: b.notes, rate: b.rate };
            if (b.start_time) { body.start_time = b.start_time; body.end_time = b.end_time; } else { body.hours = b.hours; }
            if (b.fx_rate) body.fx_rate = b.fx_rate;
            try {
              const back = await this.api('POST', '/api/freelance/blocks', body);
              this.blocks = [...this.blocks, back];
              await this.reloadFlData();
              this.showToast('Block restored', 'neutral');
            } catch (e) { this.error = e.message; }
          },
        });
      } catch (e) { this.error = e.message; }
      finally { this.flBusy = false; }
    },
    // "+€170.07" floats up from the editor and fades — the coin landing in the jar.
    flFloatMoney(saved) {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const text = saved.amount_eur !== null ? this.fmtMoneySigned(saved.amount_eur) : `+${this.fmtHours(saved.hours)}`;
      this.flFloat = { text, key: Date.now() };
      setTimeout(() => { this.flFloat = null; }, 1300);
    },

    // ---------- the ECB rate ----------------------------------------------------
    // Asked for when a view that shows or needs a rate opens (Settings → Currency, the
    // calculator in USD) — the server itself asks the ECB at most once an hour.
    async loadFx(force = false) {
      if (this.fxInfo && !force) return this.fxInfo;
      try { this.fxInfo = await this.api('GET', '/api/fx'); }
      catch (e) { this.fxInfo = { available: false, usd_per_eur: null, date: null, source: 'ECB', stale: false, error: e.message }; }
      return this.fxInfo;
    },
    fxLabel() {
      const f = this.fxInfo;
      if (!f) return 'asking…';
      if (!f.available) return `no rate · ${(f.error || 'unavailable').replace(/\s*\(.*\)$/, '')}`;
      return `$${f.usd_per_eur} per € · ECB ${f.date}${f.stale ? ' · stale' : ''}`;
    },

    // ---------- Settings → Sources ---------------------------------------------
    srcEdit(s) { this.srcForm = { id: s.id, name: s.name, hourly_rate: s.hourly_rate, currency: s.currency }; },
    srcReset() { this.srcForm = { id: null, name: '', hourly_rate: '', currency: 'EUR' }; },
    srcFormValid() { return this.srcForm.name.trim().length > 0 && Number(this.srcForm.hourly_rate) > 0; },
    async srcSave() {
      if (!this.srcFormValid()) return;
      const body = { name: this.srcForm.name.trim(), hourly_rate: Number(this.srcForm.hourly_rate), currency: this.srcForm.currency };
      try {
        if (this.srcForm.id) await this.api('PUT', `/api/freelance/sources/${this.srcForm.id}`, body);
        else await this.api('POST', '/api/freelance/sources', body);
        const first = this.sources.length === 0;
        await this.loadSources();
        this._flStale = true;
        this.srcReset();
        this.showToast(first ? '⚡ First income source — the Freelance tab is yours' : 'Source saved', 'neutral');
        if (body.currency === 'USD') this.loadFx();
      } catch (e) { this.error = e.message; }
    },
    async srcSetAccount(s, value) {
      try { await this.api('PUT', `/api/freelance/sources/${s.id}`, { default_account_id: value === '' ? null : Number(value) }); await this.loadSources(); }
      catch (e) { this.error = e.message; await this.loadSources(); }
    },

    // ---------- Settings → Accounts ----------------------------------------------
    async loadAccounts() {
      try { this.accounts = await this.api('GET', '/api/freelance/accounts'); } catch { /* keep what we had */ }
      if (!this.currencyList.length) {
        try { this.currencyList = await this.api('GET', '/api/currencies'); } catch { /* the picker falls back to EUR and USD */ }
      }
    },
    acctKinds: ['bank', 'wallet', 'cash', 'other'],
    acctUsedBy(a) { return a && a.payouts ? `Used by ${a.payouts} payout${a.payouts !== 1 ? 's' : ''}` : ''; },
    acctLocked() { return !!this.acctForm.id && !!(this.accountById(this.acctForm.id) || {}).payouts; },
    acctEdit(a) { this.acctForm = { id: a.id, name: a.name, currency: a.currency, kind: a.kind }; this.curQuery = ''; this.curOpen = false; },
    acctReset() { this.acctForm = { id: null, name: '', currency: 'EUR', kind: 'bank' }; this.curQuery = ''; this.curOpen = false; },
    acctFormValid() { return this.acctForm.name.trim().length > 0 && !!this.acctForm.currency; },
    async acctSave() {
      if (!this.acctFormValid()) return;
      const body = { name: this.acctForm.name.trim(), currency: this.acctForm.currency, kind: this.acctForm.kind };
      try {
        if (this.acctForm.id) {
          if (this.acctLocked()) delete body.currency;
          await this.api('PUT', `/api/freelance/accounts/${this.acctForm.id}`, body);
        } else await this.api('POST', '/api/freelance/accounts', body);
        const first = this.accounts.length === 0;
        await this.loadAccounts();
        await this.reloadFlData();
        this.acctReset();
        this.showToast(first ? 'First account saved' : 'Account saved', 'neutral');
      } catch (e) { this.error = e.message; }
    },
    async acctSetDefault(a) {
      try { await this.api('PUT', `/api/freelance/accounts/${a.id}`, { is_default: !a.is_default }); await this.loadAccounts(); }
      catch (e) { this.error = e.message; }
    },
    async acctArchive(a, archived) {
      try { await this.api('PUT', `/api/freelance/accounts/${a.id}`, { archived }); await this.loadAccounts(); await this.loadSources(); }
      catch (e) { this.error = e.message; }
    },
    // Active accounts first (the default leading, as the API sends them), then the archived ones, dimmed.
    acctRows() { return [...this.accounts.filter(a => !a.archived), ...this.accounts.filter(a => a.archived)]; },
    // The currency picker: fiat first by code with its name, then the coins; typing filters.
    curOptions() {
      const q = this.curQuery.trim().toLowerCase();
      const all = this.currencyList.length ? this.currencyList : [{ code: 'EUR', name: 'Euro', kind: 'fiat' }, { code: 'USD', name: 'US dollar', kind: 'fiat' }];
      const byCode = (a, b) => (a.code < b.code ? -1 : 1);
      const sorted = [...all.filter(c => c.kind === 'fiat').sort(byCode), ...all.filter(c => c.kind !== 'fiat').sort(byCode)];
      return q ? sorted.filter(c => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)) : sorted;
    },
    curLabel(code) { const c = this.currencyList.find(x => x.code === code); return c ? `${c.code} · ${c.name}` : code; },
    curPick(c) { this.acctForm.currency = c.code; this.curQuery = ''; this.curOpen = false; },
    curKey(ev) {
      const n = this.curOptions().length;
      if (ev.key === 'ArrowDown') { ev.preventDefault(); this.curOpen = true; this.curIdx = Math.min(n - 1, this.curIdx + 1); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); this.curIdx = Math.max(0, this.curIdx - 1); }
      else if (ev.key === 'Enter' && this.curOpen) { ev.preventDefault(); const c = this.curOptions()[this.curIdx]; if (c) this.curPick(c); }
      else if (ev.key === 'Escape' && this.curOpen) { ev.stopPropagation(); this.curOpen = false; this.curQuery = ''; }
    },
    async srcSetDefault(s) {
      try { await this.api('PUT', `/api/freelance/sources/${s.id}`, { is_default: true }); await this.loadSources(); }
      catch (e) { this.error = e.message; }
    },
    async srcArchive(s, archived) {
      try { await this.api('PUT', `/api/freelance/sources/${s.id}`, { archived }); await this.loadSources(); }
      catch (e) { this.error = e.message; }
    },
    async srcDelete(s) {
      if (!confirm(`Delete the source "${s.name}"?`)) return;
      try { await this.api('DELETE', `/api/freelance/sources/${s.id}`); await this.loadSources(); this._flStale = true; }
      catch (e) { this.error = e.message; }
    },

    // ---------- Settings → Taxes (per year) --------------------------------------
    async loadTaxYear(year) {
      this.taxYear = year;
      try {
        const t = await this.api('GET', `/api/freelance/tax-years/${year}`);
        t.set_aside_pct = Math.round(t.set_aside_share * 1000) / 10;
        this.taxForm = t;
        this._taxSaved = JSON.stringify(this._taxBody());
      } catch (e) { this.error = e.message; }
    },
    _taxBody() {
      const t = this.taxForm;
      return { year: this.taxYear, salary_annual: Number(t.salary_annual) || 0, tarifa_plana: !!t.tarifa_plana, inicio_actividad: !!t.inicio_actividad,
        set_aside_share: Math.round((Number(t.set_aside_pct) || 0) * 10) / 1000, gestoria_annual: Number(t.gestoria_annual) || 0, other_expenses: Number(t.other_expenses) || 0 };
    },
    taxDirty() { return !!this.taxForm && JSON.stringify(this._taxBody()) !== this._taxSaved; },
    // Where the shown values come from: the year's own row, an earlier year's, or the defaults.
    taxOrigin() {
      const t = this.taxForm;
      if (!t) return '';
      if (t.is_default) return `${this.taxYear} has no values of its own yet — these are the defaults. Change one and they become ${this.taxYear}'s.`;
      if (t.inherited_from) return `${this.taxYear} has no values of its own — using ${t.inherited_from}'s. Change one and it gets its own.`;
      return `${this.taxYear}'s own values.`;
    },
    saveTaxYear(opts = {}) { return this._queued('taxes', () => this._saveTaxYear(opts)); },
    async _saveTaxYear({ quiet = false } = {}) {
      const year = this.taxYear, body = this._taxBody();
      this._setStatus('taxes', 'busy');
      try {
        const t = await this.api('PUT', `/api/freelance/tax-years/${year}`, body);
        if (this.taxYear !== year) return;  // the year switched meanwhile: the form is another year's
        // keep the form as typed; only the origin flags and the saved copy come from the answer
        Object.assign(this.taxForm, { inherited_from: t.inherited_from, is_default: t.is_default, fiscal_year: t.fiscal_year, region: t.region });
        this._taxSaved = JSON.stringify(this._taxBody());
        this._flStale = true;
        this._setStatus('taxes', 'saved');
        if (!quiet) this.showToast(`Taxes ${year} saved`, 'neutral');
      } catch (e) { this.error = e.message; this._setStatus('taxes', 'error'); }
    },
    taxTouched(event, immediate = false) {
      if (event?.target?.closest('.year-step')) return;
      clearTimeout(this._autosave.taxes);
      const run = () => {
        if (!this.taxForm || !this.taxDirty()) return;
        const card = document.getElementById('settings-taxes');
        if (card && [...card.querySelectorAll('input')].some(i => i.checkValidity && !i.checkValidity())) { this._setStatus('taxes', 'invalid'); return; }
        this.saveTaxYear({ quiet: true });
      };
      if (immediate) run(); else this._autosave.taxes = setTimeout(run, 600);
    },
    async switchTaxYear(year) {
      clearTimeout(this._autosave.taxes);
      if (this.taxForm && this.taxDirty()) await this.saveTaxYear({ quiet: true });
      await this.loadTaxYear(year);
    },
    async dropTaxYear() {
      if (!confirm(`Drop ${this.taxYear}'s own values and use the previous year's again?`)) return;
      try { await this.api('DELETE', `/api/freelance/tax-years/${this.taxYear}`); await this.loadTaxYear(this.taxYear); this._flStale = true; }
      catch (e) { this.error = e.message; }
    },

    // =====================================================================
    // freelance — the year (Freelance tab + dashboard card)
    // =====================================================================
    async loadFreelance() {
      // the projection's inputs are settings: have them before the strip renders
      await Promise.all([this.loadSources(), this.loadFlSummary(), this.blocks.length ? Promise.resolve() : this.loadDays(), this._settingsSaved ? Promise.resolve() : this.loadSettings()]);
      if (!this.calc.result && this.flSummary) { this.calcFromYear(false); }
    },
    async loadFlSummary(year = this.flYear) {
      try { this.flSummary = await this.api('GET', `/api/freelance/summary?year=${year}`); this._flStale = false; }
      catch (e) { this.error = e.message; }
    },
    setFlYear(y) { this.flYear = y; this.loadFlSummary(y); },
    flYears() {
      const ys = new Set(this.blocks.map(b => Number(b.date.slice(0, 4))));
      ys.add(new Date().getFullYear());
      return [...ys].sort((a, b) => b - a);
    },
    // The dashboard card: this week and month from the blocks already loaded (as the week
    // strip does), the share to set aside from the year's inputs.
    flCard() {
      if (!this.hasFreelance()) return null;
      const today = this.todayIso();
      const monday = this._mondayIso(new Date());
      const sunday = this._dateIso(new Date(new Date(monday + 'T00:00:00').getTime() + 6 * 86400000));
      const week = this.blocks.filter(b => b.date >= monday && b.date <= sunday);
      const month = this.blocks.filter(b => b.date.slice(0, 7) === today.slice(0, 7));
      const year = this.blocks.filter(b => b.date.slice(0, 4) === today.slice(0, 4));
      const rWeek = { from: monday, to: sunday };
      const rMonth = { from: today.slice(0, 7) + '-01', to: today.slice(0, 7) + '-31' };
      const rYear = { from: today.slice(0, 4) + '-01-01', to: today.slice(0, 4) + '-12-31' };
      const share = this.flSummary?.set_aside_share ?? 0.4;
      return {
        week: this.flPeriod(week, rWeek),
        month: this.flPeriod(month, rMonth),
        year: { hours: this.blockHours(year), eur: this.blockEur(year, rYear) },
        setAside: Math.round(this.blockEur(month, rMonth) * share * 100) / 100,
        share,
        netPerHour: this.flSummary?.projection?.eur_per_hour_net ?? null,
      };
    },
    // Eight tiny bars: the freelance hours of the last eight weeks, this one last.
    flCardSpark() {
      const monday = new Date(this._mondayIso(new Date()) + 'T00:00:00');
      const weeks = [];
      for (let i = 7; i >= 0; i--) {
        const a = new Date(monday); a.setDate(a.getDate() - 7 * i);
        const b = new Date(a); b.setDate(b.getDate() + 6);
        const ai = this._dateIso(a), bi = this._dateIso(b);
        weeks.push({ key: ai, hours: this.blockHours(this.blocks.filter(x => x.date >= ai && x.date <= bi)), now: i === 0 });
      }
      const max = Math.max(1, ...weeks.map(w => w.hours));
      return weeks.map(w => ({ ...w, pct: Math.round(w.hours / max * 100) }));
    },

    // The twelve months of the year as bars: what was billed (solid) and, after today, the
    // planned share of the projection (dashed). Built as markup like the other charts.
    flMonthsSvg() {
      const s = this.flSummary;
      if (!s) return '';
      const W = 420, H = 150, PADL = 8, PADR = 8, PADT = 26, PADB = 20;
      const today = new Date(this.todayIso() + 'T12:00:00');
      const year = s.year;
      const planned = s.projection.planned_gross_eur || 0;
      // spread the planned gross over the days after today, month by month
      const dec31 = new Date(year, 11, 31), jan1 = new Date(year, 0, 1);
      const after = d => Math.max(0, Math.min(d, dec31) - Math.max(today, jan1 - 1)) / 86400000;
      const daysLeft = today.getFullYear() > year ? 0 : (dec31 - (today < jan1 ? new Date(jan1 - 86400000) : today)) / 86400000;
      const bars = s.by_month.map(m => {
        const mEnd = new Date(year, m.month, 0);
        const share = daysLeft > 0 ? after(mEnd) - after(new Date(year, m.month - 1, 0)) : 0;
        return { month: m.month, real: m.gross_eur, paid: m.paid_out_eur || 0, hours: m.hours, plan: share > 0 ? planned * share / daysLeft : 0 };
      });
      const split = this.flSplitOn();  // paid out solid, estimated lighter; without payouts one bar as always
      const max = Math.max(1, ...bars.map(b => b.real + b.plan));
      const bw = (W - PADL - PADR) / 12;
      const Y = v => PADT + (H - PADT - PADB) * (1 - v / max);
      const f = n => n.toFixed(1);
      let out = '';
      const M = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];
      bars.forEach((b, i) => {
        const x = PADL + i * bw + bw * 0.18, w = bw * 0.64;
        const isNow = today.getFullYear() === year && today.getMonth() === i;
        const paid = split ? Math.min(b.paid, b.real) : b.real, est = b.real - paid;
        const tip = `${new Date(year, i, 1).toLocaleDateString('en-US', { month: 'long' })} · ${this.fmtHours(b.hours)} · ${this.fmtMoney(b.real)}${split ? ` · ${this.fmtMoney(paid)} paid out · ${this.fmtMoney(est)} estimated` : ''}`;
        if (paid > 0) out += `<rect class="flm-bar${split ? ' paid' : ''}${isNow ? ' now' : ''}" x="${f(x)}" y="${f(Y(paid))}" width="${f(w)}" height="${f(Y(0) - Y(paid))}" rx="2" style="--i:${i}"><title>${tip}</title></rect>`;
        if (est > 0.005) out += `<rect class="flm-est${isNow ? ' now' : ''}" x="${f(x)}" y="${f(Y(b.real))}" width="${f(w)}" height="${f(Y(paid) - Y(b.real))}" rx="2" style="--i:${i}"><title>${tip}</title></rect>`;
        if (b.plan > 0.5) out += `<rect class="flm-plan" x="${f(x)}" y="${f(Y(b.real + b.plan))}" width="${f(w)}" height="${f(Y(0) - Y(b.plan))}" rx="2" style="--i:${i}"><title>planned · ${this.fmtMoney(b.plan)}</title></rect>`;
        if (b.real > 0) out += `<text class="flm-val" x="${f(x + w / 2)}" y="${f(Y(b.real + b.plan) - 4)}">${this.fmtMoney0(b.real)}</text>`;
        out += `<text class="flm-lbl${isNow ? ' now' : ''}" x="${f(x + w / 2)}" y="${H - 6}">${M[i]}</text>`;
      });
      out += `<line class="flm-axis" x1="${PADL}" x2="${W - PADR}" y1="${f(Y(0))}" y2="${f(Y(0))}"/>`;
      return `<svg class="flm" viewBox="0 0 ${W} ${H}" aria-hidden="true">${out}</svg>`;
    },
    flQuarterLabel(q) {
      const f = iso => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { day: 'numeric', month: 'short' });
      return `${f(q.from)} – ${f(q.to)}`;
    },
    flDeadlineLabel(q) {
      return new Date(q.deadline + 'T12:00:00').toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
    },
    flQuarterStatus(q) {
      return { paid: 'filed', due: 'due now', current: 'running', future: 'ahead' }[q.status] || q.status;
    },
    fl130Total() { return this.flSummary ? Math.round(this.flSummary.quarters.reduce((s, q) => s + q.payment, 0) * 100) / 100 : 0; },
    // The projection's two inputs live in the config; editing them here saves them.
    async flSaveProjection() {
      const body = { freelance_hours_per_week: Number(this.settingsForm.freelance_hours_per_week) || 0, freelance_days_off: Number(this.settingsForm.freelance_days_off) || 0 };
      try {
        await this.api('PUT', '/api/config', body);
        if (this._settingsSaved) Object.assign(this._settingsSaved, body);
        await this.loadFlSummary();
      } catch (e) { this.error = e.message; }
    },

    // The two shortcuts between the Calculator and the Freelance options: change an input,
    // then see what it does to a rate, a day, a year — and back.
    openFreelanceOptions(section = 'taxes') {
      this.setSettingsGroup('freelance', section);
      this.go('settings');
    },
    async openCalculator() {
      this.settingsFlush();
      await this._queued('config', () => {});  // let a pending save land first
      await this._queued('taxes', () => {});
      this.flYear = new Date().getFullYear();
      this._flStale = true;
      await this.go('freelance');  // loads the year's summary afresh
      this.calcFromYear();  // the calculator starts from the inputs just changed
      this.$nextTick(() => document.getElementById('fl-calc')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    },

    // =====================================================================
    // freelance — the calculator (the API does the maths; the page shows it)
    // =====================================================================
    // Start from this year's real values: the realised rate, the hours per billed day, the
    // year's tax inputs, the default source's currency.
    calcFromYear(run = true) {
      const s = this.flSummary;
      const src = this.defaultSource();
      const t = s?.tax_inputs || {};
      const days = new Set(this.blocks.filter(b => b.date.startsWith(String(this.flYear))).map(b => b.date)).size;
      const hours = s?.total.hours || 0;
      const perDay = days ? Math.max(0.25, Math.round(hours / days * 4) / 4) : 8;
      const currency = src?.currency || 'EUR';
      let hourly = s && s.total.eur_per_hour > 0 ? s.total.eur_per_hour : (src?.hourly_rate || 60);
      if (currency === 'USD' && s && s.total.eur_per_hour > 0 && this.calc.fx_rate) hourly = Math.round(hourly * Number(this.calc.fx_rate) * 100) / 100;
      else if (currency === 'USD' && src) hourly = src.hourly_rate;
      Object.assign(this.calc, {
        mode: 'hourly', hourly, daily: '', net: '', currency, hours_per_day: perDay,
        salary_annual: t.salary_annual ?? 0, gestoria_annual: t.gestoria_annual ?? 0, other_expenses: t.other_expenses ?? 0,
        tarifa_plana: !!t.tarifa_plana, inicio_actividad: !!t.inicio_actividad,
      });
      if (this.calc.billable_mode === 'calendar') this.calc.billable_days = this.calcCalendarDays();
      if (run) this.calcRun('hourly', true);
      else if (currency === 'USD') this.calcSetCurrency('USD'); else this.calcRun('hourly', true);
    },
    // "The calendar's": the year's work-week days less the holidays logged and the vacation budget.
    calcCalendarDays() {
      const y = this.flYear;
      const week = this._planWorkWeek();
      let n = 0;
      for (let d = new Date(y, 0, 1); d.getFullYear() === y; d.setDate(d.getDate() + 1)) if (week.has((d.getDay() + 6) % 7)) n++;
      const holidays = this.entries.filter(e => e.date.startsWith(String(y)) && e.day_type === 'holiday').reduce((s, e) => s + e.fraction, 0);
      const budget = this.dashboard?.vacation_budget_days ?? this.settingsForm.vacation_budget_days ?? 0;
      return Math.max(1, Math.round(n - holidays - budget));
    },
    calcSetBillable(mode) {
      this.calc.billable_mode = mode;
      this.calc.billable_days = mode === 'calendar' ? this.calcCalendarDays() : 220;
      this.calcRun(this.calc.mode, true);
    },
    async calcSetCurrency(c) {
      this.calc.currency = c;
      if (c === 'USD') {
        const fx = await this.loadFx();
        if (fx.available) { this.calc.fx_rate = fx.usd_per_eur; this.calc.fx_source = `ECB ${fx.date}${fx.stale ? ' (stale)' : ''}`; }
        else if (!this.calc.fx_rate) {
          // no ECB: the rate the last dollar block was saved with, else nothing to compute with
          const last = [...this.blocks].filter(b => b.currency === 'USD' && b.fx_rate).sort((a, b) => (a.date < b.date ? 1 : -1))[0];
          if (last) { this.calc.fx_rate = last.fx_rate; this.calc.fx_source = `last dollar block's, ${last.date}`; }
          else this.calc.fx_source = 'no ECB rate — type one';
        }
      }
      this.calcRun(this.calc.mode, true);
    },
    calcFxTyped() { this.calc.fx_source = 'typed by hand'; this.calcRun(this.calc.mode); },
    // The money fields show the same grouping as the results ("28.960,03") until one gets focus, and
    // then the number as typed. They take "28960,03", "28960.03" and "28.960,03" alike, and a dot
    // before exactly three digits is a thousands mark: "55.000" is fifty-five thousand.
    calcShow(key) {
      if (this.calcEdit === key) return this.calcDraft;
      const v = this.calc[key];
      if (v === '' || v === null || v === undefined || isNaN(Number(v))) return '';
      return new Intl.NumberFormat('es-ES', { minimumFractionDigits: 0, maximumFractionDigits: 2, useGrouping: 'always' }).format(Number(v));
    },
    calcFocus(key, el) {
      const v = this.calc[key];
      this.calcDraft = (v === '' || v === null || v === undefined || isNaN(Number(v))) ? '' : String(Number(v)).replace('.', ',');
      this.calcEdit = key;
      // swap the grouped text for the plain number right now (not on Alpine's next paint), and
      // select it, so typing replaces it as it did in a number field
      if (el) { el.value = this.calcDraft; el.select(); }
    },
    calcBlur() { this.calcEdit = null; },
    calcTyped(key, text, mode) {
      this.calcDraft = text;
      const t = text.trim().replace(/\s/g, '');
      const n = t.includes(',') || /^\d{1,3}(\.\d{3})+$/.test(t) ? t.replace(/\./g, '').replace(',', '.') : t;
      if (n === '') this.calc[key] = '';
      else if (!isNaN(Number(n))) this.calc[key] = Number(n);
      this.calcRun(mode || this.calc.mode);
    },
    // One of the three fields changed: it drives the other two. Debounced; the last answer
    // wins even if an earlier request lands later.
    calcRun(mode, now = false) {
      this.calc.mode = mode;
      clearTimeout(this._calcTimer);
      const go = async () => {
        const c = this.calc;
        const value = Number(c[mode]);
        if (!(value >= 0) || (c.currency === 'USD' && !(Number(c.fx_rate) > 0))) return;
        const body = { year: this.flYear, mode, value, currency: c.currency, fx_rate: c.currency === 'USD' ? Number(c.fx_rate) : null,
          billable_days: Number(c.billable_days) || 0, hours_per_day: Number(c.hours_per_day) || 8,
          salary_annual: Number(c.salary_annual) || 0, gestoria_annual: Number(c.gestoria_annual) || 0, other_expenses: Number(c.other_expenses) || 0,
          tarifa_plana: !!c.tarifa_plana, inicio_actividad: !!c.inicio_actividad };
        const seq = ++c._seq;
        c.busy = true;
        try {
          const r = await this.api('POST', '/api/freelance/calc', body);
          if (seq !== c._seq) return;
          c.result = r;
          if (mode !== 'hourly') c.hourly = r.hourly;
          if (mode !== 'daily') c.daily = r.daily;
          if (mode !== 'net') c.net = r.net;
          c.linked = mode; setTimeout(() => { if (c.linked === mode) c.linked = null; }, 700);
        } catch (e) { if (seq === c._seq) this.error = e.message; }
        finally { if (seq === c._seq) c.busy = false; }
      };
      if (now) go(); else this._calcTimer = setTimeout(go, 250);
    },
    // Gross → expenses → RETA → IRPF → net, as shares of the gross for the waterfall bar.
    calcWaterfall() { return this.waterfall(this.calc.result?.figures); },
    waterfall(f) {
      if (!f || f.gross <= 0) return [];
      const parts = [
        { id: 'expenses', label: 'expenses', value: f.expenses },
        { id: 'reta', label: 'RETA', value: f.reta_annual },
        { id: 'irpf', label: 'IRPF', value: Math.max(0, f.irpf) },
        { id: 'net', label: 'net', value: Math.max(0, f.net) },
      ];
      const total = parts.reduce((s, p) => s + p.value, 0) || 1;
      let left = 0;
      return parts.map(p => { const w = p.value / total * 100; const o = { ...p, pct: Math.round(w * 10) / 10, left: Math.round(left * 10) / 10 }; left += w; return o; });
    },
    calcQuarterly() { const f = this.calc.result?.figures; return f ? Math.round(f.pago_fraccionado / 4 * 100) / 100 : 0; },

    // =====================================================================
    // freelance — analytics
    // =====================================================================
    hmMode: 'employee',
    // Freelance hours of a day on the heatmap: four shades of brass.
    flLevelCls(hours) { return hours <= 0 ? 'hm-empty' : hours < 1 ? 'hm-fl hm-fl-1' : hours < 2 ? 'hm-fl hm-fl-2' : hours < 4 ? 'hm-fl hm-fl-3' : 'hm-fl hm-fl-4'; },
    anFlVisible() {
      const { x0, x1 } = this.an;
      return this.blocks.filter(b => { const t = this._ms(b.date); return t >= x0 && t < x1; });
    },
    anFlSummary() {
      if (!this.hasFreelance()) return null;
      const vis = this.anFlVisible();
      const hours = this.blockHours(vis), lines = this.flLines(vis, this.anFlRange()), eur = this.lineEur(lines);
      const netShare = this.flSummary?.projection?.figures?.net_share ?? null;
      return { hours, eur, ...this.lineSplit(lines), blocks: vis.length, rate: hours ? Math.round(eur / hours * 100) / 100 : 0,
        netRate: hours && netShare !== null ? Math.round(eur / hours * netShare * 100) / 100 : null, year: this.flSummary?.year };
    },
    // The visible span (x1 is exclusive) as dates, for the payouts of weeks with no blocks.
    anFlRange() {
      const { x0, x1 } = this.an;
      return { from: this._dateIso(new Date(x0)), to: this._dateIso(new Date(x1 - 86400000)) };
    },
    anFlMonths(vis) {
      const m = {};
      for (const l of this.flLines(vis, this.anFlRange())) { const k = l.date.slice(0, 7); const row = (m[k] ||= { key: k, eur: 0, minutes: 0 }); row.eur += l.eur || 0; row.minutes += l.minutes; }
      return Object.values(m).map(r => ({ ...r, eur: this._r2(r.eur), hours: this._r2(r.minutes / 60) }));
    },

    // =====================================================================
    // W6 — easter egg + streaks
    // =====================================================================
    computeStreaks() {
      const sorted = [...this.entries].sort((a, b) => (a.date < b.date ? -1 : 1));
      let longestSurplus = 0, longestDeficit = 0, curS = 0, curD = 0, mostBreaks = 0;
      let longestPositiveStreak = 0, curPositive = 0, running = 0;
      for (const e of sorted) {
        if (e.surplus_hours > 0.01)       { curS++; curD = 0; }
        else if (e.surplus_hours < -0.01) { curD++; curS = 0; }
        else                               { curS = 0; curD = 0; }
        longestSurplus = Math.max(longestSurplus, curS);
        longestDeficit = Math.max(longestDeficit, curD);
        mostBreaks = Math.max(mostBreaks, (e.breaks || []).length);
        running = Math.round((running + e.surplus_hours) * 100) / 100;
        if (running > 0.01) { curPositive++; } else { curPositive = 0; }
        longestPositiveStreak = Math.max(longestPositiveStreak, curPositive);
      }
      return { longestSurplus, longestDeficit, mostBreaks, longestPositiveStreak };
    },

    triggerEasterEgg() {
      this.streaks = this.computeStreaks();
      this.streaksUnlocked = true;
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.eggAnimating = true;
        setTimeout(() => { this.eggAnimating = false; }, 1300);
        this._bzFx(document.querySelector('.brand-logo'), 'logo-wind', 1200);
      }
      this.$nextTick(() => {
        const panel = document.querySelector('.streaks-panel');
        if (panel && !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
          panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    },
  };
}
