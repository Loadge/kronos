# Regenerating `docs/demo.gif`

The README GIF is produced from a scripted Playwright tour of a **throwaway,
seeded** Kronos instance. Your real data is never involved.

Requires Node 20+, ffmpeg, and the project's Python dependencies.

## 1. Seed a disposable database

`seed_demo.py` deletes all work entries, freelance blocks, payouts and income
sources before writing, so it refuses to run unless `KRONOS_DATA_DIR` is set.
Use a directory outside the repo:

```sh
export KRONOS_DATA_DIR=/tmp/kronos-demo
alembic upgrade head
python docs/demo/seed_demo.py
```

The dates are fixed, so the result does not depend on the day you run it:

- Work entries from 2025-01-01 to Mon 2026-11-02 (about 22 months), so
  Analytics has a real year-over-year comparison and a well-filled "Year at a
  glance" heatmap. Tue 3 Nov and Wed 4 Nov are left empty: the tour logs
  Tue 3 Nov live.
- A short note on about one work day in eight.
- Three fictional freelance sources (Lumen Studio, Kestrel Labs in USD, Pine &
  Quill), 79 blocks from April to the start of November and one weekly payout
  (Lumen Studio, week of 19 Oct). USD blocks carry a fixed exchange rate, so
  the seed never calls the network.

The tour was made on **Wed 2026-11-04**: the browser's clock is pinned to that
day (10:12), and `KRONOS_NOW` freezes the server's clock on the same instant,
so the frames come out the same on any day.

## 2. Serve it on a spare port

```sh
KRONOS_DATA_DIR=/tmp/kronos-demo KRONOS_NOW=2026-11-04T10:12:00+01:00 python -m uvicorn app.main:app --host 127.0.0.1 --port 8799 --app-dir backend
```

## 3. Capture the frames

**Re-seed before every capture**: the tour creates the entry for 3 Nov, and a
second run would find it already there.

```sh
cd docs/demo && npm install && npx playwright install chromium
KRONOS_URL=http://127.0.0.1:8799 OUT_DIR=./frames node record_demo.mjs
```

Capture is frame-driven, not wall-clock-driven: each frame explicitly sets the
scroll offset, the cursor position, the typed characters, the flash of the
opened week and the "Saved" toast before screenshotting, so playback is smooth
no matter how slow the capture machine is. Edit the scene list in
`record_demo.mjs` to change what the tour shows. The viewport is 1280 x 720
(the header fits on one row and the Log tab has its three columns).

The tour, in order (about 21 s):

1. **Dashboard**, the faint `v38` next to the title, then a scroll down to the
   end of the page.
2. **Log**: the calendar with its Wk column; the October mini month, then the
   week number `41`.
3. **Days > Employee**: the app opens that week's `W41` separator; the week
   flashes.
4. **Log again**: click Tue 3 Nov, `+ Add note`, type a note, change the end
   time to 18:15 (the result rail follows: Net 9.25h, target 8h, +1.25h, fill
   bar), `Create entry`: the page stays in Log, the "Saved" toast shows and the
   calendar cell takes its colour.
5. **Analytics**: the year at a glance, then a scroll down through every chart
   to the export buttons.
6. **Freelance**: billed this year, per-source totals, paid out vs estimated,
   then a scroll down to the year to Dec 31, the tax split and the exports.

## 4. Assemble the GIF

```sh
ffmpeg -y -framerate 15 -i frames/f%05d.png -vf "fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=96[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" -loop 0 ../demo.gif
```

`dither=none` matters — on Kronos's dark theme, dithering adds noise that costs
~2 MB with no visible benefit. The capture is 15 fps; the GIF keeps 10 fps.
The scrolls change the whole frame, so they dominate the size and the palette
size barely matters; width and frame rate do (900 px at 10 fps was 4.8 MB,
800 px at 8 fps 3.5 MB, but the scrolls turn choppy). The current output is
21.3 s, 213 frames, 800 x 450, 4.2 MB.
