"""Host drawing services for the core where pygame is not available (Android): decoding the game's PNG/BMP
images and rasterising text, both with Pillow.

When pygame is installed (every desktop build) the core keeps using pygame for these jobs exactly as before and
this module is never loaded: `image.decode_image` and `Display._font` / `Display.DrawText` only reach for it when
`import pygame` fails.
"""

from __future__ import annotations

import io
import math
import os
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------------------------- images
def decode_image(raw: bytes):
    """-> (rgb565 (h, w) uint16, alpha mask (h, w) bool), as khvcemu.image.decode_image gives with pygame.

    Pillow's RGBA conversion applies a palette's or a colour key's transparency, so one alpha test covers what the
    pygame version does in two steps."""
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    img.load()
    rgba = np.asarray(img.convert("RGBA"))
    rgb = rgba[..., :3].astype(np.uint16)
    alpha = rgba[..., 3] > 127
    px = ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)
    return px.astype(np.uint16), alpha


# ---------------------------------------------------------------------------------------------- fonts
# font family (as in Display.FONT_CANDIDATES) -> (regular file, bold file). The first one found in a system
# folder is used. Android always has Droid Sans (this is what the phone gets); Roboto and Noto Sans follow.
FONT_FILES = {
    "verdana": ("verdana.ttf", "verdanab.ttf"),
    "dejavusans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "segoeui": ("segoeui.ttf", "segoeuib.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf"),
    "liberationsans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
    "freesans": ("FreeSans.ttf", "FreeSansBold.ttf"),
    "droidsans": ("DroidSans.ttf", "DroidSans-Bold.ttf"),
    "roboto": ("Roboto-Regular.ttf", "Roboto-Bold.ttf"),
    "notosans": ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
}
FALLBACK_ORDER = ("droidsans", "roboto", "notosans", "dejavusans", "liberationsans")
FONT_DIRS = (
    "/system/fonts",
    "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/TTF",
    "/usr/share/fonts/truetype/freefont",
    "/Library/Fonts", "/System/Library/Fonts/Supplemental",
    os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
)


def find_font_file(names: str, bold: bool) -> Optional[str]:
    """Path of the first system font named in `names` (comma separated, like pygame's SysFont), then the fallbacks."""
    wanted = [n.strip().lower().replace(" ", "") for n in (names or "").split(",") if n.strip()]
    for family in wanted + [f for f in FALLBACK_ORDER if f not in wanted]:
        files = FONT_FILES.get(family)
        if not files:
            continue
        name = files[1] if bold else files[0]
        for folder in FONT_DIRS:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return None


class PilFont:
    """The small part of pygame's font interface the core uses (ascent, descent, size), plus mask(): the text as a
    1-bit coverage array, which is all Display.DrawText needs. Glyphs are not anti-aliased, like pygame's
    render(text, False, ...)."""

    def __init__(self, font):
        self.font = font
        ascent, descent = font.getmetrics()
        self.ascent, self.descent = ascent, abs(descent)      # pygame's convention below makes the descent negative

    def get_ascent(self) -> int:
        return self.ascent

    def get_descent(self) -> int:               # pygame reports it negative; the core takes abs()
        return -self.descent

    def size(self, text: str):
        return (math.ceil(self.font.getlength(text)), self.ascent + self.descent)

    def mask(self, text: str) -> np.ndarray:
        """(height, width) bool array: where the glyphs are."""
        from PIL import Image, ImageDraw
        w, h = self.size(text)
        img = Image.new("L", (max(1, w), max(1, h)), 0)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"
        draw.text((0, 0), text, font=self.font, fill=255)
        return np.asarray(img) > 127


def load_font(names: str, size: int, bold: bool = False) -> Optional[PilFont]:
    """A PilFont of `size` pixels, or None when Pillow cannot make one."""
    from PIL import ImageFont
    path = find_font_file(names, bold)
    try:
        if path:
            return PilFont(ImageFont.truetype(path, size))
        return PilFont(ImageFont.load_default(size))
    except Exception:
        return None
