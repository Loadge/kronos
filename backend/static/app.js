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
    pdfModal: { open: false, preset: 'this_month', from: '', to: '', detail: 'full', hours: 'dec', theme: 'light', notes: false, sign: false },

    // ---------- days list -----------------------------------------------
    entries: [],
    sortKey: 'date',
    sortDir: 'desc',
    daysYear: String(new Date().getFullYear()),
    notesQuery: '',
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

    // ---------- settings ------------------------------------------------
    settingsForm: { daily_target_hours: 8, cumulative_start_date: '', reset_annually: false, work_week_days: [0,1,2,3,4], vacation_budget_days: 0, default_start_time: '09:00', default_end_time: '17:00', holiday_country: '', holiday_region: '', daily_target_schedule: [], profile_name: '', profile_employer: '', profile_extra: '' },
    _scheduleKeySeq: 0,  // stable keys for the date-effective target rows
    _settingsSaved: null,  // the form as last loaded / saved, for the per-section dirty flags
    // Settings is one long page with a section index; each section saves its own fields.
    SETTINGS_SECTIONS: [
      { id: 'work',      label: 'Work',      fields: ['daily_target_hours', 'default_start_time', 'default_end_time', 'work_week_days', 'cumulative_start_date', 'reset_annually'] },
      { id: 'leave',     label: 'Leave',     fields: ['vacation_budget_days'] },
      { id: 'holidays',  label: 'Holidays',  fields: [] },
      { id: 'profile',   label: 'Profile',   fields: ['profile_name', 'profile_employer', 'profile_extra'] },
      { id: 'templates', label: 'Templates', fields: [] },
      { id: 'data',      label: 'Data',      fields: [] },
    ],
    settingsActive: 'work',
    _settingsSpy: null,

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

    // ---------- W1 animated metrics (tick-up) ---------------------------
    animWeek: 0, animMonth: 0, animCumulative: 0,

    // ---------- W5 save ribbon ------------------------------------------
    toast: { msg: '', kind: 'neutral', show: false },
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

      const TABS = ['dashboard', 'plan', 'log', 'days', 'analytics', 'settings'];
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
          if (this.tab === 'log' && this.editingDate) { this.openNewEntry(); return; }
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

      this.weekStart = this._mondayIso(new Date());
      this.loadSettings(); // pre-load so logPreview() has accurate target hours
      this.loadTemplates();
      this.openNewEntry();
      await this.go(this.tab);
    },

    // =====================================================================
    // nav
    // =====================================================================
    async go(t) {
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
      else if (t === 'settings') { await this.loadSettings(); this.loadHolidayData(); }
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
      // time; dark is a per-report decision.
      const saved = JSON.parse(localStorage.getItem('k-pdf-options') || '{}');
      this.pdfModal = { ...this.pdfModal, ...saved, theme: 'light', open: true };
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
      const q = new URLSearchParams({ from, to, detail: o.detail, hours: o.hours, theme: o.theme });
      if (o.notes) q.set('notes', '1');
      if (o.sign) q.set('sign', '1');
      return `/timesheet?${q}`;
    },
    openTimesheet() {
      const o = this.pdfModal;
      if (o.preset === 'custom' && (!o.from || !o.to || o.to < o.from)) { this.showToast('Pick a valid date range', 'deficit'); return; }
      const { open, ...remember } = o;
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

    // ── year strip: twelve mini months, click one to work on it ──────────
    planYearStrip() {
      const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const entryMap = {};
      for (const e of this.entries) if (e.date.startsWith(String(this.planYear))) entryMap[e.date] = e;
      const drafts = this.draftMap();
      const todayStr = this.todayIso();
      const out = [];
      for (let mo = 0; mo < 12; mo++) {
        const offset = (new Date(this.planYear, mo, 1).getDay() + 6) % 7;
        const days = new Date(this.planYear, mo + 1, 0).getDate();
        const cells = [];
        for (let i = 0; i < offset; i++) cells.push({ key: `p${i}`, pad: true });
        for (let d = 1; d <= days; d++) {
          const iso = `${this.planYear}-${String(mo + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
          const entry = entryMap[iso] || null;
          const dow = (offset + d - 1) % 7;
          cells.push({ key: iso, pad: false,
            cls: this.dayCellCls(entry, drafts[iso]) + (dow >= 5 ? ' hm-weekend' : '') + (iso === todayStr ? ' hm-today' : ''),
            style: this.entryCellStyle(entry) });
        }
        out.push({ mo, label: MONTHS[mo], cells, active: mo === this.planMonth });
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
        const [dashboard, series, yoy] = await Promise.all([
          this.api('GET', '/api/dashboard'),
          this.api('GET', `/api/analytics/cumulative-series?year=${year}`),
          this.api('GET', '/api/analytics/yoy').catch(() => null),
        ]);
        await this.loadDays();   // entries + drafts: the week strip and quick-log read them
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
      this.loadStreaks();
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
    openNewEntry() {
      this.editingDate = null;
      const now = new Date();
      this.calYear = now.getFullYear();
      this.calMonth = now.getMonth();
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
          isToday: dateStr === todayStr, isSelected: dateStr === selectedStr });
      }
      return cells;
    },

    calPrev() {
      if (this.calMonth === 0) { this.calMonth = 11; this.calYear--; }
      else this.calMonth--;
    },

    calNext() {
      if (this.calMonth === 11) { this.calMonth = 0; this.calYear++; }
      else this.calMonth++;
    },

    async calSelectDay(dateStr) {
      this.form.date = dateStr;
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
        days.push({
          iso, label: DOW[i], dayNum: d.getDate(), entry, draft, barHours, target,
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

      // Navigate immediately — don't await loadDays (would clobber optimistic row)
      this.tab = 'days';
      this.error = null;
      if (location.hash.replace('#', '') !== 'days') location.hash = 'days';

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

        this.openNewEntry();
      } catch (e) {
        // Revert optimistic change and return the user to the log form
        this.entries = prevEntries;
        this.error = e.message;
        this.tab = 'log';
        if (location.hash.replace('#', '') !== 'log') location.hash = 'log';
      } finally {
        this.saving = false;
      }
    },

    async deleteEntry(dateIso) {
      if (!confirm(`Delete the entry for ${dateIso}?`)) return;
      try {
        await this.api('DELETE', `/api/entries/${dateIso}`);
        this.openNewEntry();
        await this.loadDashboard();
        this.go('days');
      } catch (e) { this.error = e.message; }
    },

    // =====================================================================
    // days list
    // =====================================================================
    async loadDays() {
      this.loading.days = true;
      try {
        const [entries, plans] = await Promise.all([this.api('GET', '/api/entries'), this.api('GET', '/api/plans')]);
        this.entries = entries;
        this.plans = plans;
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
      const totals = {};
      for (const e of entries) {
        const ym = e.date.slice(0, 7);
        const m = (totals[ym] ||= { count: 0, net: 0, target: 0, surplus: 0 });
        m.count++; m.net += e.net_hours; m.target += e.target_hours; m.surplus += e.surplus_hours;
      }
      const rows = [];
      let current = null;
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
        rows.push({ kind: 'entry', key: e.date, e });
      }
      return rows;
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
      let lo = 0, hi = 0, series = [], s = '';
      if (this.an.mode === 'balance') {
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
        lo = 0; hi = Math.max(target, ...vis.map(e => e.net_hours + (e.leave_hours || 0)));
      } else {
        lo = 0; hi = Math.max(1, ...this.anMonths(vis).map(m => Math.max(m.net, m.target)));
      }
      const span = Math.max(hi - lo, 2); lo -= span * 0.08; hi += span * 0.08;
      const Y = v => PADT + (H - PADT - PADB) * (1 - (v - lo) / (hi - lo));
      const rawStep = (hi - lo) / 5;
      const step = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500].find(v => v >= rawStep) || 1000;
      for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
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
        for (const e of vis) {
          const t = this._ms(e.date), h = e.net_hours + (e.leave_hours || 0);
          const style = this.entryCellStyle(e);
          s += `<rect class="an-bar ${this.entryCellCls(e)}" x="${f(X(t + DAY / 2) - bw / 2)}" width="${f(bw)}" y="${f(Y(h))}" height="${f(Math.max(0, Y(0) - Y(h)))}"${style ? ` style="${style.replace(/"/g, "'")}"` : ''}><title>${e.date} · ${this.pillLabel(e)} · ${e.net_hours}h · ${this.formatSurplus(e.surplus_hours)}</title></rect>`;
        }
        s += `<line class="an-target" x1="${PADL}" x2="${W - PADR}" y1="${f(Y(target))}" y2="${f(Y(target))}"/>`;
      } else {
        for (const m of this.anMonths(vis)) {
          const [y, mo] = m.key.split('-').map(Number);
          const t0 = Math.max(this.an.x0, +new Date(y, mo - 1, 1)), t1 = Math.min(this.an.x1, +new Date(y, mo, 1));
          const x0 = X(t0) + 3, x1 = X(t1) - 3;
          s += `<rect class="an-bar hm-${this.surplusClass(m.surplus)}" x="${f(x0)}" width="${f(Math.max(1, x1 - x0))}" y="${f(Y(m.net))}" height="${f(Math.max(0, Y(0) - Y(m.net)))}"><title>${m.key} · ${m.net}h / ${m.target}h · ${this.formatSurplus(m.surplus)}</title></rect>`;
          s += `<line class="an-target" x1="${f(x0)}" x2="${f(x1)}" y1="${f(Y(m.target))}" y2="${f(Y(m.target))}"/>`;
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
      const sum = this.anSummary();
      const aria = `${this.anRangeLabel()}: ${sum ? this.formatSurplus(sum.surplus) + ' over ' + sum.net + 'h worked' : 'nothing logged'}.`;
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
      if (!this.entries.length) return null;
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

      // Day cells
      for (const day of rawDays) {
        const entry = map[day.iso];
        const draft = entry ? null : drafts[day.iso];
        const cls = this.dayCellCls(entry, draft);
        const style = this.entryCellStyle(entry);
        const sign = entry && entry.surplus_hours > 0 ? '+' : '';
        const title = entry ? `${day.iso} · ${this.pillLabel(entry)} · ${sign}${entry.surplus_hours}h`
          : draft ? `${day.iso} · ${draft.day_type} · planned` : day.iso;
        const today = day.iso === this.todayIso();
        cells.push({ key: day.iso, type: 'day', date: day.iso, row: day.row + 1, col: monthStartCol[day.month] + day.week, cls, style, title, weekend: day.row >= 5, today });
      }

      // Build CSS grid-template-columns string
      const parts = [];
      for (let fc = 1; fc <= totalFinalCols; fc++) {
        parts.push(finalColIsGap[fc] ? '5px' : '13px');
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

    // Save one section's fields (its button), or every dirty field (Ctrl+Enter).
    async saveSettings(section) {
      const sections = section ? this.SETTINGS_SECTIONS.filter(s => s.id === section) : this.SETTINGS_SECTIONS;
      const body = {};
      for (const s of sections) for (const k of s.fields) body[k] = this.settingsForm[k];
      try {
        await this.api('PUT', '/api/config', body);
        for (const k of Object.keys(body)) this._settingsSaved[k] = JSON.parse(JSON.stringify(body[k]));
        this.showToast('Settings saved', 'neutral');
        this.loadDashboard();  // the target or the start date may have moved every number
      } catch (e) { this.error = e.message; }
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
      this.settingsActive = id;
      document.getElementById('settings-' + id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    },
    async saveDailyTargetSchedule() {
      const rows = (this.settingsForm.daily_target_schedule || []).map(r => ({
        effective_from: r.effective_from,
        hours: Number(r.hours),
      }));
      if (!rows.length) { this.error = 'Add at least one target row.'; return; }
      try {
        await this.api('PUT', '/api/config/daily-target-schedule', { rows });
        await this.loadSettings();   // server sorts/dedupes; refresh the current-target field too
        await this.loadDashboard();  // cumulative/surplus numbers may shift
        this.showToast('Target timeline saved', 'neutral');
      } catch (e) { this.error = e.message; }
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
      this.anSeries = null;
    },

    // =====================================================================
    // W5 — save ribbon
    // =====================================================================
    showToast(msg, kind) {
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this.toast = { msg, kind: kind || 'neutral', show: false };
      this.$nextTick(() => {
        this.toast.show = true;
        const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 1200 : 1800;
        this._toastTimer = setTimeout(() => { this.toast.show = false; }, delay);
      });
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
