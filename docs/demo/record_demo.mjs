/**
 * Captures the frames for the README demo GIF.
 *
 * Frame-driven, not wall-clock-driven: every frame explicitly sets the page
 * state (scroll offset, cursor position, typed characters, the flash of the
 * jumped-to week, the toast) and then screenshots, so the result plays back at
 * exactly FPS regardless of how slow the capture machine is.
 *
 *   KRONOS_URL=http://127.0.0.1:8799 OUT_DIR=./frames node record_demo.mjs
 *
 * The tour assumes the instance seeded by `seed_demo.py` (fixed dates: data to
 * Mon 2 Nov 2026, Tue 3 Nov empty) and pins the browser's clock to Wed 4 Nov
 * 2026, 10:12. The *server* reads its own clock: serve it on 2026-11-04 (or
 * with a TZ where it still is that day), see docs/demo/README.md.
 *
 * Then assemble with ffmpeg — see docs/demo/README.md.
 */

import { chromium } from 'playwright';
import { mkdir, rm } from 'node:fs/promises';
import path from 'node:path';

const URL = process.env.KRONOS_URL || 'http://127.0.0.1:8799';
const OUT_DIR = path.resolve(process.env.OUT_DIR || './frames');
const FPS = 15;
// 1280 px: the header fits on one row with the Freelance tab, and the Log tab
// has its three columns (calendar, form, result rail).
const VIEWPORT = { width: 1280, height: 720 };
const NOW = '2026-11-04T10:12:00+01:00';

// What the tour logs live: the day the seed leaves empty, and its week.
const LOG_DAY = '2026-11-03';
const JUMP_WEEK = '2026-10-05'; // the Monday of W41, opened from the Log calendar (October)
const NOTE = 'Release prep, then a hotfix';

const CURSOR_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">' +
  '<path d="M3 1.5 L3 16 L6.6 12.6 L9 18 L11.6 16.9 L9.2 11.7 L14 11.5 Z" ' +
  'fill="#fff" stroke="#111" stroke-width="1.1" stroke-linejoin="round"/></svg>';

/** Frames for a duration in seconds. */
const secs = (s) => Math.round(s * FPS);

/** easeInOutCubic — scrolls that start and stop gently read as "human". */
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

