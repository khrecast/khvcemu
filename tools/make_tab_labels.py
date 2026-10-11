"""Render the launcher's tab names (and the Android app's menu names) in the Kingdom Hearts menu font, blocky like the logo.

    python tools/make_tab_labels.py [path/to/KHMenu.otf]

The font is KHMenu, recreated by Televo for "Kingdom Hearts Re:Collection"
(https://github.com/Televo/kingdom-hearts-recollection). That set has no formal license; its
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
import shutil
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
# the Android app's menu and heading names (bright silver, drawn the same way): key -> name. They are written to
# khvcemu/assets/menu/ and copied to android/app/src/main/res/drawable-nodpi/menu_<key>.png (a test keeps the copies equal)
MENU_OUT = os.path.join(ROOT, "khvcemu", "assets", "menu")
ANDROID_RES = os.path.join(ROOT, "android", "app", "src", "main", "res", "drawable-nodpi")
MENU_LABELS = {"continue": "Continue", "play_title": "Play from the title screen", "saved_games": "Saved games",
               "options": "Options", "game_files": "Game files", "set_up": "Set up the game files",
               "load_saved": "Load a saved game", "save_slot": "Save to a slot", "understand": "I understand",
               "start_world": "Start at a world", "sound": "Sound",
               # headings of the Options and Sound screens
               "h_picture_size": "Picture size", "h_picture_filter": "Picture filter", "h_text_size": "Text size",
               "h_speed": "Speed", "h_controls": "Controls", "h_online": "Online scores", "h_autosave": "Autosave",
               "h_try": "Try the music", "h_recording": "A recording of this tune", "h_mix": "Mix", "h_loud": "How loud",
               "h_instruments": "How the instruments sound",
               # the first-run question
               "style_title": "How do you want to play?", "style_smart": "Smartphone style",
               "style_flip": "Play in flip phone style",
               # buttons that always say the same thing
               "b_controls_reset": "Put the controls back to the default", "b_music_mix": "Music mix and sliders",
               "b_test_connection": "Test the connection", "b_restore": "Restore the default settings",
               "b_choose_file": "Choose a file", "b_remove_recording": "Remove it",
               "b_match": "Match its loudness", "b_save_mix": "Save this mix",
               "b_delete_mix": "Delete this mix", "b_rename_mix": "Rename this mix",
               "b_reset": "Reset", "b_import": "Import a state file",
               "b_play": "Play", "b_stop": "Stop", "b_play_recording": "Play the recording",
               "b_stop_recording": "Stop the recording", "b_star": "Star this mix", "b_unstar": "Unstar this mix",
               "b_clear_cache": "Clear the made music", "b_no_cache": "No made music is kept",
               # the names on the touch controls
               "c_action": "Action", "c_magic": "Magic", "c_status": "Status", "c_soft1": "Soft 1", "c_back": "Back",
               "c_soft2": "Soft 2", "c_action_slash": "Action/",
               # the words the game's banner puts over Action (Open, Attack, Grab seen; the others are likely)
               "w_open": "Open", "w_attack": "Attack", "w_grab": "Grab", "w_jump": "Jump", "w_talk": "Talk",
               "w_interact": "Interact", "w_use": "Use", "w_enter": "Enter", "w_lift": "Lift", "w_throw": "Throw"}


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


def _mask(font, text: str) -> np.ndarray:
    glyphs = font.render(text, False, (255, 255, 255))
    a = pygame.surfarray.array_alpha(glyphs).T if glyphs.get_flags() & pygame.SRCALPHA else \
        (pygame.surfarray.array3d(glyphs).sum(axis=2).T > 0)
    return np.asarray(a) > 0


def _spaced_mask(font, text: str, gap: int) -> np.ndarray:
    """The text letter by letter with `gap` empty columns between them (the font draws some pairs, such as l and k, touching)."""
    parts = []
    for ch in text:
        if ch == " ":
            parts.append(np.zeros((1, 4 + gap), bool))
        else:
            m = _mask(font, ch)
            if m.any():
                cols = np.where(m.any(axis=0))[0]
                parts.append(m[:, cols[0]:cols[-1] + 1])                  # trim the letter's own side space
        parts.append(np.zeros((1, gap), bool))
    parts = [p for p in parts if p.size] or [np.zeros((1, 1), bool)]
    h = max(p.shape[0] for p in parts)
    cells = [np.pad(p, ((0, h - p.shape[0]), (0, 0))) for p in parts]
    return np.hstack(cells[:-1])                                          # (no gap after the last letter)


def render(font, text: str, selected: bool, gap: int = 0) -> pygame.Surface:
    mask = np.pad(_spaced_mask(font, text, gap) if gap else _mask(font, text), 1)
    if selected:                       # bright silver on the blue selected tab
        rgba = silver(mask, (255, 255, 255), (176, 188, 204))
    else:                              # the muted silver of an idle tab
        rgba = silver(mask, (196, 208, 224), (110, 126, 148))
    big = rgba.repeat(ZOOM, axis=0).repeat(ZOOM, axis=1)
    surf = pygame.Surface((big.shape[1], big.shape[0]), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surf)[:] = big[:, :, :3].transpose(1, 0, 2)
    pygame.surfarray.pixels_alpha(surf)[:] = big[:, :, 3].T
    return surf


ATLAS_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,:;!?'-/+&%()"


def make_atlas(font) -> None:
    """One picture of the letters, digits and common marks in the menu font (bright silver, like the labels), for text the app only knows
    at run time (the game's own softkey words). A text file beside it lists, for each character, where its cell starts and how wide it is
    (after the doubling), plus the picture's height. The cells include the dark outline and sit side by side without a gap."""
    parts, cells, col = [], [], 0
    gap = 3                                                       # empty columns between glyphs: 1 for each outline and 1 spare
    for ch in ATLAS_CHARS:
        m = _mask(font, ch)
        if not m.any():
            continue
        cols = np.where(m.any(axis=0))[0]
        m = m[:, cols[0]:cols[-1] + 1]
        cells.append((ch, col, m.shape[1] + 2))                   # (in padded coordinates: the outline adds a column each side)
        parts.append(m)
        parts.append(np.zeros((m.shape[0], gap), bool))
        col += m.shape[1] + gap
    strip = np.hstack(parts[:-1])
    rgba = silver(np.pad(strip, 1), (255, 255, 255), (176, 188, 204))
    big = rgba.repeat(ZOOM, axis=0).repeat(ZOOM, axis=1)
    surf = pygame.Surface((big.shape[1], big.shape[0]), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surf)[:] = big[:, :, :3].transpose(1, 0, 2)
    pygame.surfarray.pixels_alpha(surf)[:] = big[:, :, 3].T
    os.makedirs(MENU_OUT, exist_ok=True)
    png = os.path.join(MENU_OUT, "font_atlas.png")
    pygame.image.save(surf, png)
    lines = [str(big.shape[0])] + ["%d %d %d" % (ord(ch), x * ZOOM, w * ZOOM) for ch, x, w in cells]
    txt = os.path.join(MENU_OUT, "font_atlas.txt")
    with open(txt, "w", newline="\n", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if os.path.isdir(ANDROID_RES):
        shutil.copyfile(png, os.path.join(ANDROID_RES, "menu_font_atlas.png"))
        raw = os.path.join(os.path.dirname(ANDROID_RES), "raw")
        os.makedirs(raw, exist_ok=True)
        shutil.copyfile(txt, os.path.join(raw, "menu_font_atlas.txt"))
    print(f"wrote the menu font alphabet ({len(cells)} characters)")


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
    os.makedirs(MENU_OUT, exist_ok=True)
    for key, text in MENU_LABELS.items():
        path = os.path.join(MENU_OUT, f"{key}.png")
        pygame.image.save(render(font, text, True, gap=2 if key.startswith("style_") else 1 if key.startswith("w_") else 0), path)
        if os.path.isdir(ANDROID_RES):
            shutil.copyfile(path, os.path.join(ANDROID_RES, f"menu_{key}.png"))
    make_atlas(font)
    print(f"wrote {len(MENU_LABELS)} app menu labels to {MENU_OUT}"
          + (f" and {ANDROID_RES}" if os.path.isdir(ANDROID_RES) else ""))


if __name__ == "__main__":
    main(*sys.argv[1:2])
