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

    // ---------- dashboard layout: draggable + persisted (redesign) -------
    dashboardLayout: {
      hero: ['week', 'month', 'cumulative'],
      tiles: ['yoy', 'logging_streak', 'on_target_streak'],
      aux: ['forecast', 'quick_log', 'vacation'],
    },
    _dashboardLayoutLoaded: false,
    _dashboardSortables: [],

    // ---------- log form ------------------------------------------------
    // leave_hours: hours of leave on a non-work day, null for work days.
    // Stored on the server as a fraction of that date's target (see formFraction()).
    form: { date: '', day_type: 'work', start_time: '09:00', end_time: '17:00', notes: '', breaks: [], leave_hours: null },
    editingDate: null,

    // ---------- log calendar --------------------------------------------
    calYear: new Date().getFullYear(),
    calMonth: new Date().getMonth(),

    // ---------- week view -----------------------------------------------
    weekStart: '', // ISO date of the Monday of the displayed week; set in init()

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
    monthly: [],
    yearly: [],
    yoy: null,
    records: null,
    analyticsYear: String(new Date().getFullYear()),

    // ---------- settings ------------------------------------------------
    settingsForm: { daily_target_hours: 8, cumulative_start_date: '', reset_annually: false, work_week_days: [0,1,2,3,4], vacation_budget_days: 0, default_start_time: '09:00', default_end_time: '17:00', holiday_country: '', holiday_region: '', daily_target_schedule: [], profile_name: '', profile_employer: '', profile_extra: '' },
    _scheduleKeySeq: 0,  // stable keys for the date-effective target rows

    // ---------- public holidays ------------------------------------------
    holidayCountries: [],
    holidaySubdivisions: [],
    holidayPreview: [],
    holidayYear: new Date().getFullYear(),
    holidayImporting: false,

    // ---------- day templates (server-side) -----------------------------
    templates: [],
    _tplName: '',

    // ---------- notes expansion (days table) ----------------------------
    notesExpanded: {},

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

      const TABS = ['dashboard', 'plan', 'week', 'log', 'days', 'analytics', 'settings'];
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

        // Escape — dismiss in priority order
        if (e.key === 'Escape') {
          if (this.palette.open)                    { this.closePalette(); return; }
          if (this.tab === 'log' && this.editingDate) { this.openNewEntry(); return; }
          if (this.tab === 'log')                   { this.go('dashboard'); return; }
          return;
        }

        // All remaining shortcuts fire only when focus is not inside a field
        if (inInput || e.ctrlKey || e.altKey || e.metaKey) return;

        switch (e.key) {
          case 'p': case 'P': e.preventDefault(); this.go('plan');      break;
          case 'w': case 'W': e.preventDefault(); this.go('week');      break;
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
      if (t === 'dashboard') { await this.loadDashboard(); this.$nextTick(() => this.initDashboardSortables()); }
      else if (t === 'plan') await this.loadPlan();
      else if (t === 'week') { this.ensureWeekStart(); await this.loadDays(); }
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
    toggleNotes(date) {
      this.notesExpanded = { ...this.notesExpanded, [date]: !this.notesExpanded[date] };
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
      { id: 'dashboard', label: 'Dashboard',     hint: '1'     },
      { id: 'plan',      label: 'Plan time off', hint: 'P'     },
      { id: 'week',      label: 'Week',          hint: 'W'     },
      { id: 'log',       label: 'Log new entry', hint: '2 · L' },
      { id: 'days',      label: 'Days',          hint: '3'     },
      { id: 'pdf',       label: 'PDF timesheet', hint: ''      },
      { id: 'analytics', label: 'Analytics',     hint: '4 · A' },
      { id: 'settings',  label: 'Settings',      hint: '5 · S' },
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
        this.dashboard = await this.api('GET', '/api/dashboard');
        const h = this.dashboard.cumulative.surplus_hours;
        const abs = Math.abs(h).toFixed(2);
        if (h > 0.01) this.subtitle = `${abs}h ahead overall`;
        else if (h < -0.01) this.subtitle = `${abs}h behind overall`;
        else this.subtitle = 'on target';
        this.$nextTick(() => this.tickUpDashboard()); // W1
      } catch (e) { this.error = e.message; }
      finally { this.loading.dashboard = false; }
      this.loadStreaks();
      if (!this._dashboardLayoutLoaded) this.loadDashboardLayout();
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

    // =====================================================================
    // dashboard layout — draggable cards/tiles/blocks (redesign)
    // =====================================================================
    async loadDashboardLayout() {
      this._dashboardLayoutLoaded = true;
      try {
        this.dashboardLayout = await this.api('GET', '/api/config/dashboard-layout');
      } catch (e) { /* keep the built-in default order */ }
    },

    async saveDashboardLayout() {
      try {
        await this.api('PUT', '/api/config/dashboard-layout', this.dashboardLayout);
      } catch (e) { this.error = e.message; }
    },

    visibleHero() {
      return this.dashboardLayout.hero;
    },
    heroCardClass(id) {
      if (id === 'week') return 'summary-card summary-card--link';
      if (id === 'cumulative') {
        const sc = this.surplusClass(this.dashboard.cumulative.surplus_hours);
        return 'summary-card cumulative' + (sc !== 'neutral' ? ' pulse-' + sc : '');
      }
      return 'summary-card';
    },
    visibleTiles() {
      return this.dashboardLayout.tiles.filter(id => {
        if (id === 'yoy') return !!this.yoy;
        return !!this.streakStats;
      });
    },
    visibleAux() {
      return this.dashboardLayout.aux.filter(id => {
        if (id === 'forecast') return !!this.forecast();
        if (id === 'vacation') return !!this.vacationStatus();
        return true;
      });
    },

    // Re-created every time the Dashboard tab mounts (its whole subtree is
    // torn down by x-if when navigating away, taking prior instances with it).
    initDashboardSortables() {
      if (!window.Sortable) return;
      this._dashboardSortables.forEach(s => s.destroy());
      this._dashboardSortables = [];

      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const attach = (el, key) => {
        if (!el) return;
        // Native HTML5 drag (no forceFallback): the browser renders its own floating
        // drag image from the source element and moves it with the cursor, so there's
        // no DOM clone for Alpine's mutation observer to choke on (forceFallback clones
        // the node — including its x-for/x-if directives — into document.body outside
        // Alpine's reactive scope, which threw "id is not defined" on every clone).
        let preDragOrder = [];
        this._dashboardSortables.push(new Sortable(el, {
          animation: reduceMotion ? 0 : 180,
          easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
          handle: '.drag-handle',
          ghostClass: 'kr-drag-ghost',
          chosenClass: 'kr-drag-chosen',
          dragClass: 'kr-drag-dragging',
          onStart: () => { preDragOrder = this._realChildren(el); },
          onEnd: () => {
            const newOrder = this._realChildren(el).map(c => c.dataset.id);
            // Sortable just moved the real DOM nodes to reflect the drop — but Alpine's
            // x-for has no idea that happened; it still thinks the DOM matches the
            // order from its last render. If we leave Sortable's move in place and ALSO
            // let Alpine reorder once we update dashboardLayout below, Alpine computes
            // its moves against a now-stale assumption of "current" positions and can
            // land cards anywhere — right, back where they started, or somewhere else
            // entirely (exactly the flakiness reported). So put the DOM back exactly
            // as Alpine last knew it first, then update state and let Alpine perform
            // the one real, correctly-informed move.
            preDragOrder.forEach(node => el.appendChild(node));
            this._persistDashboardOrder(key, newOrder);
          },
        }));
      };
      attach(this.$refs.heroGrid, 'hero');
      attach(this.$refs.tileGrid, 'tiles');
      attach(this.$refs.auxStack, 'aux');
    },

    // Real (data-id-bearing) children of a Sortable container, in current DOM order —
    // excludes the inert x-for <template> marker Alpine leaves behind as a sibling.
    _realChildren(el) {
      return Array.from(el.children).filter(c => c.dataset && c.dataset.id);
    },

    _persistDashboardOrder(key, visibleIds) {
      const hiddenIds = this.dashboardLayout[key].filter(id => !visibleIds.includes(id));
      this.dashboardLayout[key] = [...visibleIds, ...hiddenIds];
      this.saveDashboardLayout();
    },

    // W1 — animate the three metric values from 0 → real (ease-out cubic, 600ms)
    tickUpDashboard() {
      if (!this.dashboard) return;
      const targets = {
        week:       Math.abs(this.dashboard.week.surplus_hours),
        month:      Math.abs(this.dashboard.month.surplus_hours),
        cumulative: Math.abs(this.dashboard.cumulative.surplus_hours),
      };
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.animWeek = targets.week; this.animMonth = targets.month; this.animCumulative = targets.cumulative;
        return;
      }
      this.animWeek = 0; this.animMonth = 0; this.animCumulative = 0;
      const start = performance.now();
      const tick = (now) => {
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

    // ── Week view ───────────────────────────────────────────────────────────────
    // All figures come straight from /api/entries — summing a week's entries
    // reproduces the backend's `summarize()`, so this stays in lock-step with the
    // Dashboard "This week" card without a dedicated endpoint.

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

    weekIsCurrent() {
      return this.weekStart === this._mondayIso(new Date());
    },

    _weekShift(deltaDays) {
      const base = new Date(this.weekStart + 'T00:00:00');
      this.weekStart = this._dateIso(
        new Date(base.getFullYear(), base.getMonth(), base.getDate() + deltaDays)
      );
    },
    weekPrev() { this.ensureWeekStart(); this._weekShift(-7); },
    weekNext() { this.ensureWeekStart(); this._weekShift(7); },
    weekThis() { this.weekStart = this._mondayIso(new Date()); },

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
        days.push({
          iso, label: DOW[i], dayNum: d.getDate(), entry, draft,
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
      return `${startLabel} – ${endLabel}, ${end.getFullYear()}`;
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

      return byDate.sort((a, b) => {
        const av = a[k]; const bv = b[k];
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      }).map(e => ({ ...e, _cumulative: cumMap[e.date], _isAnchor: e.date === anchorDate }));
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

    filteredMonthly() {
      if (this.analyticsYear === 'all') return this.monthly;
      return this.monthly.filter(m => m.year === Number(this.analyticsYear));
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

    // Average surplus per weekday (Mon–Sun) across all logged work days.
    weekdayPattern() {
      if (!this.entries.length) return null;
      const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const buckets = Array.from({ length: 7 }, () => ({ sum: 0, count: 0 }));
      for (const e of this.entries) {
        if (e.day_type !== 'work') continue;
        const dow = (new Date(e.date + 'T12:00:00').getDay() + 6) % 7; // Mon=0
        buckets[dow].sum += e.surplus_hours;
        buckets[dow].count++;
      }
      return labels.map((label, i) => {
        const { sum, count } = buckets[i];
        const avg = count ? Math.round((sum / count) * 100) / 100 : null;
        const cls = avg === null ? 'hm-empty'
          : avg > 0.1 ? 'hm-surplus'
          : avg < -0.1 ? 'hm-deficit'
          : 'hm-neutral';
        // One decimal everywhere; the sign follows the rounded value, so a tiny
        // average reads 0.0h rather than −0.0h.
        const r = avg === null ? null : Math.round(avg * 10) / 10;
        const text = r === null ? '—' : `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toFixed(1)}h`;
        return { label, avg, cls, count, text,
          title: avg === null ? `${label}: no data` : `${label}: avg ${text} (${count} days)` };
      });
    },

    // ── Chart helpers ────────────────────────────────────────────────

    // Cumulative surplus trend line from monthly data.
    // Returns geometry for an SVG polyline (560×70 viewBox).
    trendLine() {
      if (!this.monthly.length) return null;
      const rows = [...this.monthly].sort((a, b) =>
        a.year !== b.year ? a.year - b.year : a.month - b.month
      );
      let cum = 0;
      const pts = rows.map(r => {
        cum = Math.round((cum + r.surplus_hours) * 100) / 100;
        return { label: r.label, value: cum };
      });
      const values = pts.map(p => p.value);
      const min = Math.min(0, ...values);
      const max = Math.max(0, ...values);
      const range = max - min || 1;
      const W = 560, H = 70, PAD = 6;
      const iW = W - PAD * 2, iH = H - PAD * 2;
      const toX = i => PAD + (pts.length < 2 ? iW / 2 : (i / (pts.length - 1)) * iW);
      const toY = v => PAD + iH - ((v - min) / range) * iH;
      const zeroY = toY(0);
      const coords = pts.map((p, i) => [toX(i), toY(p.value)]);
      const polyline = coords.map(([x, y]) => `${x},${y}`).join(' ');
      const area = pts.length > 1
        ? `M${coords[0][0]},${zeroY}` + coords.map(([x, y]) => ` L${x},${y}`).join('') +
          ` L${coords[coords.length - 1][0]},${zeroY}Z`
        : '';
      const last = { x: coords[coords.length - 1][0], y: coords[coords.length - 1][1], value: pts[pts.length - 1].value };
      const cls = last.value > 0.01 ? 'surplus' : last.value < -0.01 ? 'deficit' : 'neutral';
      return { W, H, polyline, area, zeroY, last, cls };
    },

    // Monthly bar chart from filteredMonthly().
    // Returns geometry for an SVG bar chart (560×100 viewBox).
    monthlyChartBars() {
      const rows = this.filteredMonthly();
      if (!rows.length) return null;
      const W = 560, H = 100;
      const PL = 4, PR = 4, PT = 6, PB = 22;
      const plotW = W - PL - PR, plotH = H - PT - PB;
      const maxVal = Math.max(...rows.map(r => Math.max(r.net_hours, r.target_hours)), 1);
      const barW = plotW / rows.length;
      const gap = Math.max(1, barW * 0.2);
      const scaleH = v => (v / maxVal) * plotH;
      return {
        W, H,
        targetY: PT + plotH - scaleH(rows[0].target_hours),
        bars: rows.map((r, i) => ({
          x: PL + i * barW + gap / 2,
          y: PT + plotH - scaleH(r.net_hours),
          w: barW - gap,
          h: Math.max(scaleH(r.net_hours), 0),
          lx: PL + i * barW + barW / 2,
          ly: H - 6,
          label: r.label.slice(5),
          cls: r.surplus_hours > 0.01 ? 'surplus' : r.surplus_hours < -0.01 ? 'deficit' : 'neutral',
          targetY: PT + plotH - scaleH(r.target_hours),
        })),
      };
    },

    // Renders the bar chart as an SVG string (avoids x-for-inside-svg Alpine issue).
    renderBarChart() {
      const d = this.monthlyChartBars();
      if (!d) return '';
      const bars = d.bars.map(b =>
        `<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" class="chart-bar chart-bar--${b.cls}" rx="1"></rect>` +
        `<text x="${b.lx}" y="${b.ly}" class="chart-label" text-anchor="middle">${b.label}</text>`
      ).join('');
      return `<svg viewBox="0 0 ${d.W} ${d.H}" width="100%" height="${d.H}" class="chart-svg" aria-hidden="true" preserveAspectRatio="none">` +
        `<line x1="0" y1="${d.targetY}" x2="${d.W}" y2="${d.targetY}" class="chart-target"></line>` +
        bars +
        `</svg>` +
        `<p class="muted chart-caption">Net hours per month — dashed line = daily target × work days</p>`;
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
        const [monthly, yearly, records, yoy] = await Promise.all([
          this.api('GET', '/api/analytics/monthly'),
          this.api('GET', '/api/analytics/yearly'),
          this.api('GET', '/api/analytics/records'),
          this.api('GET', '/api/analytics/yoy'),
        ]);
        this.monthly = monthly;
        this.yearly = yearly;
        this.records = records;
        this.yoy = yoy;
        // Entries needed for the heatmap; load lazily if not already in memory
        if (!this.entries.length) await this.loadDays();
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
      } catch (e) { this.error = e.message; }
      finally { this.loading.settings = false; }
    },

    async saveSettings() {
      try {
        await this.api('PUT', '/api/config', this.settingsForm);
        await this.loadDashboard();
        this.showToast('Settings saved', 'neutral');
        this.go('dashboard');
      } catch (e) { this.error = e.message; }
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
      this.monthly = [];
      this.records = null;
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
