"""Make the Android app icon: the Re:Cast heart, slightly pixelated, at the five launcher densities.

    python android/tools/make_icon_pixelated.py [cells] [rough]        (default 44 cells across the heart, no roughness)

The heart is the hollow blue one from khvcemu/assets/recast_icon.png (drawn by tools/make_icon.py). It is cut into a coarse grid of cells,
each cell is either heart or not (hard edges, no smoothing) and the smooth gradient becomes a few flat color bands. Nothing is added or
removed: with a `rough` share above 0 (say 0.07) that share of the boundary cells is nudged (a fixed seed, so the same icon comes out every
time), which looked like missing pieces and is off by default; `edges=True` in cells() adds a bright and a dark pixel along the edges. Writes
android/app/src/main/res/mipmap-*/ic_launcher_foreground.png; the adaptive icon's background is unchanged.
"""

import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE = os.path.join(ROOT, "khvcemu", "assets", "recast_icon.png")
RES = os.path.join(ROOT, "android", "app", "src", "main", "res")
DENSITIES = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
HEART_SHARE = 0.56                    # the heart's width as a share of the canvas (the adaptive icon's safe zone is the middle 66%)
BANDS = [(120, 240, 255), (70, 205, 252), (38, 160, 244), (25, 120, 232), (18, 88, 214), (12, 62, 180)]   # light top-left to deep bottom-right
SHADE = (8, 40, 128)                  # the bottom and right edge of the shape
LIGHT = (190, 250, 255)               # a bright pixel on the top and left edge


def cells(n_wide: int, seed: int = 7, rough: float = 0.0, edges: bool = False):
    """(rgba array of the heart as n_wide cells across, its height in cells)."""
    src = Image.open(SOURCE).convert("RGBA")
    box = src.getbbox()
    heart = src.crop(box)
    aspect = heart.height / heart.width
    n_high = max(1, round(n_wide * aspect))
    # how much of each cell the heart covers (so the cell is in or out by what is there, not by a smoothed guess)
    big = heart.resize((n_wide * 8, n_high * 8), Image.LANCZOS)
    alpha = np.asarray(big)[..., 3].astype(np.float32) / 255.0
    cover = alpha.reshape(n_high, 8, n_wide, 8).mean(axis=(1, 3))
    on = cover >= 0.5
    # rough the edge: a boundary cell is flipped now and then
    rng = np.random.default_rng(seed)
    pad = np.pad(on, 1)
    edge = (pad[1:-1, 1:-1] != pad[:-2, 1:-1]) | (pad[1:-1, 1:-1] != pad[2:, 1:-1]) | (pad[1:-1, 1:-1] != pad[1:-1, :-2]) | (pad[1:-1, 1:-1] != pad[1:-1, 2:])
    if rough > 0:
        on = on ^ (edge & (rng.random(on.shape) < rough))
    # flat color bands, light top-left to deep bottom-right (as the smooth icon runs)
    yy, xx = np.mgrid[0:n_high, 0:n_wide].astype(np.float32)
    t = np.clip((0.55 * (xx / n_wide) + 0.45 * (yy / n_high) - 0.05) / 0.9, 0, 0.999)
    band = (t * len(BANDS)).astype(int)
    rgb = np.zeros((n_high, n_wide, 3), np.uint8)
    for i, c in enumerate(BANDS):
        rgb[band == i] = c
    # a pixel of light on the top and left edge of the shape, a pixel of shade on the bottom and right edge
    pad = np.pad(on, 1)
    top_left = on & (~pad[:-2, 1:-1] | ~pad[1:-1, :-2])
    bottom_right = on & (~pad[2:, 1:-1] | ~pad[1:-1, 2:])
    if edges:
        rgb[bottom_right & ~top_left] = SHADE
        rgb[top_left & ~bottom_right] = LIGHT
    out = np.zeros((n_high, n_wide, 4), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = np.where(on, 255, 0)
    return out, n_high


def icon(size: int, n_wide: int, rough: float = 0.0, edges: bool = False) -> Image.Image:
    grid, n_high = cells(n_wide, rough=rough, edges=edges)
    cell = Image.fromarray(grid, "RGBA")
    heart_w = round(size * HEART_SHARE)
    heart_h = round(heart_w * n_high / n_wide)
    big = cell.resize((heart_w, heart_h), Image.NEAREST)            # hard-edged cells
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(big, ((size - heart_w) // 2, (size - heart_h) // 2 + round(size * 0.01)), big)
    return canvas


def main(n_wide: int = 44, rough: float = 0.0):
    for name, size in DENSITIES.items():
        folder = os.path.join(RES, "mipmap-" + name)
        os.makedirs(folder, exist_ok=True)
        icon(size, n_wide, rough).save(os.path.join(folder, "ic_launcher_foreground.png"), optimize=True)
    print("wrote the launcher icon with %d cells across the heart (roughness %.2f)" % (n_wide, rough))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 44, float(sys.argv[2]) if len(sys.argv) > 2 else 0.0)
