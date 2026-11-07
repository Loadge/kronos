#!/usr/bin/env python
"""Redraw the app's icon set from the master logo.

    python bin/icons.py            writes backend/static/*.png from bin/icon-master.png

The master is a 1024 px picture of the logo: a disc on a flat dark square. Everything outside the
disc is dropped and the disc is redrawn at each size, so the small icons carry no grey-blue corners
of the old square and weigh a few KB instead of 800 KB.

    favicon-32.png         the browser tab
    icon-96.png            the header logo and the shortcuts
    icon-192.png           manifest, any
    icon-512.png           manifest, any
    apple-touch-icon.png   180 px, opaque on the app's background (iOS paints transparency black)
    icon-maskable-512.png  the disc inside the 80% safe zone, opaque on the app's background
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "backend" / "static"
MASTER = Path(__file__).resolve().parent / "icon-master.png"
BG = (0x17, 0x14, 0x0F, 255)  # --k-bg

# The disc of the master: centred, outer radius of the grey ring, measured on the 1024 px picture.
DISC_CENTER = 512
DISC_RADIUS = 380
SS = 4  # supersampling for the circular mask edge


def disc(master: Image.Image) -> Image.Image:
    """The master's disc as an RGBA square of 2*DISC_RADIUS px, transparent outside the circle."""
    box = (
        DISC_CENTER - DISC_RADIUS,
        DISC_CENTER - DISC_RADIUS,
        DISC_CENTER + DISC_RADIUS,
        DISC_CENTER + DISC_RADIUS,
    )
    tile = master.convert("RGBA").crop(box)
    size = tile.width
    mask = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * SS - 1, size * SS - 1), fill=255)
    tile.putalpha(mask.resize((size, size), Image.LANCZOS))
    return tile


def render(tile: Image.Image, size: int, fraction: float, opaque: bool) -> Image.Image:
    """The disc scaled to ``fraction`` of a ``size`` px square, centred; opaque or transparent."""
    inner = round(size * fraction)
    scaled = tile.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), BG if opaque else (0, 0, 0, 0))
    offset = (size - inner) // 2
    canvas.alpha_composite(scaled, (offset, offset))
    return canvas


def main() -> None:
    tile = disc(Image.open(MASTER))
    jobs = [
        ("favicon-32.png", 32, 1.0, False),
        ("icon-96.png", 96, 1.0, False),
        ("icon-192.png", 192, 1.0, False),
        ("icon-512.png", 512, 1.0, False),
        ("apple-touch-icon.png", 180, 0.88, True),
        # The maskable safe zone is a circle of 40% of the side; the disc stays inside it.
        ("icon-maskable-512.png", 512, 0.76, True),
    ]
    for name, size, fraction, opaque in jobs:
        image = render(tile, size, fraction, opaque)
        if opaque:
            image = image.convert("RGB")
        if size >= 192:
            # The master is a flat-colour logo with soft noise from its source: 256 colours say
            # the same thing in a fifth of the bytes.
            image = image.quantize(
                colors=256, method=Image.Quantize.FASTOCTREE if not opaque else Image.MEDIANCUT
            )
        path = STATIC / name
        image.save(path, optimize=True)
        print(f"{name}: {size}x{size}, {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
