/*
 * Kronos year dial: the year as a brass chronograph whose outer ring turns under a
 * fixed index, one day per detent. A plain script, no modules: it defines window.KronosDial.
 *
 *   KronosDial.open(root, data, callbacks)   root: the #yd element the template drew
 *   KronosDial.close()
 *
 * data:      { today: 'YYYY-MM-DD', years: [2024, 2025, 2026], balanceMax: 123.4 }
 * callbacks: year(y)   one { k, v, fl } per day of the year y: the kind of its tick, its signed
 *                      length (-1..1) and its freelance mark ('fl' | 'paid' | undefined)
 *            read(iso) what the day says (see paint): text, balance, week
 *            go(iso)   open that day in Log
 *            close()   the user asked for it to close (Esc, the cross)
 *            getSound() / setSound(on)
 *
 * This file draws and turns; what a day says is app.js's. The loop runs only while the dial is
 * open. A frame writes the ring's rotation and, while it moves, the needle; the readout is
 * written once per detent, never per frame, and no Alpine state is touched.
 */
(function () {
  'use strict';

  const BASE = 366;                 // the base line of the ticks, in viewBox units
  const REACH = 56;                 // how far a bar reaches from it, at most
  const FL_FROM = 308, FL_TO = 314; // the inner ring of freelance days
  const NEEDLE_MAX = 135;           // degrees either side of the top
  const BAND_FROM = 300, BAND_TO = 505;   // where a press turns the ring to the day pressed
  const MAX_FLICK = 8;              // days per frame, the fastest a hand can throw the ring
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  let S = null;   // the open dial, or null

  const mod = (n, m) => ((n % m) + m) % m;
  const f1 = n => n.toFixed(1);
  const polar = (deg, rad) => {
    const a = (deg - 90) * Math.PI / 180;
    return [Math.cos(a) * rad, Math.sin(a) * rad];
  };
  const pad2 = n => String(n).padStart(2, '0');
  const isoOf = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  const sign = n => (n > 0 ? 1 : n < 0 ? -1 : 0);

  function yearDays(y) {
    const out = [];
    for (let d = new Date(y, 0, 1, 12); d.getFullYear() === y; d.setDate(d.getDate() + 1)) out.push(isoOf(d));
    return out;
  }

  const el = (s, name) => s.root.querySelector(`[data-yd="${name}"]`);

  // ---- drawing -----------------------------------------------------------------------------

  // The ticks of the year: one path per colour class, drawn once per year shown. Days after
  // today go in a dimmer group.
  function drawYear(s) {
    const desc = s.cb.year(s.year) || [];
    s.days = yearDays(s.year);
    s.N = s.days.length;
    s.STEP = 360 / s.N;
    const past = {}, future = {}, fl = {};
    const add = (g, cls, seg) => { (g[cls] ||= []).push(seg); };
    s.days.forEach((iso, i) => {
      const d = desc[i] || { k: 'empty', v: 0 };
      const deg = i * s.STEP;
      const seg = (a, b) => {
        const [x1, y1] = polar(deg, a), [x2, y2] = polar(deg, b);
        return `M${f1(x1)} ${f1(y1)}L${f1(x2)} ${f1(y2)}`;
      };
      const len = Math.max(5, Math.abs(d.v || 0) * REACH);   // at least a stub
      let from, to;
      if (d.k === 'surplus') { from = BASE; to = BASE + len; }
      else if (d.k === 'deficit') { from = BASE - len; to = BASE; }
      else if (d.k === 'neutral') { from = BASE - 4; to = BASE + 4; }
      else if (d.k === 'empty') { from = BASE - 3; to = BASE + 3; }
      else { from = BASE - 22; to = BASE + 22; }               // a leave day, whole, or a draft
      add(iso > s.today ? future : past, String(d.k).replace(/[^a-z-]/g, ''), seg(from, to));
      if (d.fl) add(fl, d.fl === 'paid' ? 'paid' : 'fl', seg(FL_FROM, FL_TO));
    });
    const paths = g => Object.entries(g).map(([c, segs]) => `<path class="yd-t-${c}" d="${segs.join('')}"/>`).join('');
    el(s, 'ticks').innerHTML = `<g class="yd-past">${paths(past)}</g><g class="yd-future">${paths(future)}</g>`;
    el(s, 'flring').innerHTML = paths(fl);

    let m = '';
    MONTHS.forEach((name, n) => {
      const key = `-${pad2(n + 1)}-`;
      const first = s.days.findIndex(k => k.includes(key));
      const len = s.days.filter(k => k.includes(key)).length;
      const [x1, y1] = polar(first * s.STEP - s.STEP / 2, 432), [x2, y2] = polar(first * s.STEP - s.STEP / 2, 470);
      m += `<line x1="${f1(x1)}" y1="${f1(y1)}" x2="${f1(x2)}" y2="${f1(y2)}" class="yd-edge"/>`;
      m += `<text class="yd-month" transform="rotate(${f1((first + len / 2) * s.STEP)}) translate(0 -442)">${name}</text>`;
    });
    el(s, 'months').innerHTML = m;

    // the brass pip on the turning ring: today, whichever day is under the index
    const pip = el(s, 'pip');
    const ti = s.days.indexOf(s.today);
    if (ti >= 0) {
      const [x, y] = polar(ti * s.STEP, 422);
      pip.setAttribute('cx', f1(x));
      pip.setAttribute('cy', f1(y));
      pip.removeAttribute('visibility');
    } else {
      pip.setAttribute('visibility', 'hidden');
    }

    s.ring.setAttribute('aria-valuemax', String(s.N));
    s.stage.dataset.days = String(s.N);
    el(s, 'year').textContent = String(s.year);
    const at = s.data.years.indexOf(s.year);
    el(s, 'prev').disabled = at <= 0;
    el(s, 'next').disabled = at < 0 || at >= s.data.years.length - 1;
    s.rot = null;
  }

  // The small dials' fixed marks, once.
  function drawSubdials(s) {
    let t = '';
    for (let i = 0; i < 12; i++) {
      const [a, b] = polar(i * 30, 62), [c, d] = polar(i * 30, 68);
      t += `<line x1="${f1(a)}" y1="${f1(b)}" x2="${f1(c)}" y2="${f1(d)}" class="yd-edge-s"/>`;
    }
    el(s, 'balticks').innerHTML = t;
    t = '';
    for (let i = 0; i < 60; i += 5) {
      const [a, b] = polar(i * 6, 50), [c, d] = polar(i * 6, 56);
      t += `<line x1="${f1(a)}" y1="${f1(b)}" x2="${f1(c)}" y2="${f1(d)}" class="yd-edge-s"/>`;
    }
    el(s, 'secticks').innerHTML = t;
  }

  // The readout of the day under the index. Called on a detent only.
  function paint(s, r, iso, i) {
    el(s, 'date').textContent = r.date;
    el(s, 'wk').textContent = r.wk;
    const big = el(s, 'big'), sub = el(s, 'sub');
    big.textContent = r.big;
    big.setAttribute('class', `yd-big yd-big--${r.bigKind}`);
    sub.textContent = r.sub;
    sub.setAttribute('class', `yd-sub yd-sub--${r.subKind}`);
    for (const n of ['note', 'note2']) el(s, n).textContent = r.note || '';
    for (const n of ['fl', 'fl2']) {
      const f = el(s, n);
      f.textContent = r.fl ? r.fl.text : '';
      f.classList.toggle('paid', !!(r.fl && r.fl.paid));
    }
    for (const n of ['balv', 'balv2']) el(s, n).textContent = r.balance.text;
    s.needle = s.data.balanceMax > 0
      ? Math.max(-NEEDLE_MAX, Math.min(NEEDLE_MAX, r.balance.value / s.data.balanceMax * NEEDLE_MAX))
      : 0;
    if (s.calm) { s.needleNow = s.needle; writeNeedle(s); }
    let w = '';
    r.week.pips.forEach((p, n) => {
      const h = p.h == null ? 4 : 10 + Math.min(1, p.h) * 26;
      w += `<rect class="yd-pip yd-pip--${p.k}${p.on ? ' on' : ''}" x="${f1(-42 + n * 12.4)}" y="${f1(14 - h)}" width="9" height="${f1(h)}" rx="1.5"/>`;
    });
    el(s, 'week').innerHTML = w;
    for (const n of ['weekv', 'weekv2']) el(s, n).textContent = r.week.sum;
    s.stage.dataset.day = iso;
    s.ring.setAttribute('aria-valuenow', String(i + 1));
    s.ring.setAttribute('aria-valuetext', r.text);
  }

  function writeNeedle(s) {
    el(s, 'bal').setAttribute('transform', `rotate(${s.needleNow.toFixed(2)})`);
  }

  // ---- the detent: a click, a buzz, a jiggle ------------------------------------------------

  function audioOf(s) {
    if (!s.audio) {
      try {
        const C = window.AudioContext || window.webkitAudioContext;
        if (C) s.audio = new C();
      } catch { /* no audio here: the dial stays silent */ }
    }
    return s.audio;
  }

  // A click you can hear, made on the spot: no sound file.
  function click(s, speed) {
    if (!s.sound) return;
    const ctx = audioOf(s);
    if (!ctx) return;
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    const n = ctx.currentTime, o = ctx.createOscillator(), g = ctx.createGain();
    o.type = 'square';
    o.frequency.value = 1900 + Math.min(speed, 2) * 500;
    g.gain.setValueAtTime(0.05, n);
    g.gain.exponentialRampToValueAtTime(0.0001, n + 0.018);
    o.connect(g).connect(ctx.destination);
    o.start(n);
    o.stop(n + 0.02);
  }

  // The crown's label: "Today" is engraved beside the crown while the ring is away from today, and the crown
  // glows once each time the ring leaves it. On opening the ring winds round to today by itself: that is not
  // leaving it, so the label waits until the wind has ended (`opening`).
  function setAway(s, away) {
    if (away === s.away) return;
    s.away = away;
    el(s, 'crownlabel').hidden = !away;
    if (away && !s.calm) {
      const crown = el(s, 'crown');
      crown.classList.remove('glow');
      void crown.offsetWidth;
      crown.classList.add('glow');
    }
  }

  function settle(s) {
    s.opening = false;
    if (s.shown >= 0) setAway(s, s.days[s.shown] !== s.today);
  }

  function detent(s, i) {
    const first = s.shown === -1;
    s.shown = i;
    const iso = s.days[i];
    paint(s, s.cb.read(iso), iso, i);
    if (!s.opening) setAway(s, iso !== s.today);
    if (first) return;
    if (!s.calm) {
      const x = el(s, 'index');
      x.classList.remove('tick');
      void x.getBBox();
      x.classList.add('tick');
    }
    click(s, Math.abs(s.vel));
    if (navigator.userActivation && navigator.userActivation.hasBeenActive) {
      try { navigator.vibrate && navigator.vibrate(4); } catch { /* a buzz is a nicety */ }
    }
  }

  // ---- the loop ---------------------------------------------------------------------------

  // Write the ring's rotation if it changed, and the readout if the day under the index did.
  function sync(s) {
    const rot = -s.pos * s.STEP;
    if (rot !== s.rot) {
      el(s, 'rotor').setAttribute('transform', `rotate(${rot.toFixed(3)})`);
      s.rot = rot;
    }
    const i = mod(Math.round(s.pos), s.N);
    if (i !== s.shown) detent(s, i);
  }

  function step(s, now) {
    const dt = Math.min(40, now - s.last) / 16.67;
    s.last = now;
    if (!s.dragging) {
      if (s.target !== null) {                       // a target: ease toward it
        const d = s.target - s.pos;
        s.pos += d * Math.min(1, 0.14 * dt);
        if (Math.abs(d) < 0.01) { s.pos = s.target; s.target = null; s.vel = 0; if (s.opening) { sync(s); settle(s); } }
      } else if (Math.abs(s.vel) > 0.02) {           // a flick: friction
        s.pos += s.vel * dt;
        s.vel *= Math.pow(0.955, dt);
      } else {                                       // the detent pulls it home, with a little bounce
        const home = Math.round(s.pos), d = home - s.pos;
        s.vel = 0;
        s.pos += d * Math.min(1, 0.32 * dt);
        if (Math.abs(d) < 0.002) s.pos = home;
      }
    }
    sync(s);
    if (Math.abs(s.needle - s.needleNow) > 0.01) {
      s.needleNow += (s.needle - s.needleNow) * Math.min(1, 0.16 * dt);
      writeNeedle(s);
    }
  }

  function loop(s) {
    const tick = now => {
      if (S !== s) return;                           // closed: the loop ends with the dial
      s.raf = requestAnimationFrame(tick);
      step(s, now);
    };
    s.last = performance.now();
    s.raf = requestAnimationFrame(tick);
  }

  // The little dial's second hand: the real clock. It keeps turning forward past 60.
  function secondHand(s) {
    const sec = new Date().getSeconds();
    if (sec === s.sec) return;
    if (sec < s.sec) s.turns++;
    s.sec = sec;
    el(s, 'sec').style.transform = `rotate(${sec * 6 + s.turns * 360}deg)`;
  }

  // ---- moving the ring ---------------------------------------------------------------------

  // Whole days from where the ring rests (or is heading), or at once when motion is off.
  function nudge(s, n) {
    if (s.calm) { s.pos = Math.round(s.pos) + n; s.target = null; s.vel = 0; sync(s); return; }
    s.target = (s.target === null ? Math.round(s.pos) : s.target) + n;
  }

  function turnTo(s, index) {
    if (s.calm) { s.pos = index; s.target = null; s.vel = 0; sync(s); return; }
    s.target = index;
  }

  // The crown: back to today, the short way round.
  function goToday(s) {
    const ty = Number(s.today.slice(0, 4));
    if (s.year !== ty) { setYear(s, ty, sign(ty - s.year) || 1, s.today); return; }
    const i = s.days.indexOf(s.today), c = mod(Math.round(s.pos), s.N);
    let d = i - c;
    if (d > s.N / 2) d -= s.N;
    if (d < -s.N / 2) d += s.N;
    turnTo(s, Math.round(s.pos) + d);
  }

  // Another year, on the same month and day as far as it has them; the ring does a short turn.
  function setYear(s, y, dir, iso) {
    const cur = iso || s.days[mod(Math.round(s.pos), s.N)];
    let md = cur.slice(5);
    s.year = y;
    drawYear(s);
    if (!s.days.includes(`${y}-${md}`)) md = '02-28';
    const idx = s.days.indexOf(`${y}-${md}`);
    s.shown = -1;
    s.vel = 0;
    s.target = null;
    if (s.calm) { s.pos = idx; } else { s.pos = idx - 12 * dir; s.target = idx; }
    sync(s);
  }

  function stepYear(s, dir) {
    const at = s.data.years.indexOf(s.year) + dir;
    if (at < 0 || at >= s.data.years.length) return;
    setYear(s, s.data.years[at], dir);
  }

  // ---- hands -------------------------------------------------------------------------------

  const centre = s => {
    const b = s.stage.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2, u: b.width / 1040 };
  };

  function onDown(ev) {
    const s = S;
    if (!s || ev.target.closest('.yd-crown, .yd-crown-label')) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    const c = centre(s);
    s.dragging = true;
    s.moved = false;
    s.target = null;
    if (s.opening) settle(s);
    s.vel = 0;
    s.pid = ev.pointerId;
    s.downX = ev.clientX;
    s.downY = ev.clientY;
    s.lastA = Math.atan2(ev.clientY - c.y, ev.clientX - c.x) * 180 / Math.PI;
    s.lastT = ev.timeStamp;
    try { s.stage.setPointerCapture(ev.pointerId); } catch { /* a synthetic pointer */ }
    s.stage.classList.add('turning');
    s.ring.focus({ preventScroll: true });           // the keys turn the ring after a drag too
  }

  function onMove(ev) {
    const s = S;
    if (!s || !s.dragging || ev.pointerId !== s.pid) return;
    if (!s.moved && Math.hypot(ev.clientX - s.downX, ev.clientY - s.downY) < 4) return;
    s.moved = true;
    const c = centre(s);
    const a = Math.atan2(ev.clientY - c.y, ev.clientX - c.x) * 180 / Math.PI;
    let d = a - s.lastA;
    if (d > 180) d -= 360;
    if (d < -180) d += 360;
    s.pos -= d / s.STEP;
    const dt = Math.max(1, ev.timeStamp - s.lastT);
    const v = s.vel * 0.6 + (-d / s.STEP) / dt * 16.67 * 0.4;
    s.vel = Math.max(-MAX_FLICK, Math.min(MAX_FLICK, v));
    s.lastA = a;
    s.lastT = ev.timeStamp;
  }

  // A press with no movement on the tick band turns the ring to the day pressed.
  function press(s, ev) {
    const c = centre(s);
    const dx = ev.clientX - c.x, dy = ev.clientY - c.y;
    const r = Math.hypot(dx, dy) / c.u;
    if (r < BAND_FROM || r > BAND_TO) return;
    let a = Math.atan2(dy, dx) * 180 / Math.PI + 90;   // from twelve o'clock, clockwise
    if (a > 180) a -= 360;
    turnTo(s, Math.round(s.pos + a / s.STEP));
  }

  function onUp(ev) {
    const s = S;
    if (!s || !s.dragging || ev.pointerId !== s.pid) return;
    s.dragging = false;
    s.stage.classList.remove('turning');
    try { s.stage.releasePointerCapture(ev.pointerId); } catch { /* already released */ }
    if (ev.type === 'pointercancel') { s.vel = 0; return; }
    if (!s.moved) { s.vel = 0; press(s, ev); return; }
    if (ev.timeStamp - s.lastT > 90) s.vel = 0;       // held still before letting go: no flick
    if (s.calm) { s.vel = 0; s.pos = Math.round(s.pos); sync(s); }
  }

  function onWheel(ev) {
    const s = S;
    if (!s) return;
    ev.preventDefault();
    if (ev.timeStamp - s.wheelT > 250) s.wheelAcc = 0;
    s.wheelT = ev.timeStamp;
    s.wheelAcc += ev.deltaY;
    if (Math.abs(s.wheelAcc) < 40) return;             // a notch is 100; a trackpad adds up
    nudge(s, sign(s.wheelAcc));
    s.wheelAcc = 0;
  }

  const KEY_STEPS = { ArrowRight: 1, ArrowLeft: -1, ArrowUp: 7, ArrowDown: -7, PageUp: 30, PageDown: -30 };

  function onRingKey(ev) {
    const s = S;
    if (!s || ev.ctrlKey || ev.altKey || ev.metaKey) return;
    const go = KEY_STEPS[ev.key];
    if (go) { ev.preventDefault(); nudge(s, go); }
    else if (ev.key === 'Home') { ev.preventDefault(); goToday(s); }
    else if (ev.key === 'Enter') { ev.preventDefault(); s.cb.go(s.days[mod(Math.round(s.pos), s.N)]); }
  }

  // Esc closes it; Tab stays inside. Nothing else the app listens to may see these keys.
  function onRootKey(ev) {
    const s = S;
    if (!s) return;
    if (ev.key === 'Escape') {
      ev.preventDefault();
      ev.stopPropagation();
      s.cb.close();
      return;
    }
    if (ev.key !== 'Tab') return;
    const items = [...s.root.querySelectorAll('button, [tabindex="0"]')].filter(n => !n.disabled && n.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (ev.shiftKey && (document.activeElement === first || !s.root.contains(document.activeElement))) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && (document.activeElement === last || !s.root.contains(document.activeElement))) {
      ev.preventDefault();
      first.focus();
    }
  }

  // ---- open and close ------------------------------------------------------------------------

  function open(root, data, cb) {
    if (S) close();
    const stage = root.querySelector('[data-yd="stage"]');
    const s = {
      root, stage, ring: root.querySelector('[data-yd="ring"]'), data, cb,
      today: data.today, year: Number(data.today.slice(0, 4)),
      calm: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      days: [], N: 365, STEP: 360 / 365, pos: 0, vel: 0, target: null, dragging: false,
      moved: false, shown: -1, away: false, opening: false, rot: null, needle: 0, needleNow: 0, last: 0, raf: 0,
      sound: !!cb.getSound(), audio: null, wheelAcc: 0, wheelT: 0, sec: -1, turns: 0, secTimer: 0,
    };
    S = s;
    drawYear(s);
    drawSubdials(s);
    document.documentElement.classList.add('yd-lock');

    // on opening the ring winds round to today once
    const today = s.days.indexOf(s.today);
    s.pos = today - (s.calm ? 0 : 150);
    s.target = s.calm ? null : today;
    s.opening = !s.calm;
    sync(s);

    const soundBtn = el(s, 'sound');
    const label = () => { soundBtn.textContent = s.sound ? 'Sound on' : 'Sound off'; soundBtn.classList.toggle('on', s.sound); };
    label();
    soundBtn.addEventListener('click', () => {
      s.sound = !s.sound;
      label();
      cb.setSound(s.sound);
      if (s.sound) click(s, 0);                        // a gesture: the right moment to unlock audio
    });
    el(s, 'prev').addEventListener('click', () => stepYear(s, -1));
    el(s, 'next').addEventListener('click', () => stepYear(s, 1));
    el(s, 'go').addEventListener('click', () => cb.go(s.days[mod(Math.round(s.pos), s.N)]));
    el(s, 'close').addEventListener('click', () => cb.close());
    el(s, 'crown').addEventListener('click', () => goToday(s));
    el(s, 'crownlabel').addEventListener('click', () => goToday(s));
    el(s, 'crown').addEventListener('animationend', ev => ev.currentTarget.classList.remove('glow'));

    stage.addEventListener('pointerdown', onDown);
    stage.addEventListener('pointermove', onMove);
    stage.addEventListener('pointerup', onUp);
    stage.addEventListener('pointercancel', onUp);
    stage.addEventListener('wheel', onWheel, { passive: false });
    s.ring.addEventListener('keydown', onRingKey);
    root.addEventListener('keydown', onRootKey);
    // after a click on the crown or the bar the arrows go on turning the ring; the keyboard keeps its place
    root.addEventListener('click', ev => {
      if (S === s && ev.detail > 0 && ev.target.closest('.yd-bar button, .yd-crown, .yd-crown-label')) s.ring.focus({ preventScroll: true });
    });

    secondHand(s);
    if (!s.calm) s.secTimer = setInterval(() => secondHand(s), 250);
    loop(s);
    s.ring.focus({ preventScroll: true });
  }

  function close() {
    const s = S;
    if (!s) return;
    S = null;
    cancelAnimationFrame(s.raf);
    clearInterval(s.secTimer);
    document.documentElement.classList.remove('yd-lock');
    if (s.audio) { s.audio.close().catch(() => {}); s.audio = null; }
  }

  window.KronosDial = { open, close };
})();
