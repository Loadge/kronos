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

function app() {
  return {
    // ---------- nav + global state ---------------------------------------
    tab: 'dashboard',
    subtitle: '',
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
      { id: 'general',   label: 'General' },
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
    daysWeekOpen: {},     // Days > Freelance: week key (its Monday) -> opened by hand; unset = open only the current week
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
    taxYear: new Date().getFullYear(),
    taxForm: null,        // Settings → Taxes: the year's inputs as loaded
    _taxSaved: null,
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
    animWeek: 0, animMonth: 0, animCumulative: 0,

    // ---------- W5 save ribbon ------------------------------------------
    toast: { msg: '', kind: 'neutral', show: false, action: null },
    _toastTimer: null,

    // ---------- W6 easter egg + streaks ---------------------------------
    streaksUnlocked: false,
    streaks: null,
    eggAnimating: false,

    // ---------- bulk log modal ------------------------------------------
    bulkModal: { open: false, year: new Date().getFullYear(), month: new Date().getMonth(), selected: [], _dragging: false, _dragAnchor: null, _dragCurrent: null, submitting: false },

    // ---------- theme ---------------------------------------------------
    theme: localStorage.getItem('k-theme') || 'dark',

    // ---------- command palette -----------------------------------------
    palette: { open: false, query: '', selected: 0 },

    // =====================================================================
    // init
    // =====================================================================
    async init() {
      // Apply persisted theme before first render
      document.documentElement.setAttribute('data-theme', this.theme);

      const TABS = ['dashboard', 'plan', 'log', 'days', 'analytics', 'freelance', 'settings'];
      const hash = location.hash.replace('#', '');
      if (TABS.includes(hash)) this.tab = hash;

      window.addEventListener('hashchange', () => {
        const t = location.hash.replace('#', '');
        if (TABS.includes(t) && t !== this.tab) this.go(t);
      });

      // Keyboard shortcuts
      let _keyBuf = '';
      document.addEventListener('keydown', (e) => {
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

    // Roving-tabindex arrow navigation for the tab list (E3)
    focusTab(dir, el) {
      const tabs = [...el.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];
      const next = tabs[(tabs.indexOf(el) + dir + tabs.length) % tabs.length];
      next.focus();
      next.click();
    },

    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', this.theme);
      localStorage.setItem('k-theme', this.theme);
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
      if (cmd.id === 'calc') { await this.go('freelance'); this.$nextTick(() => document.getElementById('fl-calc')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); return; }
      this.go(cmd.id);
    },

    paletteConfirm() {
      const cmds = this.filteredCommands();
      if (cmds.length) this.paletteRun(cmds[this.palette.selected] ?? cmds[0]);
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

    todayIso() { return new Date().toISOString().slice(0, 10); },

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
        const h = dashboard.cumulative.surplus_hours;
        const abs = Math.abs(h).toFixed(2);
        if (h > 0.01) this.subtitle = `${abs}h ahead overall`;
        else if (h < -0.01) this.subtitle = `${abs}h behind overall`;
        else this.subtitle = 'on target';
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

    // W1 — animate the three metric values from 0 → real (ease-out cubic, 600ms)
    tickUpDashboard() {
      if (!this.dashboard) return;
      const targets = {
        week:       Math.abs(this.dashboard.week.surplus_hours),
        month:      Math.abs(this.dashboard.month.surplus_hours),
        cumulative: Math.abs(this.dashboard.cumulative.surplus_hours),
      };
      // Unchanged numbers (a background refresh) or a dashboard that isn't showing: no show.
      const settled = this.animWeek === targets.week && this.animMonth === targets.month && this.animCumulative === targets.cumulative;
      if (settled || this.tab !== 'dashboard' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.animWeek = targets.week; this.animMonth = targets.month; this.animCumulative = targets.cumulative;
        return;
      }
      this.animWeek = 0; this.animMonth = 0; this.animCumulative = 0;
      const start = performance.now();
      const token = (this._tickToken = (this._tickToken || 0) + 1);
      const tick = (now) => {
        if (token !== this._tickToken) return;  // a newer animation took over
        const t = Math.min(1, (now - start) / 600);
        const e = 1 - Math.pow(1 - t, 3); // ease-out cubic
        this.animWeek       = targets.week       * e;
        this.animMonth      = targets.month      * e;
        this.animCumulative = targets.cumulative * e;
        if (t < 1) requestAnimationFrame(tick);
        else { this.animWeek = targets.week; this.animMonth = targets.month; this.animCumulative = targets.cumulative; }
      };
      requestAnimationFrame(tick);
    },

    // =====================================================================
    // log form
    // =====================================================================
    // `keepMonth`: the calendar stays where it was (the ← after editing a day, Escape), so
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
      const res = await fetch(`/api/entries/${dateStr}`, {
        headers: { Accept: 'application/json' },
      });
      if (res.status === 404) return;
      if (!res.ok) { this.error = `${res.status} ${res.statusText}`; return; }
      this.editEntry(await res.json());
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
      this.daysYear = this._daysYearFor(mine);
      await this.go('days');
      // The Days tab scrolls to today once it has rendered; this scroll has to come after it.
      this.$nextTick(() => setTimeout(() => this._scrollToWeek(monday, 0), 350));
    },
    _scrollToWeek(monday, tries) {
      const el = document.getElementById('eweek-' + monday);
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
      this.form.date = dateStr;
      this.notesOpen = false;
      await this.probeDate(dateStr);
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
          const dow = new Date(saved.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long' });
          this.showToast(`Saved — ${dow} is ${this.formatSurplus(saved.surplus_hours)}`, this.surplusClass(saved.surplus_hours));
        }

        this.openNewEntry({ keepMonth: true });
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
      const today = new Date().toISOString().slice(0, 10);
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
    // month while sorted by date — under a net-hours sort a month boundary means nothing.
    daysRows() {
      const entries = this.sortedEntries();
      if (this.sortKey !== 'date') return entries.map(e => ({ kind: 'entry', key: e.date, e }));
      const totals = {}, weeks = {}, mondayOf = {};
      for (const e of entries) {
        const ym = e.date.slice(0, 7);
        const m = (totals[ym] ||= { count: 0, net: 0, target: 0, surplus: 0 });
        m.count++; m.net += e.net_hours; m.target += e.target_hours; m.surplus += e.surplus_hours;
        const monday = (mondayOf[e.date] = this._mondayIso(new Date(e.date + 'T12:00:00')));
        const w = (weeks[monday] ||= { count: 0, net: 0, target: 0, surplus: 0 });
        w.count++; w.net += e.net_hours; w.target += e.target_hours; w.surplus += e.surplus_hours;
      }
      const rows = [];
      let current = null, currentWeek = null;
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
          const w = weeks[monday];
          rows.push({
            kind: 'wk', key: 'wk-' + monday, week: monday,
            id: this.weekId(monday), range: this._weekRange(monday),
            count: w.count,
            net: Math.round(w.net * 100) / 100,
            target: Math.round(w.target * 100) / 100,
            surplus: Math.round(w.surplus * 100) / 100,
          });
        }
        rows.push({ kind: 'entry', key: e.date, e, week: monday });
      }
      return rows;
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
    daysWeekIsOpen(key) {
      return key in this.daysWeekOpen ? this.daysWeekOpen[key] : key === this._mondayIso(new Date());
    },
    daysWeekToggle(key) { this.daysWeekOpen = { ...this.daysWeekOpen, [key]: !this.daysWeekIsOpen(key) }; },
    daysWeeksSetAll(open) {
      const next = {};
      for (const w of this.daysWeeks()) next[w.key] = open;
      this.daysWeekOpen = next;
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
          const gap = p && p.minutes > 0 ? this._r2(p.amount - p.estimate_amount) : null;
          lines.push({ key: s.id, source: s, currency: s.currency, hours: this._r2(minutes / 60), estimate, payout: p,
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
    // week is one line, its source lines (when open) and then its block rows.
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
        w.blocks.forEach((b, i) => rows.push({ kind: 'block', key: 'b-' + b.id, b, last: i === w.blocks.length - 1, dow: DOW[new Date(b.date + 'T12:00:00').getDay()] }));
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
      const drop = () => { const d = { ...this.payDraft }; delete d[k]; this.payDraft = d; };
      if (text === '') {
        if (!existing) { drop(); this._setStatus(st, ''); return; }
        this._setStatus(st, 'busy');
        try {
          await this.api('DELETE', `/api/freelance/payouts/${existing.id}`);
          drop();
          await this.reloadFlData();
          this._setStatus(st, 'saved');
          const src = this.sourceById(sourceId);
          this.showToast(`Payout deleted — ${this.weekId(weekStart)} ${src ? src.name : ''}`.trim(), 'neutral', {
            label: 'Undo',
            run: async () => {
              const body = { source_id: existing.source_id, week_start: existing.week_start, amount: existing.amount, note: existing.note };
              if (existing.fx_rate) body.fx_rate = existing.fx_rate;
              try { await this.api('POST', '/api/freelance/payouts', body); await this.reloadFlData(); this.showToast('Payout restored', 'neutral'); }
              catch (e) { this.error = e.message; }
            },
          });
        } catch (e) { this.error = e.message; this._setStatus(st, 'error'); }
        return;
      }
      const amount = Number(text.replace(/[,\s]/g, ''));
      if (!(amount > 0)) { this._setStatus(st, 'invalid'); return; }
      if (existing && existing.amount === amount) { drop(); this._setStatus(st, ''); return; }
      this._setStatus(st, 'busy');
      try {
        if (existing) await this.api('PUT', `/api/freelance/payouts/${existing.id}`, { source_id: sourceId, week_start: weekStart, amount, note: existing.note });
        else await this.api('POST', '/api/freelance/payouts', { source_id: sourceId, week_start: weekStart, amount });
        drop();
        await this.reloadFlData();
        this._setStatus(st, 'saved');
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
      const today = new Date().toISOString().slice(0, 10);
      const source = this.daysYear === 'all'
        ? this.entries
        : this.entries.filter(e => e.date.startsWith(this.daysYear));
      const anchorDate = source.filter(e => e.date <= today).map(e => e.date).sort().slice(-1)[0] ?? null;
      if (!anchorDate) return;
      const el = document.getElementById('day-row-' + anchorDate);
      if (!el) return;
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
    showToast(msg, kind, action = null) {
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this.toast = { msg, kind: kind || 'neutral', show: false, action };
      this.$nextTick(() => {
        this.toast.show = true;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const delay = action ? 5000 : reduced ? 1200 : 1800;
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
      try { this.sources = await this.api('GET', '/api/freelance/sources'); } catch { /* keep what we had */ }
      if (this.flForm.source_id == null || !this.sourceById(this.flForm.source_id)) this.flForm.source_id = this.defaultSource()?.id ?? null;
    },

    // ---------- money --------------------------------------------------------
    fmtMoney(n, currency = 'EUR', digits = 2) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
    },
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
    flDayTotal() {
      const list = this.flDayBlocks();
      const lines = this.flLines(list, { from: this.form.date, to: this.form.date });
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
      this.$nextTick(() => this.tickUpFreelance());
    },
    async loadFlSummary(year = this.flYear) {
      try { this.flSummary = await this.api('GET', `/api/freelance/summary?year=${year}`); this._flStale = false; }
      catch (e) { this.error = e.message; }
    },
    setFlYear(y) { this.flYear = y; this.loadFlSummary(y).then(() => this.$nextTick(() => this.tickUpFreelance())); },
    flYears() {
      const ys = new Set(this.blocks.map(b => Number(b.date.slice(0, 4))));
      ys.add(new Date().getFullYear());
      return [...ys].sort((a, b) => b - a);
    },
    animFlGross: 0,
    tickUpFreelance() {
      const target = this.flSummary?.total.gross_eur ?? 0;
      if (this.animFlGross === target || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { this.animFlGross = target; return; }
      const from = 0, start = performance.now(), token = (this._flTick = (this._flTick || 0) + 1);
      const tick = now => {
        if (token !== this._flTick) return;
        const t = Math.min(1, (now - start) / 700), e = 1 - Math.pow(1 - t, 3);
        this.animFlGross = from + (target - from) * e;
        if (t < 1) requestAnimationFrame(tick); else this.animFlGross = target;
      };
      requestAnimationFrame(tick);
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
      }
      this.$nextTick(() => {
        const panel = document.querySelector('.streaks-panel');
        if (panel && !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
          panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    },
  };
}
