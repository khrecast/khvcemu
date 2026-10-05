"""pygame window: video, keyboard, audio, real-time loop."""

from __future__ import annotations

import math
import os
import sys
import time

import numpy as np

from .keys import AVK
from .paths import icon_file, set_app_id

HELP = """Controls (phone keypad):
  WASD / Arrows / 2 4 6 8  move (Up = forward)      Enter / Space / 5 ... select, attack, jump
  F1 or Q ................ left softkey (Continue)   F2 or E ............. right softkey (Options/Back)
  F or [ or numpad * ..... magic (*)                Z or 0 .............. status + items
  ] or numpad / .......... #                        0-9 (row or numpad) . number keys
  Backspace .............. CLR                      F10 mute   F11 picture filter   F12 screenshot
  Esc quit (asks first)
  F5 save state   F9 load state   F6/F7 previous/next slot (or Shift+1..9; slot 0 = autosave)
  F8 autosave on/off (every 5 min of play)"""


def build_keymap(pygame):
    k = pygame
    m = {
        k.K_UP: "UP", k.K_DOWN: "DOWN", k.K_LEFT: "LEFT", k.K_RIGHT: "RIGHT",
        k.K_w: "UP", k.K_s: "DOWN", k.K_a: "LEFT", k.K_d: "RIGHT", k.K_f: "STAR",   # WASD + F (magic)
        k.K_RETURN: "SELECT", k.K_KP_ENTER: "SELECT", k.K_SPACE: "SELECT",
        k.K_F1: "SOFT1", k.K_q: "SOFT1", k.K_F2: "SOFT2", k.K_e: "SOFT2",
        k.K_z: "0",                                   # Status + items (the game's 0 key)
        k.K_BACKSPACE: "CLR", k.K_LEFTBRACKET: "STAR", k.K_KP_MULTIPLY: "STAR",
        k.K_RIGHTBRACKET: "POUND", k.K_KP_DIVIDE: "POUND",
    }
    for d in range(10):
        m[getattr(k, f"K_{d}")] = str(d)
        m[getattr(k, f"K_KP{d}")] = str(d)
    return m


def to_rgb(frame565: np.ndarray) -> np.ndarray:
    f = frame565.astype(np.uint32)
    r = ((f >> 11) & 31) * 255 // 31
    g = ((f >> 5) & 63) * 255 // 63
    b = (f & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.uint8)


