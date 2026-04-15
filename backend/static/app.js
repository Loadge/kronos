/* Kronos — Alpine component + API client.
 *
 * Exposes a single global `app()` factory consumed by x-data="app()" on <main>.
 * No build step, no modules — just a function on window.
 */

function app() {
  return {
    // ---------- nav + global state ---------------------------------------
    tab: 'dashboard',
    subtitle: '',
    error: null,

    // ---------- dashboard -----------------------------------------------
    dashboard: null,

    // ---------- log form ------------------------------------------------
    form: { date: '', day_type: 'work', start_time: '09:00', end_time: '17:00', notes: '', breaks: [] },
    editingDate: null,

    // ---------- days list -----------------------------------------------
    entries: [],
    sortKey: 'date',
    sortDir: 'desc',

    // ---------- analytics -----------------------------------------------
    monthly: [],
    records: null,
    asOfDate: '',
    asOfResult: null,

    // ---------- settings ------------------------------------------------
    settingsForm: { daily_target_hours: 8, cumulative_start_date: '' },

    // ---------- fun zone ------------------------------------------------
    wipeConfirming: false,
    wipeInput: '',
    seedConfirming: false,
    seedInput: '',

    // =====================================================================
    // init
    // =====================================================================
    async init() {
      await this.loadDashboard();
      this.openNewEntry();
    },

    // =====================================================================
    // nav
    // =====================================================================
    async go(t) {
      this.tab = t;
      this.error = null;
      if (t === 'dashboard') await this.loadDashboard();
      else if (t === 'days') await this.loadDays();
      else if (t === 'analytics') await this.loadAnalytics();
      else if (t === 'settings') await this.loadSettings();
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
      try {
        this.dashboard = await this.api('GET', '/api/dashboard');
        const h = this.dashboard.cumulative.surplus_hours;
        const abs = Math.abs(h).toFixed(2);
        if (h > 0.01) this.subtitle = `${abs}h ahead overall`;
        else if (h < -0.01) this.subtitle = `${abs}h behind overall`;
        else this.subtitle = 'on target';
      } catch (e) { this.error = e.message; }
    },

    // =====================================================================
    // log form
    // =====================================================================
    openNewEntry() {
      this.editingDate = null;
      this.form = {
        date: this.todayIso(),
        day_type: 'work',
        start_time: '09:00',
        end_time: '17:00',
        notes: '',
        breaks: [],   // no break pre-filled — user adds explicitly via "+ Add break"
      };
    },

    async onDateChange() {
      // Only fires in new-entry mode (date input is disabled while editing).
      if (this.editingDate || !this.form.date) return;
      // Probe for an existing entry. A 404 is normal — stay in new-entry mode.
      const res = await fetch(`/api/entries/${this.form.date}`, {
        headers: { Accept: 'application/json' },
      });
      if (res.status === 404) return;
      if (!res.ok) { this.error = `${res.status} ${res.statusText}`; return; }
      // Entry found — populate the form and switch to edit mode so Save uses PUT.
      this.editEntry(await res.json());
    },

    editEntry(e) {
      this.editingDate = e.date;
      this.form = {
        date: e.date,
        day_type: e.day_type,
        start_time: e.start_time || '09:00',
        end_time: e.end_time || '17:00',
        notes: e.notes || '',
        breaks: (e.breaks || []).map(b => ({ break_minutes: b.break_minutes })),
      };
      this.tab = 'log';
      this.error = null;
    },

    addBreak() { this.form.breaks.push({ break_minutes: 30 }); },
    removeBreak(i) { this.form.breaks.splice(i, 1); },

    applyRangeToBreak(b, start, end) {
      const m = this.rangeMinutes(start, end);
      if (m > 0) b.break_minutes = m;
    },

    async saveEntry() {
      this.error = null;
      const isWork = this.form.day_type === 'work';
      const body = { day_type: this.form.day_type, notes: this.form.notes || null };
      if (isWork) {
        body.start_time = this.form.start_time;
        body.end_time = this.form.end_time;
        // Drop any break rows left empty (break_minutes falsy / 0) rather than
        // forwarding them to the server where they'd fail the >= 1 validation.
        body.breaks = this.form.breaks
          .filter(b => Number(b.break_minutes) > 0)
          .map(b => ({ break_minutes: Number(b.break_minutes) }));
      } else {
        body.breaks = [];
      }
      try {
        if (this.editingDate) {
          await this.api('PUT', `/api/entries/${this.editingDate}`, body);
        } else {
          body.date = this.form.date;
          await this.api('POST', '/api/entries', body);
        }
        await this.loadDashboard();
        this.go('days');
      } catch (e) { this.error = e.message; }
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
      try { this.entries = await this.api('GET', '/api/entries'); }
      catch (e) { this.error = e.message; }
    },

    sortBy(k) {
      if (this.sortKey === k) this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
      else { this.sortKey = k; this.sortDir = 'desc'; }
    },

    sortedEntries() {
      const k = this.sortKey;
      const dir = this.sortDir === 'asc' ? 1 : -1;
      return [...this.entries].sort((a, b) => {
        const av = a[k]; const bv = b[k];
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      });
    },

    // =====================================================================
    // analytics
    // =====================================================================
    async loadAnalytics() {
      try {
        this.asOfDate = this.asOfDate || this.todayIso();
        const [monthly, records] = await Promise.all([
          this.api('GET', '/api/analytics/monthly'),
          this.api('GET', '/api/analytics/records'),
        ]);
        this.monthly = monthly;
        this.records = records;
        await this.computeAsOf();
      } catch (e) { this.error = e.message; }
    },

    async computeAsOf() {
      if (!this.asOfDate) { this.asOfResult = null; return; }
      try {
        this.asOfResult = await this.api(
          'GET', `/api/analytics/cumulative?as_of=${this.asOfDate}`
        );
      } catch (e) { this.error = e.message; }
    },

    // =====================================================================
    // settings
    // =====================================================================
    async loadSettings() {
      try {
        const cfg = await this.api('GET', '/api/config');
        this.settingsForm = { ...cfg };
      } catch (e) { this.error = e.message; }
    },

    async saveSettings() {
      try {
        await this.api('PUT', '/api/config', this.settingsForm);
        await this.loadDashboard();
        this.go('dashboard');
      } catch (e) { this.error = e.message; }
    },

    // =====================================================================
    // fun zone
    // =====================================================================
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
      this.asOfResult = null;
    },
  };
}
