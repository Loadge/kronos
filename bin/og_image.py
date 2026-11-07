#!/usr/bin/env python
"""Redraw the link-preview picture and the install dialog's screenshots.

    python bin/og_image.py                      og.png only (no server needed)
    python bin/og_image.py --screenshots        also the two manifest screenshots, of the Dashboard
                                                of a seeded instance (python bin/kctl.py up --seed)

    backend/static/og.png                1200x630, what WhatsApp, Telegram and the like show
    backend/static/screenshot-wide.webp  1280x800, manifest screenshot, form_factor wide
    backend/static/screenshot-narrow.webp 390x844, manifest screenshot, form_factor narrow

The preview picture is an HTML page (below) rendered by Playwright: the logo, the name in the app's
heading face and a slice of the year dial's ring with its ticks, brass on the dark ground.
"""

from __future__ import annotations

import argparse
import base64
import io
import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "backend" / "static"
OG = STATIC / "og.png"
WIDE = STATIC / "screenshot-wide.webp"
NARROW = STATIC / "screenshot-narrow.webp"

BG = "#17140f"
BRASS = "#e0b341"
TEXT = "#ece6d7"
MUTED = "#a49b87"
TAGLINE = "Your hours, your balance and your year, at a glance."

# The ring: a circle far larger than the picture, so only a slice of it shows in the lower right,
# like the dial seen from close. 365 ticks, a long one at the first of each month, a brass one at
# "today".
CX, CY, R = 1250, 860, 560
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def ring_svg() -> str:
    parts = []
    starts = {sum(MONTH_DAYS[:i]) for i in range(12)}
    today = 322  # a day in mid-November: the ring's lit tick
    for day in range(365):
        # day 0 at 12 o'clock, clockwise
        angle = math.radians(day / 365 * 360 - 90)
        long_tick = day in starts
        length = 34 if long_tick else 16
        r1, r2 = R - length, R
        x1, y1 = CX + r1 * math.cos(angle), CY + r1 * math.sin(angle)
        x2, y2 = CX + r2 * math.cos(angle), CY + r2 * math.sin(angle)
        if day == today:
            colour, width, opacity = BRASS, 5, 1
            x1, y1 = CX + (R - 52) * math.cos(angle), CY + (R - 52) * math.sin(angle)
        elif long_tick:
            colour, width, opacity = BRASS, 3, 0.9
        else:
            colour, width, opacity = "#8a6f2c", 1.6, 0.8
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{colour}" stroke-width="{width}" stroke-opacity="{opacity}" '
            'stroke-linecap="round"/>'
        )
    rings = "".join(
        f'<circle cx="{CX}" cy="{CY}" r="{r}" fill="none" stroke="{c}" stroke-width="{w}"/>'
        for r, c, w in (
            (R + 16, "#5a4a22", 2),
            (R + 34, "#3b2f12", 14),
            (R - 74, "#6e5822", 2),
            (R - 150, "#3b2f12", 1),
        )
    )
    return f'<svg viewBox="0 0 1200 630" width="1200" height="630">{rings}{"".join(parts)}</svg>'


def page_html(logo_data: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; width: 1200px; height: 630px; overflow: hidden; background: {BG}; }}
  body {{
    position: relative;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: {TEXT};
    background:
      radial-gradient(900px 700px at {CX}px {CY}px, #2a251b 0%, #1c1913 48%, transparent 72%),
      radial-gradient(700px 500px at 180px 130px, #221d13 0%, transparent 70%),
      {BG};
  }}
  svg {{ position: absolute; inset: 0; }}
  .logo {{ position: absolute; left: 84px; top: 92px; width: 190px; height: 190px;
           filter: drop-shadow(0 10px 28px rgba(0, 0, 0, .55)); }}
  h1 {{ position: absolute; left: 80px; top: 296px; margin: 0; font-size: 168px; line-height: 1;
        font-weight: 700; font-variant: small-caps; letter-spacing: 0.06em; color: {BRASS}; }}
  p {{ position: absolute; left: 86px; top: 490px; width: 620px; margin: 0; font-size: 34px;
       line-height: 1.3; color: {MUTED}; }}
  .rule {{ position: absolute; left: 86px; top: 468px; width: 120px; height: 4px;
           border-radius: 2px; background: {BRASS}; }}
</style></head><body>
{ring_svg()}
<img class="logo" src="{logo_data}" alt="">
<h1>Kronos</h1>
<div class="rule"></div>
<p>{TAGLINE}</p>
</body></html>"""


def draw_og(playwright) -> None:
    logo = base64.b64encode((STATIC / "icon-512.png").read_bytes()).decode("ascii")
    browser = playwright.chromium.launch()
    try:
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(page_html(f"data:image/png;base64,{logo}"))
        page.wait_for_timeout(200)
        raw = page.screenshot(type="png")
    finally:
        browser.close()
    # 256 colours: the picture is flat brass on dark, and a preview should be a few tens of KB.
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        OG, optimize=True
    )
    print(f"{OG.name}: {OG.stat().st_size} bytes")


def draw_screenshots(playwright, url: str) -> None:
    browser = playwright.chromium.launch()
    try:
        for path, (width, height) in ((WIDE, (1280, 800)), (NARROW, (390, 844))):
            context = browser.new_context(
                locale="en-GB",
                color_scheme="dark",
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            # the one-time "press the logo" callout would land in the picture
            context.add_init_script("try { localStorage.setItem('k-dial-hint', '1') } catch {}")
            page = context.new_page()
            page.goto(f"{url}/#dashboard", wait_until="networkidle")
            page.wait_for_timeout(1800)  # the counters roll once
            raw = page.screenshot(type="png")
            context.close()
            Image.open(io.BytesIO(raw)).convert("RGB").save(path, "WEBP", quality=80, method=6)
            print(f"{path.name}: {path.stat().st_size} bytes")
    finally:
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--screenshots", action="store_true", help="also the manifest screenshots")
    parser.add_argument("--url", default="http://127.0.0.1:8796", help="a seeded instance")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        draw_og(p)
        if args.screenshots:
            draw_screenshots(p, args.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