def make_dpi_aware():
    """Stop Windows display scaling (125%/150%) from blowing the window up and
    blurring it: tell Windows we size the window ourselves."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


AUTO_SCALE_MAX = 2      # the game was made for a tiny phone screen: it looks best small, so "Auto" stops here


def auto_scale(pygame, w: int, h: int) -> int:
    """Largest whole-number scale that fits the desktop with room for the
    taskbar and title bar, but never more than AUTO_SCALE_MAX (2). A bigger window is
    still one drag, or --scale 3 or 4, away."""
    try:
        dw, dh = pygame.display.get_desktop_sizes()[0]
    except Exception:
        info = pygame.display.Info()
        dw, dh = info.current_w, info.current_h
    if dw <= 0 or dh <= 0:
        return AUTO_SCALE_MAX
    return max(1, min(AUTO_SCALE_MAX, (dw - 100) // w, (dh - 140) // h))


def fit_rect(win_w: int, win_h: int, w: int, h: int):
    """Largest aspect-correct rectangle for a w x h image inside the window."""
    k = min(win_w / w, win_h / h)
    if k >= 1:
        k = max(1, int(k)) if abs(k - round(k)) < 0.02 else k
    dw, dh = max(1, int(w * k)), max(1, int(h * k))
    return (win_w - dw) // 2, (win_h - dh) // 2, dw, dh


# How the 176x220 picture is enlarged to the window. Only the picture: hi-res text
# (when on) is drawn afterwards at window resolution and F12 saves the raw frame.
FILTERS = ("nearest", "smooth", "sharp", "scale2x")
FILTER_NAMES = {"nearest": "Pixels (crisp)", "smooth": "Smooth", "sharp": "Sharp pixels",
                "scale2x": "Scale2x (rounded edges)"}


_CUBIC: dict = {}
A = -0.75  # cubic sharpness: -0.5 is Catmull-Rom; -0.75 is crisper with no visible halos


def _cubic_weights(n_in: int, n_out: int) -> np.ndarray:
    """n_out x n_in matrix that resamples a line with a Catmull-Rom cubic."""
    key = (n_in, n_out)
    if key not in _CUBIC:
        x = (np.arange(n_out) + 0.5) * n_in / n_out - 0.5        # source position of each output pixel
        base = np.floor(x).astype(int)
        w = np.zeros((n_out, n_in), np.float32)
        for k in range(-1, 3):
            idx = base + k
            d = np.abs(x - idx)
            wk = np.where(d < 1, (A + 2) * d ** 3 - (A + 3) * d ** 2 + 1,
                          np.where(d < 2, A * d ** 3 - 5 * A * d ** 2 + 8 * A * d - 4 * A, 0))
            np.add.at(w, (np.arange(n_out), np.clip(idx, 0, n_in - 1)), wk.astype(np.float32))
        _CUBIC[key] = w / w.sum(1, keepdims=True)
    return _CUBIC[key]


def _bicubic(pygame, surf, dw: int, dh: int):
    a = pygame.surfarray.array3d(surf).astype(np.float32)        # (w, h, 3)
    a = np.tensordot(_cubic_weights(a.shape[0], dw), a, axes=(1, 0))     # (dw, h, 3)
    a = np.tensordot(_cubic_weights(a.shape[1], dh), a, axes=(1, 1))     # (dh, dw, 3)
    return pygame.surfarray.make_surface(np.clip(a, 0, 255).astype(np.uint8).transpose(1, 0, 2))


def scale_frame(pygame, surf, dw: int, dh: int, filt: str = "nearest"):
    """Enlarge (or shrink) `surf` to dw x dh with the chosen filter.
      nearest: every phone pixel a crisp block; at non-integer sizes some
               blocks come out a pixel wider than others
      smooth:  bicubic (Catmull-Rom): smooth but keeps edges crisp, unlike
               bilinear, which looks out of focus
      sharp:   nearest to the largest whole multiple, then bilinear for the
               last fraction: crisp blocks of even width, edges barely softened
      scale2x: EPX/Scale2x doubling (rounds off staircases without blurring),
               as many times as fits, then bilinear for the rest"""
    w, h = surf.get_size()
    if (dw, dh) == (w, h):
        return surf
    if filt == "smooth":
        return _bicubic(pygame, surf, dw, dh)
    if filt == "sharp":
        n = max(1, min(dw // w, dh // h))
        big = pygame.transform.scale(surf, (w * n, h * n)) if n > 1 else surf
        return big if big.get_size() == (dw, dh) else pygame.transform.smoothscale(big, (dw, dh))
    if filt == "scale2x":
        big = surf
        while big.get_width() * 2 <= dw and big.get_height() * 2 <= dh:
            big = pygame.transform.scale2x(big)
        return big if big.get_size() == (dw, dh) else pygame.transform.smoothscale(big, (dw, dh))
    return pygame.transform.scale(surf, (dw, dh))


def draw_frame(pygame, emu, screen, w: int, h: int, override=None, filt: str = "nearest"):
    """Paint the latest frame letterboxed onto `screen`. When the game drew
    text straight to the screen it is redrawn here at window resolution.
    `override`: a w x h pygame surface to show instead (khvcemu's own screens).
    `filt`: how the picture is enlarged (see scale_frame)."""
    overlay = None if override is not None else getattr(emu, "overlay", None)
    if override is not None:
        surf = override
    else:
        base = overlay[0] if overlay else emu.last_frame   # overlay[0]: frame minus the low-res text
        surf = pygame.surfarray.make_surface(to_rgb(base).transpose(1, 0, 2))
    x, y, dw, dh = fit_rect(screen.get_width(), screen.get_height(), w, h)
    surf = scale_frame(pygame, surf, dw, dh, filt)
    screen.fill((0, 0, 0))
    screen.blit(surf, (x, y))
    if overlay:
        kx, ky = dw / w, dh / h
        for it in overlay[1]:
            ts = emu.display.hires_text(it, kx)
            if ts is None:
                continue
            bx0, by0, bx1, by1 = it["box"]
            # clip to the low-res text's visible box so game clip rects still apply
            screen.set_clip(pygame.Rect(x + int(bx0 * kx) - 1, y + int(by0 * ky) - 1,
                                        math.ceil((bx1 - bx0) * kx) + 2, math.ceil((by1 - by0) * ky) + 2))
            screen.blit(ts, (x + round(it["x"] * kx), y + round(it["y"] * ky)))
        screen.set_clip(None)


def draw_quit_prompt(pygame, screen, font_cache: dict):
    """Dim the picture and draw the 'Are you sure?' box centered on the window."""
    sw, sh = screen.get_size()
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 150))
    screen.blit(dim, (0, 0))
    lines = [("Quit the game?", (255, 255, 255)),
             ("Unsaved progress will be lost.", (210, 210, 210)),
             ("Enter / Y  =  quit", (255, 220, 120)),
             ("Esc / N  =  keep playing", (255, 220, 120)),
             ("D  =  quit, and don't ask again", (180, 200, 230))]
    size = max(12, min(sw // 14, sh // 16))
    while True:                                   # shrink until the widest line fits the window
        if size not in font_cache:
            font_cache[size] = pygame.font.SysFont("verdana,dejavusans,tahoma,arial", size, bold=True)
        font = font_cache[size]
        surfs = [font.render(t, True, c) for t, c in lines]
        pad = size
        bw = max(s.get_width() for s in surfs) + pad * 2
        if bw <= sw * 0.94 or size <= 8:
            break
        size -= 1
    bh = sum(s.get_height() for s in surfs) + pad * 2 + size // 2 * (len(surfs) - 1)
    bx, by = (sw - bw) // 2, (sh - bh) // 2
    pygame.draw.rect(screen, (24, 28, 52), (bx, by, bw, bh), border_radius=8)
    pygame.draw.rect(screen, (230, 200, 90), (bx, by, bw, bh), width=2, border_radius=8)
    y = by + pad
    for s in surfs:
        screen.blit(s, (bx + (bw - s.get_width()) // 2, y))
        y += s.get_height() + size // 2


MUTE_ICON_SECS = 1.6


def draw_mute_icon(pygame, screen, muted: bool):
    """A speaker in a small box in the top-right corner: with a red cross when sound is off,
    with sound waves when it is on. Drawn from shapes, so it needs no font or image."""
    sw, sh = screen.get_size()
    size = max(34, min(sw // 9, sh // 9, 72))
    pad = max(6, size // 6)
    box = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.rect(box, (24, 28, 52, 225), (0, 0, size, size), border_radius=max(4, size // 6))
    pygame.draw.rect(box, (230, 200, 90, 255), (0, 0, size, size), width=2, border_radius=max(4, size // 6))
    white = (255, 255, 255)
    cy, u = size // 2, size / 10                       # the speaker is drawn on a 10-unit grid
    body = [(2.0 * u, cy - 1.3 * u), (3.6 * u, cy - 1.3 * u), (5.6 * u, cy - 3.0 * u),
            (5.6 * u, cy + 3.0 * u), (3.6 * u, cy + 1.3 * u), (2.0 * u, cy + 1.3 * u)]
    pygame.draw.polygon(box, white, body)
    if muted:
        red, t = (235, 70, 70), max(2, size // 14)
        pygame.draw.line(box, red, (6.6 * u, cy - 2.0 * u), (8.8 * u, cy + 2.0 * u), t)
        pygame.draw.line(box, red, (6.6 * u, cy + 2.0 * u), (8.8 * u, cy - 2.0 * u), t)
    else:
        t = max(2, size // 16)
        for r in (1.9 * u, 3.1 * u):                  # two arcs of sound, centered on the speaker's mouth
            pygame.draw.arc(box, white, (5.6 * u - r, cy - r, 2 * r, 2 * r), -0.9, 0.9, t)
    screen.blit(box, (sw - size - pad, pad))


def draw_pause_label(pygame, screen, font_cache: dict):
    """The game is held still because the window is in the background: dim the picture a little
    and say so, so a paused game never looks frozen."""
    sw, sh = screen.get_size()
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 90))
    screen.blit(dim, (0, 0))
    lines = [("PAUSED", (255, 255, 255)), ("Click the window to continue", (255, 220, 120))]
    size = max(12, min(sw // 11, sh // 12))
    while True:
        key = ("pause", size)
        if key not in font_cache:
            font_cache[key] = pygame.font.SysFont("verdana,dejavusans,tahoma,arial", size, bold=True)
        small = key[1] * 0.55
        key2 = ("pause", int(small))
        if key2 not in font_cache:
            font_cache[key2] = pygame.font.SysFont("verdana,dejavusans,tahoma,arial", max(8, int(small)), bold=True)
        surfs = [font_cache[key].render(lines[0][0], True, lines[0][1]),
                 font_cache[key2].render(lines[1][0], True, lines[1][1])]
        pad = size // 2
        bw = max(s.get_width() for s in surfs) + pad * 2
        if bw <= sw * 0.94 or size <= 8:
            break
        size -= 1
    bh = sum(s.get_height() for s in surfs) + pad * 2
    bx, by = (sw - bw) // 2, (sh - bh) // 2
    box = pygame.Surface((bw, bh), pygame.SRCALPHA)
    pygame.draw.rect(box, (24, 28, 52, 225), (0, 0, bw, bh), border_radius=8)
    pygame.draw.rect(box, (230, 200, 90, 255), (0, 0, bw, bh), width=2, border_radius=8)
    screen.blit(box, (bx, by))
    y = by + pad
    for s in surfs:
        screen.blit(s, (bx + (bw - s.get_width()) // 2, y))
        y += s.get_height()


SAVE_ICON_SECS = 1.8


def draw_save_icon(pygame, screen):
    """A small floppy disc in the bottom-left corner: "autosaved". It sits low and in the corner so
    it never covers the dialogue, which a text message across the top used to."""
    sw, sh = screen.get_size()
    n = max(16, min(sw // 11, sh // 14))                 # the disc is n x n pixels
    pad = max(4, n // 4)
    x, y = pad, sh - n - pad
    icon = pygame.Surface((n, n), pygame.SRCALPHA)
    r = max(2, n // 9)
    pygame.draw.rect(icon, (10, 14, 30, 215), (0, 0, n, n), border_radius=r + 1)           # backing, for contrast
    m = max(1, n // 12)
    body = pygame.Rect(m, m, n - 2 * m, n - 2 * m)
    pygame.draw.rect(icon, (46, 92, 190), body, border_radius=r)                            # the disc
    pygame.draw.rect(icon, (210, 225, 255), body, width=max(1, n // 16), border_radius=r)
    sh_w, sh_h = body.w * 5 // 8, body.h * 3 // 8                                           # metal shutter
    shutter = pygame.Rect(body.x + (body.w - sh_w) // 2, body.y + max(1, n // 16), sh_w, sh_h)
    pygame.draw.rect(icon, (205, 210, 220), shutter)
    pygame.draw.rect(icon, (60, 70, 95), (shutter.right - max(2, n // 7), shutter.y + shutter.h // 5,
                                          max(2, n // 9), shutter.h * 3 // 5))             # its slot
    label = pygame.Rect(body.x + body.w // 6, body.y + body.h * 11 // 20, body.w * 2 // 3, body.h * 11 // 30)
    pygame.draw.rect(icon, (245, 245, 250), label)                                          # the paper label
    pygame.draw.line(icon, (150, 160, 190), (label.x + 2, label.y + label.h // 3),
                     (label.right - 3, label.y + label.h // 3))
    screen.blit(icon, (x, y))


def draw_toast(pygame, screen, text: str, font_cache: dict):
    """Short status message (save states) across the top of the window."""
    sw, sh = screen.get_size()
    size = max(11, min(sw // 22, sh // 26))
    while True:
        if size not in font_cache:
            font_cache[size] = pygame.font.SysFont("verdana,dejavusans,tahoma,arial", size, bold=True)
        surf = font_cache[size].render(text, True, (255, 255, 255))
        if surf.get_width() + size * 2 <= sw * 0.96 or size <= 8:
            break
        size -= 1
    bw, bh = surf.get_width() + size * 2, surf.get_height() + size
    bx, by = (sw - bw) // 2, max(4, sh // 40)
    box = pygame.Surface((bw, bh), pygame.SRCALPHA)
    pygame.draw.rect(box, (24, 28, 52, 225), (0, 0, bw, bh), border_radius=6)
    pygame.draw.rect(box, (230, 200, 90, 255), (0, 0, bw, bh), width=2, border_radius=6)
    screen.blit(box, (bx, by))
    screen.blit(surf, (bx + size, by + size // 2))


def screenshot_label(path: str) -> str:
    """What the F12 message says: the file and the folder it is in, never a whole long path."""
    path = os.path.abspath(path)
    folder, name = os.path.split(path)
    parent = os.path.basename(folder)
    return f"Saved: {'.../' if os.path.dirname(folder) != folder else ''}{parent + '/' if parent else ''}{name}"


BACKDROP_SETTLE_S = 1.0         # focus changes this soon after the backdrop opens are its own doing


def open_backdrop(pygame, emu=None):
    """The "dark screen": a black borderless window over the whole monitor the game is on, put
    behind the game window, so nothing else on that screen distracts. Returns (backdrop, game
    window), or (None, None) if the window system will not do it (the game then just runs)."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            main = pygame.Window.from_display_module()
        back = pygame.Window("Kingdom Hearts Re:Cast backdrop", (320, 200), position=main.position,
                             borderless=True, utility=True)      # utility: no taskbar button of its own
        back.set_fullscreen(desktop=True)                        # the monitor the game window is on
        back.get_surface().fill((0, 0, 0))
        back.flip()
        main.focus()                                             # the game window goes back on top
        return back, main
    except Exception as e:                                       # old pygame, no multi-window support...
        if emu is not None:
            emu.log(f"[frontend] dark screen not available ({e})")
        return None, None


STARTUP_FOCUS_CHECK_S = 1.0     # how long a new window gets to be given focus before it is judged unfocused


def window_unfocused(pygame) -> bool:
    """True if the window is on screen but does not have the keyboard focus. A window that
    opens behind another one never gets a focus-lost event, so it is checked once at startup.
    The dummy and offscreen drivers (tests, servers) never have focus and are not judged."""
    try:
        if pygame.display.get_driver() in ("dummy", "offscreen", "evdev"):
            return False
        return not pygame.key.get_focused()
    except pygame.error:
        return False


def run_window(emu, scale: int = 0, title: str = "Kingdom Hearts Re:Cast", shots_dir: str = ".",
               slot: int = 1, autosave: bool = True, filt: str = "nearest", pause_on_focus_loss: bool = True,
               dark_screen: bool = False, ask_before_quit: bool = True, remember_no_quit_prompt=None):
    """scale 0 = pick automatically. The window can be resized or maximised;
    the picture keeps the phone's aspect ratio (black bars fill the rest)."""
    from .savestate import StateError, StateSlots
    make_dpi_aware()
    import pygame
    pygame.display.init()
    pygame.font.init()
    w, h = emu.screen
    if not scale:
        scale = auto_scale(pygame, w, h)
    set_app_id("khvcemu.game")
    png = icon_file("png")
    if png:
        try:
            pygame.display.set_icon(pygame.transform.smoothscale(pygame.image.load(png), (64, 64)))
        except (pygame.error, OSError):
            pass
    screen = pygame.display.set_mode((w * scale, h * scale), pygame.RESIZABLE)
    pygame.display.set_caption(title)
    backdrop, game_window = open_backdrop(pygame, emu) if dark_screen else (None, None)
    backdrop_settles = time.monotonic() + BACKDROP_SETTLE_S   # opening it briefly takes the focus
    emu.log(f"[frontend] window {w * scale}x{h * scale} (scale {scale}); drag the edges or maximise to resize")
    keymap = build_keymap(pygame)
    dirty = [True]
    emu.frame_listeners.append(lambda f: dirty.__setitem__(0, True))
    down: dict = {}
    muted = False
    filt = filt if filt in FILTERS else "nearest"
    last_present = 0.0
    running = True
    paused_at = None            # monotonic time the quit prompt opened, else None
    focus_lost_at = None        # monotonic time the window lost focus, else None (the game is held still)
    focus_lost = {getattr(pygame, n) for n in ("WINDOWFOCUSLOST", "WINDOWMINIMIZED") if hasattr(pygame, n)}
    focus_gained = {getattr(pygame, n) for n in ("WINDOWFOCUSGAINED", "WINDOWRESTORED") if hasattr(pygame, n)}
    focus_check_at = time.monotonic() + STARTUP_FOCUS_CHECK_S   # one look at startup
    font_cache: dict = {}
    slots = StateSlots(emu)
    slots.slot = slot
    slots.autosave_enabled = autosave
    toast = ["", 0.0]           # text, monotonic time it disappears
    mute_icon = [None, 0.0]     # muted or not, monotonic time the speaker icon disappears
    save_icon = [0.0]           # monotonic time the floppy disc (autosaved) disappears; 0 = not shown
    played = [False]            # a game key was pressed since the last state save/load:
                                # idle time (e.g. sitting on the title) never rotates autosaves
    lm_screens: list = []       # khvcemu's own "Wonderland is lost media" pages still to show
    lm_state = {"t0": 0.0, "prompt": 0.0, "release": 0.0}
    prompt_total = [0.0]        # seconds spent in the quit prompt (kept out of the clock shift)

    def start_lost_media():
        """Continue was pressed on the Wonderland splash: show khvcemu's pages first.
        The game stays frozen; its Continue press is delivered after the last page."""
        from .lostmedia import build_screens
        try:
            pages = build_screens(pygame, getattr(emu, "font_name", None) or emu.display.FONT_CANDIDATES, 9)
        except Exception as e:
            emu.log(f"[frontend] lost-media screens unavailable: {e}")
            emu.wonderland_splash_up = False
            return False
        for key in list(down):
            emu.key_up(AVK[down.pop(key)])
        lm_screens[:] = pages
        lm_state["t0"], lm_state["prompt"] = time.monotonic(), prompt_total[0]
        dirty[0] = True
        return True

    def next_lost_media_page():
        lm_screens.pop(0)
        dirty[0] = True
        if lm_screens:
            return
        if emu.realtime:                                # the game didn't see the time these pages were up
            emu._t0 += (time.monotonic() - lm_state["t0"]) - (prompt_total[0] - lm_state["prompt"])
        emu.wonderland_splash_up = False
        emu.key_down(AVK["SOFT1"])                      # now let the game have its Continue
        lm_state["release"] = time.monotonic() + 0.15

    def show(msg: str, secs: float = 2.5, tag: str = "state"):
        toast[0], toast[1] = msg, time.monotonic() + secs
        dirty[0] = True
        emu.log(f"[{tag}] {msg}")

    def state_action(fn) -> None:
        """Save/load/autosave between guest calls; the clock is held still while
        the file is written so the game doesn't skip ahead."""
        t = time.monotonic()
        try:
            msg = fn()
        except (StateError, OSError) as e:
            msg = f"Failed: {e}"
            if fn == slots.autosave:
                slots.last_auto_ms = emu.clock_ms()   # try again in a while, not on every pass of the loop
        if fn != slots.load and emu.realtime:
            emu._t0 += time.monotonic() - t
        if not msg.startswith(("Failed", "Slot 0")) and "empty" not in msg:
            played[0] = False
        if fn == slots.autosave and msg == "Autosaved":
            # autosaves are frequent: a floppy disc in the corner, not a message over the dialogue
            save_icon[0] = time.monotonic() + SAVE_ICON_SECS
            dirty[0] = True
            emu.log(f"[state] {msg}")
        else:
            show(msg)

    def lose_focus():
        """The window is in the background: hold the game still, like the quit prompt does, so
        time away is not play time. Does nothing if the quit prompt or khvcemu's own pages
        already hold the clock, since both would then be shifted for the same minutes."""
        nonlocal focus_lost_at
        if not pause_on_focus_loss:                  # the Options tab's "Pause when the window loses focus"
            return
        if focus_lost_at is not None or paused_at is not None or lm_screens:
            return
        focus_lost_at = time.monotonic()
        for key in list(down):                       # don't leave keys stuck held in the game
            emu.key_up(AVK[down.pop(key)])
        mixer = getattr(emu.audio, "mixer", None)
        if mixer is not None:
            mixer.pause()
        dirty[0] = True

    def regain_focus():
        nonlocal focus_lost_at
        if focus_lost_at is None:
            return
        if emu.realtime:
            emu._t0 += time.monotonic() - focus_lost_at
        focus_lost_at = None
        mixer = getattr(emu.audio, "mixer", None)
        if mixer is not None:
            mixer.unpause()
        dirty[0] = True

    def request_quit():
        """Esc or the window's X: ask first, unless the player turned the question off."""
        nonlocal running
        if ask_before_quit:
            open_prompt()
        else:
            running = False

    def open_prompt():
        nonlocal paused_at, focus_lost_at
        # a prompt opened while the window was in the background takes over that pause, so the
        # time already held still is shifted once, when the prompt closes
        paused_at = focus_lost_at if focus_lost_at is not None else time.monotonic()
        focus_lost_at = None
        for key in list(down):                       # don't leave keys stuck held in the game
            emu.key_up(AVK[down.pop(key)])
        mixer = getattr(emu.audio, "mixer", None)
        if mixer is not None:
            mixer.pause()
        dirty[0] = True

    def close_prompt():
        """Resume: push the emulator clock back by the time spent paused so the
        game and its timers carry on exactly where they stopped."""
        nonlocal paused_at
        if emu.realtime:
            emu._t0 += time.monotonic() - paused_at
        prompt_total[0] += time.monotonic() - paused_at
        paused_at = None
        mixer = getattr(emu.audio, "mixer", None)
        if mixer is not None:
            mixer.unpause()
        dirty[0] = True

    while running and not emu.exit_requested:
        for ev in pygame.event.get():
            if backdrop is not None:
                if getattr(getattr(ev, "window", None), "id", None) == backdrop.id:
                    if ev.type == pygame.WINDOWFOCUSGAINED:      # clicked: the game window stays in front
                        game_window.focus()
                    continue                                     # nothing else the backdrop does is the game's
                if ev.type == getattr(pygame, "WINDOWCLOSE", -1):
                    # with two windows open SDL sends no QUIT for the X button, only this: the
                    # game window's X must still ask "Quit the game?"
                    ev = pygame.event.Event(pygame.QUIT)
                if (ev.type in focus_lost and ev.type != getattr(pygame, "WINDOWMINIMIZED", -1)
                        and time.monotonic() < backdrop_settles):
                    continue                                     # the backdrop's own opening, not the player leaving
                if ev.type == getattr(pygame, "WINDOWMINIMIZED", -1):
                    backdrop.hide()                              # minimising the game must not leave a black screen
                elif ev.type == getattr(pygame, "WINDOWRESTORED", -1):
                    backdrop.show()
                    game_window.focus()
            if ev.type in focus_lost:
                lose_focus()
                continue
            if ev.type in focus_gained:
                regain_focus()
                continue
            if paused_at is not None:                # quit prompt is open
                if ev.type == pygame.QUIT:
                    running = False                  # closing the window twice forces it shut
                elif ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                        running = False
                    elif ev.key == pygame.K_d:           # quit, and never ask again
                        if remember_no_quit_prompt is not None:
                            remember_no_quit_prompt()
                        running = False
                    elif ev.key in (pygame.K_ESCAPE, pygame.K_n):
                        close_prompt()
                elif ev.type in (pygame.VIDEORESIZE, getattr(pygame, "WINDOWSIZECHANGED", -1),
                                 getattr(pygame, "WINDOWEXPOSED", -1)):
                    dirty[0] = True
                continue
            if lm_screens:                           # khvcemu's Wonderland pages are up
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    request_quit()
                elif ev.type == pygame.KEYDOWN and keymap.get(ev.key) in ("SOFT1", "SELECT"):
                    next_lost_media_page()
                elif ev.type in (pygame.VIDEORESIZE, getattr(pygame, "WINDOWSIZECHANGED", -1),
                                 getattr(pygame, "WINDOWEXPOSED", -1)):
                    screen = pygame.display.get_surface()
                    dirty[0] = True
                continue
            if ev.type == pygame.QUIT:
                request_quit()
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    request_quit()
                elif ev.key == pygame.K_F10:
                    muted = not muted
                    emu.audio.master_volume = 0.0 if muted else 1.0
                    for v in emu.audio.voices:
                        emu.audio.set_volume(v, v.volume)
                    mute_icon[0], mute_icon[1] = muted, time.monotonic() + MUTE_ICON_SECS
                    dirty[0] = True
                    emu.log("[frontend] sound " + ("muted" if muted else "on") + "  (F10)")
                elif ev.key == pygame.K_F11:
                    filt = FILTERS[(FILTERS.index(filt) + 1) % len(FILTERS)]
                    show(f"Picture: {FILTER_NAMES[filt]}  (F11)", tag="frontend")
                elif ev.key == pygame.K_F12 and emu.last_frame is not None:
                    path = os.path.join(shots_dir, time.strftime("khvcemu_%Y%m%d_%H%M%S.png"))
                    img = to_rgb(emu.last_frame)
                    try:
                        os.makedirs(shots_dir, exist_ok=True)
                        pygame.image.save(pygame.surfarray.make_surface(img.transpose(1, 0, 2)), path)
                        show(screenshot_label(path) + "  (F12)", tag="frontend")
                        emu.log(f"[frontend] screenshot saved to {path}")
                    except (OSError, pygame.error) as e:
                        show("Screenshot failed: " + str(e)[:40], tag="frontend")
                elif ev.key == pygame.K_F5:
                    state_action(slots.save)
                elif ev.key == pygame.K_F9:
                    state_action(slots.load)
                    for key in list(down):            # load_state already released them in-game
                        down.pop(key)
                elif ev.key in (pygame.K_F6, pygame.K_F7):
                    order = list(range(1, 10)) + [0]  # slots 1-9, then 0 = the autosave
                    step = 1 if ev.key == pygame.K_F7 else -1
                    slots.slot = order[(order.index(slots.slot) + step) % len(order)]
                    show(slots.describe(slots.slot) + "   (F5 save, F9 load)")
                elif ev.key == pygame.K_F8:
                    slots.autosave_enabled = not slots.autosave_enabled
                    show("Autosave on (every 5 minutes)" if slots.autosave_enabled else "Autosave off")
                elif ev.mod & pygame.KMOD_SHIFT and pygame.K_0 <= ev.key <= pygame.K_9:
                    slots.slot = ev.key - pygame.K_0  # Shift+digit picks a slot (plain digits are phone keys)
                    show(slots.describe(slots.slot) + "   (F5 save, F9 load)")
                elif emu.wonderland_splash_up and keymap.get(ev.key) == "SOFT1" and start_lost_media():
                    played[0] = True
                elif ev.key in keymap and ev.key not in down:
                    played[0] = True
                    down[ev.key] = keymap[ev.key]
                    emu.key_down(AVK[keymap[ev.key]])
            elif ev.type == pygame.KEYUP and ev.key in down:
                emu.key_up(AVK[down.pop(ev.key)])
            elif ev.type in (pygame.VIDEORESIZE, getattr(pygame, "WINDOWSIZECHANGED", -1),
                             getattr(pygame, "WINDOWEXPOSED", -1)):
                screen = pygame.display.get_surface()
                dirty[0] = True
        if focus_check_at is not None and time.monotonic() >= focus_check_at:
            focus_check_at = None
            if window_unfocused(pygame):             # opened behind another window: no event will come
                lose_focus()
        if lm_state["release"] and time.monotonic() >= lm_state["release"]:
            lm_state["release"] = 0.0
            emu.key_up(AVK["SOFT1"])
        if paused_at is None and not lm_screens and focus_lost_at is None:
            if slots.autosave_due():
                if played[0]:
                    state_action(slots.autosave)
                else:
                    slots.last_auto_ms = emu.clock_ms()   # idle: check again next period
            if slots.area_save_due():                 # a new area has finished loading
                emu.last_loading_ms = None
                if played[0] and slots.area_save_allowed():
                    state_action(slots.autosave)
            emu.run_due()
        now = time.monotonic()
        if toast[0] and now >= toast[1]:
            toast[0] = ""
            dirty[0] = True
        if mute_icon[0] is not None and now >= mute_icon[1]:
            mute_icon[0] = None
            dirty[0] = True
        if save_icon[0] and now >= save_icon[0]:
            save_icon[0] = 0.0
            dirty[0] = True
        if dirty[0] and emu.last_frame is not None and now - last_present > 1 / 60:
            dirty[0] = False
            last_present = now
            screen = pygame.display.get_surface()
            draw_frame(pygame, emu, screen, w, h, override=lm_screens[0] if lm_screens else None,
                       filt=filt)
            if toast[0]:
                draw_toast(pygame, screen, toast[0], font_cache)
            if mute_icon[0] is not None:
                draw_mute_icon(pygame, screen, mute_icon[0])
            if save_icon[0]:
                draw_save_icon(pygame, screen)
            if paused_at is not None:
                draw_quit_prompt(pygame, screen, font_cache)
            elif focus_lost_at is not None:
                draw_pause_label(pygame, screen, font_cache)
            pygame.display.flip()
        if paused_at is not None or lm_screens or focus_lost_at is not None:
            time.sleep(0.01)
            continue
        due = emu.next_due()
        wait = 0.002 if due is None else (due - emu.clock_ms()) / 1000
        if wait > 0.001:
            time.sleep(min(wait, 0.005))
    if emu.applet_ptr and not emu.exit_requested and played[0] and slots.autosave_enabled:
        # leaving mid-game (Esc / window close): keep one more autosave
        try:
            slots.autosave()
            emu.log("[state] autosaved on exit (load it with Shift+0 then F9, or --load-state auto)")
        except Exception as e:
            emu.log(f"[state] autosave on exit failed: {e}")
    emu.stop()
    emu.audio.stop_all()
    if backdrop is not None:
        try:
            backdrop.destroy()
        except Exception:
            pass
    pygame.quit()
