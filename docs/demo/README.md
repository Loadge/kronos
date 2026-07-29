# Regenerating `docs/demo.gif`

The README GIF is produced from a scripted Playwright tour of a **throwaway,
seeded** Kronos instance. Your real data is never involved.

Requires Node 20+, ffmpeg, and the project's Python dependencies.

## 1. Seed a disposable database

`seed_demo.py` deletes all work entries before writing, so it refuses to run
unless `KRONOS_DATA_DIR` is set:

```sh
export KRONOS_DATA_DIR=/tmp/kronos-demo
alembic upgrade head
python docs/demo/seed_demo.py
```

That writes ~18 months of entries (2025-01-01 → today) so the Analytics tab has
a real year-over-year comparison and a well-filled "Year at a glance" heatmap.

## 2. Serve it on a spare port

```sh
KRONOS_DATA_DIR=/tmp/kronos-demo python -m uvicorn app.main:app --host 127.0.0.1 --port 8799 --app-dir backend
```

## 3. Capture the frames

```sh
cd docs/demo && npm install && npx playwright install chromium
KRONOS_URL=http://127.0.0.1:8799 OUT_DIR=./frames node record_demo.mjs
```

Capture is frame-driven, not wall-clock-driven — each frame explicitly sets the
scroll offset and cursor position before screenshotting, so playback is smooth
no matter how slow the capture machine is. Edit the scene list at the bottom of
`record_demo.mjs` to change what the tour shows.

## 4. Assemble the GIF

```sh
ffmpeg -y -framerate 15 -i frames/f%05d.png -vf "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=160[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" -loop 0 ../demo.gif
```

`dither=none` matters — on Kronos's dark theme, dithering adds noise that costs
~2 MB with no visible benefit. 900px wide is roughly 1:1 with GitHub's README
column. The current output is 9.1s, 109 frames, 2.0 MB.
