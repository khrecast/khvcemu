"""Draw the Re:Cast window icon: a hollow blue heart in the logo's colors.

    python tools/make_icon.py

Writes khvcemu/assets/recast_icon.png (256 px) and recast_icon.ico (16 to 256 px, for
Windows shortcuts and the installer). It is drawn from scratch, not cut from
any game artwork, so it can be shipped.
"""

import os
import struct

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import numpy as np
import pygame

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "khvcemu", "assets")


def _heart_points(cx, cy, scale, n=400):
    t = np.linspace(0, 2 * np.pi, n)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    return [(cx + px * scale, cy - py * scale) for px, py in zip(x, y)]


def heart_icon(size: int = 1024) -> pygame.Surface:
    """A hollow blue heart in the logo's colors (light cyan top-left to deep blue),
    drawn big and then shrunk for smooth edges."""
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    k = size / 40.0
    outer = _heart_points(size / 2, size * 0.52, k)
    inner = _heart_points(size / 2, size * 0.47, k * 0.52)
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), outer)
    pygame.draw.polygon(mask, (0, 0, 0, 0), inner)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    t = np.clip((0.55 * (xx / size) + 0.45 * (yy / size) - 0.12) / 0.75, 0, 1)    # light top-left -> dark bottom-right
    top, mid, low = np.array([70, 235, 255]), np.array([35, 150, 240]), np.array([12, 70, 200])
    col = np.where(t[..., None] < 0.5, top + (mid - top) * (t[..., None] / 0.5),
                   mid + (low - mid) * ((t[..., None] - 0.5) / 0.5))
    img = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(img)[:] = np.clip(col, 0, 255).astype(np.uint8).transpose(1, 0, 2)
    pygame.surfarray.pixels_alpha(img)[:] = pygame.surfarray.array_alpha(mask)
    rim = pygame.Surface((size, size), pygame.SRCALPHA)                           # a dark rim so it holds on light taskbars
    pygame.draw.polygon(rim, (6, 30, 90, 255), outer, max(3, size // 90))
    pygame.draw.polygon(rim, (6, 30, 90, 255), inner, max(3, size // 120))
    img.blit(rim, (0, 0))
    return img


def ico_bytes(frames: dict) -> bytes:
    """A .ico holding one PNG image per size (supported since Windows Vista)."""
    pngs = {}
    for size, surf in frames.items():
        tmp = os.path.join(ASSETS, f"_tmp_{size}.png")
        pygame.image.save(surf, tmp)
        with open(tmp, "rb") as f:
            pngs[size] = f.read()
        os.remove(tmp)
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    table, body = b"", b""
    for size, data in pngs.items():
        table += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return head + table + body


def main():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.HIDDEN)
    square = heart_icon()
    frames = {n: pygame.transform.smoothscale(square, (n, n)) for n in (16, 24, 32, 48, 64, 128, 256)}
    pygame.image.save(frames[256], os.path.join(ASSETS, "recast_icon.png"))
    with open(os.path.join(ASSETS, "recast_icon.ico"), "wb") as f:
        f.write(ico_bytes(frames))
    print("wrote recast_icon.png and recast_icon.ico in", ASSETS)


if __name__ == "__main__":
    main()
