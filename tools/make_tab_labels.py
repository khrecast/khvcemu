"""Render the launcher's tab names in the Kingdom Hearts menu font, blocky like the logo.

    python tools/make_tab_labels.py [path/to/KHMenu.otf]

The font is KHMenu, recreated by Televo for "Kingdom Hearts Re:Collection"
(https://github.com/Televo/kingdom-hearts-recollection). That set has no formal licence; its
README says credit is much appreciated although not necessary, and Televo is credited in the
README, docs/CREDITS.md and on the website. The font file itself is not part of this repository
(keep it in the gitignored reference/ folder); only the small pictures made from it are, in
khvcemu/assets/tabs/:

    <tab>.png       the tab's name, silver, for a tab that is not selected
    <tab>_on.png    brighter, for the selected tab

Each name is drawn small with no smoothing, given a silver gradient and a dark outline, then
doubled with hard pixel edges, the way the Re:Cast logo was made.
"""

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import numpy as np
import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "khvcemu", "assets", "tabs")
FONT = os.path.join(ROOT, "reference", "KHMenu.otf")
SIZE = 10            # pixels, before doubling
ZOOM = 2
# the launcher's tabs (key -> name); "setup_warn" is the Setup tab when something needs fixing
LABELS = {"play": "Play", "saves": "Saves", "options": "Options", "sound": "Sound",
          "setup": "Setup", "setup_warn": "Setup (!)", "controls": "Controls"}
OUTLINE = (8, 14, 26)


def silver(mask: np.ndarray, top, bottom) -> np.ndarray:
    """RGBA (h, w, 4): the letters filled with a top-to-bottom gradient, plus a 1-pixel dark
    outline around them. mask is (h, w) bool with a 1-pixel margin."""
    h, w = mask.shape
    rows = np.where(mask.any(axis=1))[0]
    t = np.zeros(h)
    if len(rows):
        t = np.clip((np.arange(h) - rows[0]) / max(1, rows[-1] - rows[0]), 0, 1)
    fill = (np.array(top)[None, :] * (1 - t[:, None]) + np.array(bottom)[None, :] * t[:, None])
    grown = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            grown |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    out = np.zeros((h, w, 4), np.uint8)
    out[grown & ~mask, :3] = OUTLINE
    out[grown & ~mask, 3] = 255
    out[mask, :3] = np.broadcast_to(fill[:, None, :], (h, w, 3))[mask].astype(np.uint8)
    out[mask, 3] = 255
    return out


def render(font, text: str, selected: bool) -> pygame.Surface:
    glyphs = font.render(text, False, (255, 255, 255))
    a = pygame.surfarray.array_alpha(glyphs).T if glyphs.get_flags() & pygame.SRCALPHA else \
        (pygame.surfarray.array3d(glyphs).sum(axis=2).T > 0)
    mask = np.pad(np.asarray(a) > 0, 1)
    if selected:                       # bright silver on the blue selected tab
        rgba = silver(mask, (255, 255, 255), (176, 188, 204))
    else:                              # the muted silver of an idle tab
        rgba = silver(mask, (196, 208, 224), (110, 126, 148))
    big = rgba.repeat(ZOOM, axis=0).repeat(ZOOM, axis=1)
    surf = pygame.Surface((big.shape[1], big.shape[0]), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surf)[:] = big[:, :, :3].transpose(1, 0, 2)
    pygame.surfarray.pixels_alpha(surf)[:] = big[:, :, 3].T
    return surf


def main(font_path: str = FONT):
    if not os.path.isfile(font_path):
        sys.exit(f"KHMenu.otf not found at {font_path}: download it from "
                 "https://github.com/Televo/kingdom-hearts-recollection (Fonts folder)")
    pygame.init()
    font = pygame.font.Font(font_path, SIZE)
    os.makedirs(OUT, exist_ok=True)
    for key, text in LABELS.items():
        for selected, suffix in ((False, ""), (True, "_on")):
            pygame.image.save(render(font, text, selected), os.path.join(OUT, f"{key}{suffix}.png"))
    print(f"wrote {len(LABELS) * 2} labels to {OUT}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
