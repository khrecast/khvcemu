"""The two 'Wonderland is lost media' screens khvcemu shows after the Alice in
Wonderland splash, drawn in the look of the game's own text pages (white page,
black text, a Continue button bottom-left) at the phone's 176x220.

The game can't show them (they aren't in its data), so the frontend draws
them itself and then passes the Continue press on to the game."""

from __future__ import annotations

import os

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
W, H = 176, 220
HEADING = "Sora's adventure through Wonderland is lost media."
CREDIT = "Screenshots from the original 2005 game."
MESSAGE = ("If you, or someone you know, has a Verizon phone that has been sitting in a drawer "
           "for years and happens to have this level loaded, please contact game "
           "preservationists and send an email to")
EMAIL = "khrecast@gmail.com"


def _wrap(text, font, width):
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if font.size(trial)[0] <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def _text(surf, text, x, y, width, font, color=(0, 0, 0), gap=2):
    for line in _wrap(text, font, width):
        surf.blit(font.render(line, True, color), (x, y))
        y += font.get_linesize() + gap
    return y


def _fit(pygame, img, w, h):
    k = min(w / img.get_width(), h / img.get_height())
    return pygame.transform.smoothscale(img, (max(1, int(img.get_width() * k)), max(1, int(img.get_height() * k))))


def _page(pygame, font):
    surf = pygame.Surface((W, H))
    surf.fill((255, 255, 255))
    # Continue button, like the game's: dark rounded box, white text
    rect = pygame.Rect(3, 197, 63, 21)
    pygame.draw.rect(surf, (36, 34, 52), rect, border_radius=5)
    pygame.draw.rect(surf, (150, 148, 170), rect, width=1, border_radius=5)
    label = font.render("Continue", True, (255, 255, 255))
    surf.blit(label, (rect.centerx - label.get_width() // 2, rect.centery - label.get_height() // 2))
    return surf


def build_screens(pygame, font_names: str, size: int = 9) -> list:
    """Two 176x220 pygame surfaces (needs pygame.font and a display for convert)."""
    pygame.font.init()
    try:
        font = pygame.font.SysFont(font_names, size)
        bold = pygame.font.SysFont(font_names, size, bold=True)
    except Exception:
        font = bold = pygame.font.Font(None, size + 4)
    shot1 = pygame.image.load(os.path.join(ASSETS, "wonderland_1.png"))
    shot2 = pygame.image.load(os.path.join(ASSETS, "wonderland_2.png"))
    s1 = _page(pygame, font)
    pic = _fit(pygame, shot1, 150, 118)
    s1.blit(pic, ((W - pic.get_width()) // 2, 8))
    y = _text(s1, HEADING, 6, 132, W - 12, bold)
    _text(s1, CREDIT, 6, y + 3, W - 12, font)
    s2 = _page(pygame, font)
    # the message sets the layout: the screenshot takes whatever height is left
    lh = font.get_linesize() + 2
    need = len(_wrap(MESSAGE, font, W - 12)) * lh + bold.get_linesize() + 8
    pic_h = max(36, min(70, 190 - need - 10))
    pic = _fit(pygame, shot2, 90, pic_h)
    s2.blit(pic, ((W - pic.get_width()) // 2, 4))
    y = _text(s2, MESSAGE, 6, 4 + pic.get_height() + 5, W - 12, font)
    _text(s2, EMAIL, 6, y + 3, W - 12, bold, color=(20, 60, 160))
    return [s1, s2]


def to_rgb565(img):
    """A Pillow image as a (height, width) uint16 array in the 565 layout the core's frames use."""
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    return ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)


def build_screens_pil(font_names: str = "", size: int = 9) -> list:
    """The same two pages drawn with Pillow instead of pygame (the Android app has no pygame): two (220, 176) uint16
    arrays in the core's 565 layout. Raises RuntimeError if no font can be loaded."""
    from PIL import Image, ImageDraw
    from . import hostgfx
    font = hostgfx.load_font(font_names, size)
    bold = hostgfx.load_font(font_names, size, True)
    if font is None or bold is None:
        raise RuntimeError("no font for the Wonderland pages")

    def line_height(f):
        return f.ascent + f.descent

    def wrap(text, f, width):
        lines, cur = [], ""
        for word in text.split(" "):
            trial = (cur + " " + word).strip()
            if f.size(trial)[0] <= width or not cur:             # (a first word wider than the page stays on its own line)
                cur = trial
            else:
                lines.append(cur)
                cur = word
        return lines + [cur]

    def draw_text(draw, text, x, y, width, f, color=(0, 0, 0), gap=2):
        for line in wrap(text, f, width):
            draw.text((x, y), line, font=f.font, fill=color)
            y += line_height(f) + gap
        return y

    def page():
        img = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.fontmode = "1"                                           # no smoothing, like the game's own text
        box = (3, 197, 3 + 62, 197 + 20)
        d.rounded_rectangle(box, radius=5, fill=(36, 34, 52), outline=(150, 148, 170))
        label = "Continue"
        lw, lh = font.size(label)
        d.text(((box[0] + box[2] - lw) // 2, (box[1] + box[3] - lh) // 2), label, font=font.font, fill=(255, 255, 255))
        return img, d

    def fit(path, w, h):
        img = Image.open(path).convert("RGB")
        k = min(w / img.width, h / img.height)
        return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)

    img1, d1 = page()
    pic = fit(os.path.join(ASSETS, "wonderland_1.png"), 150, 118)
    img1.paste(pic, ((W - pic.width) // 2, 8))
    y = draw_text(d1, HEADING, 6, 132, W - 12, bold)
    draw_text(d1, CREDIT, 6, y + 3, W - 12, font)

    img2, d2 = page()
    lh2 = line_height(font) + 2
    need = len(wrap(MESSAGE, font, W - 12)) * lh2 + line_height(bold) + 8
    pic_h = max(36, min(70, 190 - need - 10))
    pic = fit(os.path.join(ASSETS, "wonderland_2.png"), 90, pic_h)
    img2.paste(pic, ((W - pic.width) // 2, 4))
    y = draw_text(d2, MESSAGE, 6, 4 + pic.height + 5, W - 12, font)
    draw_text(d2, EMAIL, 6, y + 3, W - 12, bold, color=(20, 60, 160))
    return [to_rgb565(img1), to_rgb565(img2)]

