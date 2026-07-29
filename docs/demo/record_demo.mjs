/**
 * Captures the frames for the README demo GIF.
 *
 * Frame-driven, not wall-clock-driven: every frame explicitly sets the page
 * state (scroll offset, cursor position) and then screenshots, so the result
 * plays back at exactly FPS regardless of how slow the capture machine is.
 *
 *   KRONOS_URL=http://127.0.0.1:8799 OUT_DIR=./frames node record_demo.mjs
 *
 * Then assemble with ffmpeg — see docs/demo/README.md.
 */

import { chromium } from 'playwright';
import { mkdir, rm } from 'node:fs/promises';
import path from 'node:path';

const URL = process.env.KRONOS_URL || 'http://127.0.0.1:8799';
const OUT_DIR = path.resolve(process.env.OUT_DIR || './frames');
const FPS = 15;
const VIEWPORT = { width: 1200, height: 675 };

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
  });
  const page = await context.newPage();

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

  /** Glide the fake cursor to an element, then click it. */
  const moveAndClick = async (locator, duration) => {
    const box = await locator.boundingBox();
    if (!box) throw new Error('element has no bounding box');
    const to = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    const from = await page.evaluate(() => window.__cursorPos);
    const n = secs(duration);
    for (let i = 1; i <= n; i++) {
      const k = ease(i / n);
      await setCursor(page, from.x + (to.x - from.x) * k, from.y + (to.y - from.y) * k);
      await shoot();
    }
    await setCursor(page, to.x, to.y, true);
    await shoot();
    await locator.click();
    await setCursor(page, to.x, to.y, false);
  };

  /** Scroll so a heading sits just below the sticky header. */
  const scrollToHeading = async (text, duration, offset = 90) => {
    const y = await page.evaluate(
      ([t, off]) => {
        const h = [...document.querySelectorAll('h2')].find((el) => el.textContent.trim() === t);
        if (!h) throw new Error(`no <h2> matching "${t}"`);
        return window.scrollY + h.getBoundingClientRect().top - off;
      },
      [text, offset]
    );
    await scrollTo(y, duration);
  };

  // -- Scene 1 -- Dashboard: surplus cards and streaks, static -------------
  await setCursor(page, VIEWPORT.width * 0.5, VIEWPORT.height * 0.62);
  await hold(1.5);

  // -- Scene 2 -- jump to Analytics ----------------------------------------
  const analyticsTab = page.locator('a[role="tab"]', { hasText: 'Analytics' });
  await moveAndClick(analyticsTab, 0.8);
  await page.waitForTimeout(1500); // analytics fetches + charts settle
  await hold(1.0);

  // -- Scene 3 -- cumulative trend chart -----------------------------------
  await scrollToHeading('Cumulative trend', 1.2, 60);
  await hold(0.5);

  // -- Scene 4 -- monthly breakdown -----------------------------------------
  await scrollToHeading('Monthly breakdown', 1.2);
  await hold(0.5);

  // -- Scene 5 -- Year at a glance (the hero shot) --------------------------
  await scrollToHeading('Year at a glance', 1.2, 150);
  await hold(1.0);

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