async function main() {
  await rm(OUT_DIR, { recursive: true, force: true });
  await mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2, // capture at 2x, downscale in ffmpeg for crisp text
    colorScheme: 'dark',
    reducedMotion: 'reduce', // no half-finished CSS transitions between frames
    locale: 'en-GB', // 24 h time fields
    timezoneId: 'Europe/Madrid',
  });
  // The milestone toast ("365 days logged!") belongs to a first visit; this viewer has seen it.
  await context.addInitScript(() => localStorage.setItem('k-milestone-seen', '100000'));
  const page = await context.newPage();
  await page.clock.setFixedTime(new Date(NOW)); // the browser's "today" never moves

  await page.goto(`${URL}/#dashboard`, { waitUntil: 'networkidle' });
  await installCursor(page);
  await page.waitForTimeout(1200); // let Chart.js finish its entry animation

  let frame = 0;
  const shoot = async () => {
    await page.screenshot({
      path: path.join(OUT_DIR, `f${String(frame++).padStart(5, '0')}.png`),
      animations: 'disabled',
    });
  };

  /** Hold the current state for `duration` seconds. */
  const hold = async (duration) => {
    for (let i = 0; i < secs(duration); i++) await shoot();
  };

  /** Scroll from the current offset to `targetY` over `duration` seconds. */
  const scrollTo = async (targetY, duration) => {
    const fromY = await page.evaluate(() => window.scrollY);
    const n = secs(duration);
    for (let i = 1; i <= n; i++) {
      const y = fromY + (targetY - fromY) * ease(i / n);
      await page.evaluate((v) => window.scrollTo(0, v), y);
      await shoot();
    }
  };

  /** Glide the fake cursor to a point. */
  const glideTo = async (to, duration) => {
    const from = await page.evaluate(() => window.__cursorPos);
    const n = secs(duration);
    for (let i = 1; i <= n; i++) {
      const k = ease(i / n);
      await setCursor(page, from.x + (to.x - from.x) * k, from.y + (to.y - from.y) * k);
      await shoot();
    }
  };

  const centre = async (locator) => {
    const box = await locator.boundingBox();
    if (!box) throw new Error('element has no bounding box');
    return { x: box.x + box.width / 2, y: box.y + box.height / 2, box };
  };

  /** Glide the fake cursor to an element, then click it (at `at` inside it, if given). */
  const moveAndClick = async (locator, duration, at = null) => {
    const c = await centre(locator);
    const to = at ? { x: c.box.x + at.x, y: c.box.y + at.y } : { x: c.x, y: c.y };
    await glideTo(to, duration);
    await setCursor(page, to.x, to.y, true);
    await shoot();
    if (at) await locator.click({ position: at });
    else await locator.click();
    await setCursor(page, to.x, to.y, false);
  };

  /** Back to the top of the page while the cursor glides to a header tab, then click it. */
  const scrollTopAndClick = async (locator, duration) => {
    const fromY = await page.evaluate(() => window.scrollY);
    const c = await centre(locator);
    const to = { x: c.x, y: c.y + fromY }; // where the tab is once the page is at the top
    const from = await page.evaluate(() => window.__cursorPos);
    const n = secs(duration);
    for (let i = 1; i <= n; i++) {
      const k = ease(i / n);
      await page.evaluate((v) => window.scrollTo(0, v), fromY * (1 - k));
      await setCursor(page, from.x + (to.x - from.x) * k, from.y + (to.y - from.y) * k);
      await shoot();
    }
    await setCursor(page, to.x, to.y, true);
    await shoot();
    await locator.click();
    await setCursor(page, to.x, to.y, false);
  };

  /** Type text, `perFrame` characters per frame, so the typing can be read. */
  const typeText = async (text, perFrame = 1) => {
    for (let i = 0; i < text.length; i += perFrame) {
      await page.keyboard.type(text.slice(i, i + perFrame));
      await shoot();
    }
  };

  /** Scroll down to the end of the page (the bottom edge, whatever its height), then hold. */
  const scrollToEnd = async (duration, holdFor = 0.5) => {
    const maxY = await page.evaluate(
      () => document.documentElement.scrollHeight - window.innerHeight
    );
    console.log(`scroll to end: ${Math.round(maxY)} px`);
    await scrollTo(maxY, duration);
    await hold(holdFor);
  };

  /** The Alpine state of the page (to hold things the app times by the wall clock). */
  const app = (fn, arg) => page.evaluate(fn, arg);

  const tab = (name) => page.locator('a[role="tab"]', { hasText: name }).first();

  // -- Scene 1 -- Dashboard, with the faint "v38" next to the title -----------
  await setCursor(page, 292, 80); // resting by the version label
  await hold(0.5);
  await scrollToEnd(1.3, 0.4); // the rest of the Dashboard

  // -- Scene 2 -- Log: the calendar with its week-number column ---------------
  await scrollTopAndClick(tab('Log'), 0.7);
  await page.waitForTimeout(800);
  await scrollTo(190, 0.4); // strip out of the way: calendar, form and result rail in one view
  await hold(0.1);

  // -- Scene 3 -- a week number -> Days > Employee, on that week's separator --
  // The app jumps there by itself (instantly, under reduced motion) and flashes the week
  // for two seconds of wall clock. Both are replayed here frame by frame.
  await moveAndClick(page.locator('.plan-mini', { hasText: 'Oct' }), 0.4); // a full month
  await hold(0.2);
  const wk = page.locator('.log-cal-wk', { hasText: /^41$/ });
  await moveAndClick(wk, 0.5);
  await page.waitForTimeout(1400); // the Days tab renders and the app's own jump settles
  const landedY = await page.evaluate(() => window.scrollY);
  await app(() => {
    const data = window.Alpine.$data(document.querySelector('main'));
    data.daysFlashWeek = ''; // the app's own flash is over; ours is driven per frame below
  });
  await page.addStyleTag({
    content: `tbody.week-flash > tr > td {
      animation: none !important;
      background-color: color-mix(in srgb, var(--k-brass) var(--kpct, 0%), transparent) !important;
    }`,
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await setCursor(page, 640, 360);
  await shoot();
  await scrollTo(landedY, 0.7);
  const flashFrames = secs(0.9);
  for (let i = 0; i < flashFrames; i++) {
    const pct = i < 3 ? (28 * (i + 1)) / 3 : 28 * (1 - (i - 3) / (flashFrames - 3));
    // set again on every frame: the app's own two-second timer must not clear it first
    await page.evaluate(
      ([p, w]) => {
        window.Alpine.$data(document.querySelector('main')).daysFlashWeek = w;
        document.documentElement.style.setProperty('--kpct', `${p}%`);
      },
      [pct, JUMP_WEEK]
    );
    await shoot();
  }
  await page.evaluate(() => document.documentElement.style.setProperty('--kpct', '0%'));
  await app(() => {
    window.Alpine.$data(document.querySelector('main')).daysFlashWeek = '';
  });

  // -- Scene 4 -- back in Log: a day, a note, the result rail, Create entry ---
  await scrollTopAndClick(tab('Log'), 0.5);
  await page.waitForTimeout(800);
  await scrollTo(190, 0.4);
  const month = await page.evaluate(() => {
    const d = window.Alpine.$data(document.querySelector('main'));
    return `${d.calYear}-${d.calMonth}`;
  });
  if (month !== '2026-10') {
    // the Log tab kept October on the calendar: back to November from the year strip
    await moveAndClick(page.locator('.plan-mini', { hasText: 'Nov' }), 0.4);
  }
  await moveAndClick(page.locator(`.log-cal-day[aria-label="${LOG_DAY}"]`), 0.5);
  await page.waitForTimeout(500);
  await hold(0.1);

  await moveAndClick(page.getByRole('button', { name: '+ Add note' }), 0.4);
  await page.waitForTimeout(300);
  if (!(await page.evaluate(() => document.activeElement?.tagName === 'TEXTAREA'))) {
    await page.locator('.log-notes textarea').click();
  }
  await typeText(NOTE, 3);
  await hold(0.2);

  // The end time moves; the rail (Net / Target / delta and its fill bar) follows live.
  const endInput = page.locator('.log-times .grid input[type="time"]').nth(1);
  await moveAndClick(endInput, 0.4, { x: 12, y: 18 });
  await typeText('18', 1); // 18:00
  await hold(0.5);
  await typeText('15', 1); // 18:15
  await hold(0.8);

  await moveAndClick(page.getByRole('button', { name: 'Create entry' }), 0.5);
  await page.waitForTimeout(450); // the POST answers, the toast shows, the cell colours
  await app(() => {
    const d = window.Alpine.$data(document.querySelector('main'));
    clearTimeout(d._toastTimer); // keep the toast up as long as the tour wants it
  });
  await hold(1.0);
  await app(() => {
    window.Alpine.$data(document.querySelector('main')).toast.show = false;
  });

  // -- Scene 5 -- Analytics: the year at a glance, the zoomable chart ---------
  await scrollTopAndClick(tab('Analytics'), 0.6);
  await page.waitForTimeout(1500); // analytics fetches + charts settle
  await hold(0.7);
  await scrollToEnd(2.0, 0.5); // down through every chart

  // -- Scene 6 -- Freelance: sources, blocks and a payout ---------------------
  await scrollTopAndClick(tab('Freelance'), 0.6);
  await page.waitForTimeout(1500);
  await hold(0.7);
  await scrollToEnd(1.5, 0.7);

  await browser.close();
  console.log(`captured ${frame} frames (${(frame / FPS).toFixed(1)}s @ ${FPS}fps) -> ${OUT_DIR}`);
}

/** Inject a fake cursor — headless screenshots never contain the real pointer. */
async function installCursor(page) {
  await page.addStyleTag({
    content: `
      #__cursor {
        position: fixed; z-index: 2147483647; top: 0; left: 0;
        width: 20px; height: 20px; margin: -3px 0 0 -3px;
        pointer-events: none; will-change: transform;
      }
      #__cursor > i {
        display: block; width: 100%; height: 100%;
        background: center/contain no-repeat url("data:image/svg+xml,${encodeURIComponent(CURSOR_SVG)}");
        filter: drop-shadow(0 1px 2px rgba(0,0,0,.6));
        transition: transform .12s ease-out;
      }
      #__cursor.down > i { transform: scale(.85); }
      #__cursor::after {
        content: ''; position: absolute; inset: -12px;
        border-radius: 50%; background: rgba(255,255,255,.28);
        transform: scale(0); transition: transform .18s ease-out;
      }
      #__cursor.down::after { transform: scale(1); }
    `,
  });
  await page.evaluate(() => {
    const el = document.createElement('div');
    el.id = '__cursor';
    el.appendChild(document.createElement('i'));
    document.body.appendChild(el);
    window.__cursorPos = { x: 0, y: 0 };
    // Paint synchronously so a screenshot taken right after never lags a frame.
    window.__cursorPaint = (x, y, down) => {
      window.__cursorPos = { x, y };
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.classList.toggle('down', !!down);
    };
  });
}

async function setCursor(page, x, y, down = false) {
  await page.evaluate(([px, py, d]) => window.__cursorPaint(px, py, d), [x, y, down]);
  await page.mouse.move(x, y);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
