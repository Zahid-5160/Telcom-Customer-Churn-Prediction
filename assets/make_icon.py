"""Generate the Retain app icon used by the desktop shortcut and the browser tab.

Run with ``python assets/make_icon.py``.

The glyph is a scatter plot with a fitted trend line running through it - the
most universally recognised shorthand for "this is a model fitted to data",
which is exactly what the application does. Drawn in the project's navy and sky
blue, and written out as a multi-resolution Windows .ico.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

NAVY = (12, 24, 48, 255)
NAVY_EDGE = (30, 54, 96, 255)
SKY = (56, 189, 248, 255)
SKY_DEEP = (2, 132, 199, 255)
SKY_PALE = (125, 211, 252, 255)

OUT = Path(__file__).resolve().parent / "retain.ico"

#: Points sit either side of the trend line, as real data does - the scatter is
#: the point of the glyph, so they are spread well clear of it. Coordinates are
#: fractions of the plot area, measured from its bottom-left corner.
POINTS = [
    (0.08, 0.26), (0.20, 0.10), (0.26, 0.42), (0.40, 0.28),
    (0.46, 0.62), (0.60, 0.44), (0.68, 0.78), (0.84, 0.62),
]


def draw(size: int) -> Image.Image:
    scale = 8  # supersample, then downscale for smooth edges
    px = size * scale
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    pen.rounded_rectangle(
        [0, 0, px - 1, px - 1],
        radius=int(px * 0.22),
        fill=NAVY,
        outline=NAVY_EDGE,
        width=max(1, int(px * 0.015)),
    )

    # Plot area, inset from the rounded corners.
    left, right = px * 0.20, px * 0.84
    bottom, top = px * 0.80, px * 0.20
    span_x, span_y = right - left, bottom - top

    def place(fx: float, fy: float) -> tuple[float, float]:
        return left + fx * span_x, bottom - fy * span_y

    # Axes: two hairlines, deliberately recessive.
    axis_w = max(1, int(px * 0.018))
    pen.line([left, top, left, bottom], fill=SKY_DEEP, width=axis_w)
    pen.line([left, bottom, right, bottom], fill=SKY_DEEP, width=axis_w)

    # The fitted line, drawn under the points so the points read on top.
    pen.line(
        [*place(0.04, 0.12), *place(0.88, 0.78)],
        fill=SKY_PALE,
        width=max(2, int(px * 0.035)),
    )

    # The observations. Each carries a ring in the surface colour so points that
    # land near the line, or near each other, stay individually readable.
    radius = px * 0.032
    ring = px * 0.014
    for fx, fy in POINTS:
        cx, cy = place(fx, fy)
        pen.ellipse(
            [cx - radius - ring, cy - radius - ring, cx + radius + ring, cy + radius + ring],
            fill=NAVY,
        )
        pen.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=SKY)

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw(size) for size in sizes]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
