"""Generate the app icon used by the desktop shortcut.

Run with ``python assets/make_icon.py``. Draws a small rising bar chart in the
project's navy and sky blue and writes a multi-resolution Windows .ico.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

NAVY = (12, 24, 48, 255)
NAVY_EDGE = (30, 54, 96, 255)
SKY = (56, 189, 248, 255)
SKY_DEEP = (2, 132, 199, 255)

OUT = Path(__file__).resolve().parent / "churn-insight.ico"


def draw(size: int) -> Image.Image:
    scale = 8  # supersample, then downscale for smooth edges
    px = size * scale
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    radius = int(px * 0.22)
    pen.rounded_rectangle([0, 0, px - 1, px - 1], radius=radius, fill=NAVY, outline=NAVY_EDGE,
                          width=max(1, int(px * 0.015)))

    # Four bars climbing left to right - the project's core idea in one glyph.
    heights = [0.30, 0.46, 0.62, 0.80]
    bar_w = px * 0.13
    gap = px * 0.055
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (px - total) / 2
    base = px * 0.80
    bar_radius = int(bar_w * 0.28)

    for index, height in enumerate(heights):
        top = base - px * height * 0.72
        colour = SKY if index >= len(heights) - 2 else SKY_DEEP
        pen.rounded_rectangle([x, top, x + bar_w, base], radius=bar_radius, fill=colour)
        x += bar_w + gap

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw(size) for size in sizes]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
