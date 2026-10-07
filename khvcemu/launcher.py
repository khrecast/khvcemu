"""Friendly launcher: pick the game folder, check/install requirements, then
play, resume a save state or start at a world. Settings are remembered.

    python -m khvcemu.launcher        (or double-click "Launch khvcemu.bat")

Uses only tkinter (part of Python), so it runs even before the emulator's own
requirements are installed, and can install them.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import keys as keymod
from . import music_settings, swerve_patch
from .paths import data_home, find_wonderland_music, icon_file, no_window, set_app_id, use_bundled_tools

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(data_home(), "launcher.json")
PACKAGES = (("unicorn", "unicorn"), ("pygame", "pygame-ce"), ("numpy", "numpy"))
SLOTS = [(str(i), f"Slot {i}") for i in range(1, 10)] + \
        [("auto", "Autosave (newest)"), ("auto2", "Autosave 2"), ("auto3", "Autosave 3")]


# --------------------------------------------------------------------------- helpers
def load_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def is_dump(folder: str) -> bool:
    return bool(folder) and os.path.isdir(os.path.join(folder, "mif")) and os.path.isdir(os.path.join(folder, "mod"))


def find_dump() -> str:
    """Guess the game folder: the project folder itself, or a sub-folder of it."""
    if is_dump(PROJECT):
        return PROJECT
    for name in sorted(os.listdir(PROJECT)):
        p = os.path.join(PROJECT, name)
        if is_dump(p):
            return p
    return ""


def missing_packages() -> list:
    return [pip for mod, pip in PACKAGES if importlib.util.find_spec(mod) is None]


def data_dir_for(dump: str) -> str:
    from .paths import game_data_dir         # stdlib-only module, safe to import
    return game_data_dir(dump)


def slot_file(dump: str, slot: str) -> str:
    name = {"auto": "auto1"}.get(slot, slot if slot.startswith("auto") else f"slot{slot}")
    return os.path.join(data_dir_for(dump), "states", name + ".khs")


def saved_world(dump: str):
    """(world, when) that Load Game will continue, read from savegame.dat."""
    p = os.path.join(data_dir_for(dump), "files", "savegame.dat")
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError:
        return None, None
    for w in ("training", "island", "wonderland", "agrabah", "castle"):
        if w.encode() in data:
            when = time.strftime("%b %d, %H:%M", time.localtime(os.path.getmtime(p)))
            return w, when
    return None, None


def world_saves(dump: str) -> list:
    out = []
    for fn in sorted(os.listdir(dump)) if os.path.isdir(dump) else []:
        low = fn.lower()
        if low.startswith("savegame(") and low.endswith(").dat"):
            w = low[len("savegame("):-len(").dat")]
            out.append({"maleficient": "castle", "maleficent": "castle"}.get(w, w))
    return out


def clean_minutes(value, default: float = 5.0) -> float:
    """The autosave interval typed on the Saves tab: 1 to 120 minutes (a whole or half number), else the default."""
    try:
        m = float(str(value).strip().replace(",", "."))
    except ValueError:
        return default
    if m != m or m in (float("inf"), float("-inf")):          # nan and infinity are not minutes
        return default
    return min(120.0, max(1.0, round(m * 2) / 2))


def fit_photo(img, box_w: int, box_h: int):
    """A Tk picture scaled to fit a box: Tk scales by whole numbers only (zoom by up, shrink by down), so this is the
    biggest fraction with a denominator up to 16 that still fits, never above 1x."""
    scale = min(box_w / img.width(), box_h / img.height(), 1.0)
    best = max(((int(scale * d) / d, int(scale * d), d) for d in range(1, 17) if int(scale * d) >= 1),
               default=(1 / 16, 1, 16))
    up, down = best[1], best[2]
    return img.zoom(up, up).subsample(down, down) if up > 1 else img.subsample(down, down)


def shot_label(filename: str) -> str:
    """A short list entry for a screenshot: khvcemu_20261004_214135.png reads "Oct 04  21:41:35"; any other file name
    is shown as it is."""
    m = re.fullmatch(r"khvcemu_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:[-_]\d+)?\.\w+", filename)
    if m:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        if 1 <= mo <= 12:
            return f"{MONTHS[mo - 1]} {d:02d}  {h:02d}:{mi:02d}:{s:02d}"
    return filename


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# 16x16 pixel pictures for the small buttons: . transparent, o outline, y folder, Y folder front,
# b sky, g hill, s sun
ICONS = {
    "folder": ("................", "................", "..oooo..........", ".oyyyyo.........", ".oyyyyoooooooo..",
               ".oyyyyyyyyyyyyo.", ".oyyyyyyyyyyyyo.", ".oyyyyyyyyyyyyo.", ".oYYYYYYYYYYYYo.", ".oYYYYYYYYYYYYo.",
               ".oYYYYYYYYYYYYo.", ".oYYYYYYYYYYYYo.", "..oooooooooooo..", "................", "................",
               "................"),
    "picture": ("................", ".oooooooooooooo.", ".obbbbbbbbbbbbo.", ".obbbbbbssbbbbo.", ".obbbbbbssbbbbo.",
                ".obbbbbbbbbbbbo.", ".obbbgbbbbbbbbo.", ".obbgggbbbggbbo.", ".obgggggbgggggo.", ".oggggggggggggo.",
                ".oggggggggggggo.", ".oooooooooooooo.", "................", "................", "................",
                "................"),
}
ICONS["info"] = ("......bbbb......", "....bbbbbbbb....", "...bbbbwwbbbb...", "..bbbbbwwbbbbb..", ".bbbbbbbbbbbbbb.",
                 ".bbbbbwwwbbbbbb.", "bbbbbbbwwbbbbbbb", "bbbbbbbwwbbbbbbb", "bbbbbbbwwbbbbbbb", "bbbbbbbwwbbbbbbb",
                 ".bbbbbbwwbbbbbb.", ".bbbbbwwwwbbbbb.", "..bbbbbbbbbbbb..", "...bbbbbbbbbb...", "....bbbbbbbb....",
                 "......bbbb......")
ICONS["delete"] = ("................", "................", "..rr........rr..", "..rrr......rrr..", "...rrr....rrr...",
                   "....rrr..rrr....", ".....rrrrrr.....", "......rrrr......", "......rrrr......", ".....rrrrrr.....",
                   "....rrr..rrr....", "...rrr....rrr...", "..rrr......rrr..", "..rr........rr..", "................",
                   "................")
ICON_COLORS = {"r": "#e5645b", "w": "#ffffff", "o": "#3a4a63", "y": "#f2c94c", "Y": "#d9a92a", "b": "#2f80ed", "g": "#58c46b", "s": "#ffe9a6"}


def make_icon(name: str):
    """A small button picture drawn from ICONS (no image files to ship)."""
    img = tk.PhotoImage(width=16, height=16)
    for y, row in enumerate(ICONS[name]):
        for x, ch in enumerate(row):
            if ch == ".":
                img.tk.call(img, "transparency", "set", x, y, True)
            else:
                img.put(ICON_COLORS[ch], to=(x, y))
    return img


def to_trash(path: str) -> bool:
    """Delete a file: to the Recycle Bin on Windows (it can be restored from there), for good elsewhere.
    Returns True when the file is gone."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class SHFILEOPSTRUCTW(ctypes.Structure):
            if ctypes.sizeof(ctypes.c_void_p) == 4:
                _pack_ = 1                 # shellapi.h packs it to 1 byte on 32-bit Windows
            _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR), ("pTo", wt.LPCWSTR),
                        ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wt.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wt.LPCWSTR)]
        # FO_DELETE; FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI. pFrom ends in two NULs.
        op = SHFILEOPSTRUCTW(None, 3, os.path.abspath(path) + "\0", None, 0x40 | 0x10 | 0x4 | 0x400, False, None, None)
        try:
            ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        except OSError:
            pass
        return not os.path.exists(path)
    try:
        os.remove(path)
    except OSError:
        pass
    return not os.path.exists(path)


def music_cache_dir(dump: str) -> str:
    """Where the game keeps the tunes the built-in synth has rendered (audio.AudioEngine.cache_dir)."""
    return os.path.join(data_dir_for(dump), "audio_cache")


def music_cache_size(dump: str) -> tuple:
    """(number of rendered tunes kept, bytes they take)."""
    folder = music_cache_dir(dump)
    count = size = 0
    try:
        for fn in os.listdir(folder):
            if fn.endswith(".npy"):
                count += 1
                size += os.path.getsize(os.path.join(folder, fn))
    except OSError:
        pass
    return count, size


def clear_music_cache(dump: str) -> int:
    """Delete the rendered tunes (and any half-written ones); the game renders them again when needed."""
    folder = music_cache_dir(dump)
    gone = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for fn in names:
        if fn.endswith(".npy") or fn.endswith(".tmp"):
            try:
                os.remove(os.path.join(folder, fn))
                gone += fn.endswith(".npy")
            except OSError:
                pass
    return gone


def open_in_viewer(path: str):
    """Open a file or folder with the system's own program for it."""
    try:
        if sys.platform == "win32":
            os.startfile(path)                                    # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **no_window())
    except OSError:
        pass


def build_command(dump: str, opts: dict, load_state: str = None, start: str = None) -> list:
    cmd = [sys.executable, "-m", "khvcemu", dump]
    if opts.get("scale"):
        cmd += ["--scale", str(opts["scale"])]
    if opts.get("mute"):
        cmd.append("--mute")
    if opts.get("font_size") and int(opts["font_size"]) != 11:
        cmd += ["--font-size", str(opts["font_size"])]
    if opts.get("filter") and opts["filter"] != "nearest":
        cmd += ["--filter", opts["filter"]]
    if opts.get("hires_text"):
        cmd.append("--hires-text")
    if opts.get("soundfont"):
        cmd += ["--soundfont", opts["soundfont"]]
    if opts.get("music"):
        cmd += ["--music", opts["music"]]
    for name, path, gain in opts.get("music_files") or ():     # recordings played instead of a tune
        cmd += ["--music-file", f"{name}={path}"]
        if abs(gain - 1.0) > 1e-9:
            cmd += ["--music-file-volume", f"{name}={round(gain, 3):g}"]
    if abs(float(opts.get("wonderland_volume", 1.0)) - 1.0) > 1e-9:
        cmd += ["--wonderland-volume", f"{round(float(opts['wonderland_volume']), 3):g}"]
    timed, on_quit, on_loading = (opts.get("autosave", True), opts.get("autosave_on_quit", True),
                                  opts.get("autosave_on_loading", True))
    if not (timed or on_quit or on_loading):
        cmd.append("--no-autosave")
    else:
        minutes = clean_minutes(opts.get("autosave_minutes", 5))
        if not timed:
            cmd += ["--autosave-every", "0"]
        elif minutes != 5:
            cmd += ["--autosave-every", f"{minutes:g}"]
        if not on_quit:
            cmd.append("--no-autosave-on-quit")
        if not on_loading:
            cmd.append("--no-autosave-on-loading")
    if not opts.get("pause_on_focus_loss", True):
        cmd.append("--no-focus-pause")
    if opts.get("screenshots"):
        cmd += ["--screenshots", opts["screenshots"]]
    if opts.get("dark_screen"):
        cmd.append("--dark-screen")
    for action, key in (opts.get("custom_keys") or {}).items():       # the Controls tab's changed keys
        if action in keymod.DEFAULT_KEYS and key in keymod.ALLOWED_KEYS and key != keymod.DEFAULT_KEYS[action]:
            cmd += ["--key", f"{action}={key}"]
    off = [n for n in swerve_patch.NAMES if n in (opts.get("speed_patches_off") or ())]
    if off:                                                  # the 3D engine speed-ups (same picture), each can be off
        cmd += ["--no-speed-patch", ",".join(off)]
    if not opts.get("ask_before_quit", True):
        cmd.append("--no-quit-prompt")
    if opts.get("leaderboard"):
        cmd += ["--leaderboard", opts["leaderboard"]]
    if load_state:
        cmd += ["--load-state", load_state]
    elif start:
        cmd += ["--start", start]
    return cmd


# The defaults of the Options tab ("Restore default settings" puts these back) and of the Saves tab's autosave
# settings (which that button leaves alone). Not the game folder, the saves, the Sound tab (its music sliders, mixes,
# recordings and SoundFont: the "As tuned" mix resets the sliders).
OPTION_DEFAULTS = {"scale": "Auto", "font_size": 11, "mute": False, "hires_text": False,
                   "filter": "nearest", "autosave": True, "autosave_minutes": 5, "autosave_on_quit": True,
                   "autosave_on_loading": True, "pause_on_focus_loss": True, "screenshots": "",
                   "ask_before_deleting_screenshot": True,
                   "dark_screen": False, "ask_before_quit": True, "share_scores": True,
                   "leaderboard_url": "", "speed_patches_off": []}


def fluidsynth_found() -> bool:
    """A SoundFont is only used when the fluidsynth program is installed (audio.AudioEngine)."""
    return shutil.which("fluidsynth") is not None


MIN_WIDTH = 620          # the window never goes narrower than this
THUMB_W, THUMB_H = 118, 148       # the Saves tab's preview of a save state (a 176x220 frame at two thirds)
SHOT_W, SHOT_H = 110, 138         # the screenshot preview box (a 176x220 frame at five eighths)
SHOT_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
SHOTS_LISTED = 300                # the most recent screenshots shown in the Options tab list
SHOT_MAX_BYTES = 8_000_000        # bigger pictures are listed but not previewed (loading one would stall the window)
STATES_POLL_MS = 5000    # how often the save-state list is checked for changes made by the game

# The shared high-score server; the launcher only switches sharing on or off
LEADERBOARD_URL = "https://scores.khrecast.com"

def clean_leaderboard_url(text: str) -> str:
    """What to send scores to: the box's text with a scheme added if it is missing, or the
    default server when the box is empty."""
    t = (text or "").strip().rstrip("/")
    if not t:
        return LEADERBOARD_URL
    return t if "://" in t else "https://" + t


# Picture filters, as named in the launcher (same keys as --filter / frontend.FILTERS)
PICTURE_FILTERS = {"nearest": "Pixels (crisp)", "smooth": "Smooth", "sharp": "Sharp pixels",
                   "scale2x": "Scale2x (rounded edges)"}

# Shown in the collapsible Controls section: (in-game action, keys, emulator action, keys)
CONTROLS = [
    ("Move",            "WASD / arrows / NumPad", "Save / load",       "F5 / F9"),
    ("Action, attack",  "Enter / Space / 5",      "Change slot",       "F6 / F7"),
    ("Magic",           "F / [ / *",              "Autosave",          "F8"),
    ("Status + items",  "Z / 0",                  "Mute / screenshot", "F10 / F12"),
    ("Pause, Continue", "Q / F1",                 "Quit",              "Esc"),
    ("Back, Options",   "E / F2",                 "Picture filter",    "F11"),
]


# --------------------------------------------------------------------------- look
# Dark navy with the blue and green of the game's HUD ring
BG, PANEL, FIELD = "#0b1626", "#13253c", "#0f1d31"
TEXT, MUTED, DIM = "#e9f0fa", "#8ea4bf", "#5d7391"
BLUE, GREEN = "#2f80ed", "#58c46b"
# Shown at the top of the launcher; site/index.html carries the same words (a test keeps them equal)
DISCLAIMER = (
    "Kingdom Hearts and all related characters, names and assets belong to their respective rights holders. This is an unofficial fan project and is not affiliated with, endorsed by or connected to Disney, Square Enix, Superscape, Verizon, Qualcomm or any other rights holder. It exists only to preserve, and let people experience, a piece of gaming history. It is free and non-profit: nobody earns money from it, and it should never be sold.")

WORLD_TITLES = {"training": "Obstacle Course", "island": "Swashbuckler's Island", "wonderland": "Wonderland",
                "agrabah": "Agrabah", "castle": "Maleficent's Castle"}
WORLD_NAMES = {"training": "the Obstacle Course", "island": "Swashbuckler's Island",
               "wonderland": "Wonderland (then Agrabah)", "agrabah": "Agrabah",
               "castle": "Maleficent's Castle"}


def newest_state(dump: str):
    """(slot key, label, path, mtime) of the most recently written save state, or None."""
    best = None
    if is_dump(dump):
        for key, label in SLOTS:
            p = slot_file(dump, key)
            if os.path.isfile(p):
                m = os.path.getmtime(p)
                if best is None or m > best[3]:
                    best = (key, label, p, m)
    return best


LOGO_FILE = os.path.join(PROJECT, "khvcemu", "assets", "recast_logo_lowres_hardpixels.png")


TAB_LABELS_DIR = os.path.join(PROJECT, "khvcemu", "assets", "tabs")


def load_tab_labels(keys) -> dict:
    """The tab names drawn in the Kingdom Hearts menu font (tools/make_tab_labels.py):
    {key: (idle image, selected image)}. A tab whose pictures are missing keeps plain text."""
    out = {}
    for key in keys:
        try:
            out[key] = (tk.PhotoImage(file=os.path.join(TAB_LABELS_DIR, f"{key}.png")),
                        tk.PhotoImage(file=os.path.join(TAB_LABELS_DIR, f"{key}_on.png")))
        except (tk.TclError, OSError):
            pass
    return out


def load_logo(path: str = LOGO_FILE, shrink: int = 4):
    """The Re:Cast logo for the header, or None. A missing or unreadable file just means
    the plain text header."""
    try:
        return tk.PhotoImage(file=path).subsample(shrink)       # whole-number steps keep hard pixels crisp
    except (tk.TclError, OSError):
        return None


def apply_theme(root: tk.Tk):
    st = ttk.Style()
    try:
        st.theme_use("clam")                 # the only built-in theme that takes custom colors
    except tk.TclError:
        pass
    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    st.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=PANEL,
                 lightcolor=PANEL, darkcolor=PANEL, troughcolor=FIELD, focuscolor=BLUE,
                 insertcolor=TEXT, font=("Segoe UI", 10))
    st.configure("TLabelframe", background=BG, bordercolor=PANEL, relief="solid")
    st.configure("TLabelframe.Label", background=BG, foreground=MUTED)
    st.configure("TButton", background=PANEL, foreground=TEXT, bordercolor=PANEL, padding=(10, 5), relief="flat")
    st.map("TButton", background=[("disabled", BG), ("pressed", BLUE), ("active", "#1b3555")],
           foreground=[("disabled", DIM)])
    st.configure("Accent.TButton", background=BLUE, foreground="white", font=("Segoe UI", 12, "bold"),
                 padding=(14, 8))
    st.map("Accent.TButton", background=[("disabled", "#1c3050"), ("pressed", "#1d5fc0"), ("active", "#4693ff")],
           foreground=[("disabled", DIM)])
    st.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT)
    st.map("TEntry", fieldbackground=[("readonly", FIELD), ("disabled", BG)], foreground=[("disabled", DIM)])
    st.configure("TCombobox", fieldbackground=FIELD, background=PANEL, foreground=TEXT, arrowcolor=TEXT)
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
    st.configure("TSpinbox", fieldbackground=FIELD, background=PANEL, foreground=TEXT, arrowcolor=TEXT)
    st.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=FIELD,
                 indicatorforeground=GREEN)
    st.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", FIELD)])
    st.configure("Small.TButton", padding=(8, 1))
    st.configure("SmallOn.TButton", padding=(8, 1), background=BLUE, foreground="white")   # what is playing
    st.map("SmallOn.TButton", background=[("active", "#4693ff"), ("pressed", "#1d5fc0")])
    st.configure("Soft.TButton", background="#1d3a5c", foreground=TEXT, padding=(12, 8))
    st.map("Soft.TButton", background=[("disabled", BG), ("pressed", BLUE), ("active", "#27507e")],
           foreground=[("disabled", DIM)])
    st.configure("TNotebook", background=BG, bordercolor=PANEL, tabmargins=(0, 2, 0, 0))
    st.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 6), bordercolor=PANEL)
    st.map("TNotebook.Tab", background=[("selected", BLUE), ("active", "#1b3555")],
           foreground=[("selected", "white"), ("active", TEXT)])
    # a grayed-out slider must look off: dark thumb and trough, not the light thumb of a live one
    st.configure("Horizontal.TScale", background="#cfdcee", lightcolor="#5d7391", darkcolor="#5d7391")
    st.map("Horizontal.TScale", background=[("disabled", "#1a2b42")], troughcolor=[("disabled", BG)],
           bordercolor=[("disabled", BG)], lightcolor=[("disabled", "#1a2b42")],
           darkcolor=[("disabled", "#1a2b42")])
    st.configure("Card.TFrame", background=PANEL)
    st.configure("Card.TLabel", background=PANEL, foreground=TEXT)
    st.configure("Muted.TLabel", background=PANEL, foreground=MUTED)


# --------------------------------------------------------------------------- window
class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.proc = None
        self.output: list = []
        self.thumb = None
        root.title("Kingdom Hearts Re:Cast")
        set_app_id("khvcemu.launcher")
        png = icon_file("png")
        if png:
            try:
                self.icon = tk.PhotoImage(file=png).subsample(4)      # 64 px, kept to stay alive
                root.iconphoto(True, self.icon)
            except tk.TclError:
                pass
        apply_theme(root)
        self.hero_thumb = None

        head = ttk.Frame(root)
        head.pack(fill="x", padx=12, pady=(10, 0))
        self.logo = load_logo()
        if self.logo:
            ttk.Label(head, image=self.logo).pack(side="left")
            ttk.Label(head, text="The Unofficial 2005 Kingdom Hearts Verizon V CAST Game Emulator", foreground=MUTED,
                      justify="left").pack(side="left", padx=(14, 0))
        else:
            ttk.Label(head, text="KINGDOM HEARTS", font=("Segoe UI", 20, "bold")).pack(anchor="w")
            ttk.Label(head, text="Re:Cast  •  the 2005 Verizon V CAST game, on your PC",
                      foreground=MUTED).pack(anchor="w")
        note = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground="#1d3a5c")
        note.pack(fill="x", padx=12, pady=(8, 0))
        tk.Frame(note, bg="#f2c94c", width=4).pack(side="left", fill="y")
        self.disclaimer = tk.Label(note, text=DISCLAIMER, bg=PANEL, fg=MUTED, justify="left", anchor="w",
                                   font=("Segoe UI", 8), wraplength=MIN_WIDTH - 70, padx=10, pady=6)
        self.disclaimer.pack(side="left", fill="x", expand=True)
        self.disclaimer.bind("<Configure>", lambda e: self.disclaimer.config(wraplength=max(e.width - 24, 200)))
        bar = tk.Canvas(root, height=3, bg=BG, highlightthickness=0)
        bar.pack(fill="x", padx=12, pady=(8, 8))
        bar.bind("<Configure>", lambda e: self.draw_bar(bar))
        # the status line sits at the bottom; everything else is a tab
        self.status = ttk.Label(root, text="", foreground=MUTED)
        self.status.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.tab_frames: dict = {}

        # the tab names in the game's menu font, blocky like the logo (plain text if missing)
        self.tab_labels = load_tab_labels(("play", "saves", "options", "sound", "setup", "setup_warn", "controls"))
        if self.tab_labels:
            ttk.Style().configure("TNotebook.Tab", padding=(8, 3))

        def tab(key, title):
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=title, padding=6)
            self.tab_frames[key] = frame
            self.set_tab_label(key, key)
            return frame

        # play: the front card
        self.build_hero(tab("play", "Play"))

        # play
        body = tab("saves", "Saves")
        top = ttk.Frame(body)
        top.pack(fill="both", expand=True)
        left = ttk.Frame(top)
        left.pack(side="left", fill="both", expand=True, padx=6, pady=(6, 2))
        ttk.Label(left, text="Save states (in game: F5 save, F9 load, F6/F7 change slot):",
                  foreground=MUTED).pack(anchor="w")
        self.slot_picked = False            # true once the player has chosen a row themselves
        slot_frame = ttk.Frame(left)
        slot_frame.pack(fill="both", expand=True)
        self.slots = tk.Listbox(slot_frame, height=6, activestyle="none", exportselection=False, bg=FIELD, fg=TEXT,
                                selectbackground=BLUE, selectforeground="white", highlightthickness=1,
                                highlightbackground=PANEL, highlightcolor=BLUE, relief="flat", bd=0)
        slot_bar = ttk.Scrollbar(slot_frame, orient="vertical", command=self.slots.yview)
        self.slots.configure(yscrollcommand=slot_bar.set)
        self.slots.pack(side="left", fill="both", expand=True)
        slot_bar.pack(side="left", fill="y")
        self.slots.bind("<<ListboxSelect>>", lambda e: self.slot_chosen())
        self.slots.bind("<Double-Button-1>", lambda e: self.resume())
        self.resume_btn = ttk.Button(left, text="Resume selected state", command=self.resume)
        self.resume_btn.pack(fill="x", pady=(4, 6))
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Label(row, text="Start at world:").pack(side="left")
        self.world = ttk.Combobox(row, state="readonly", width=12)
        self.world.pack(side="left", padx=6)
        self.world_btn = ttk.Button(row, text="Start", command=self.start_world)
        self.world_btn.pack(side="left")
        right = ttk.Frame(top)
        right.pack(side="left", fill="y", padx=6, pady=(6, 2))
        self.thumb_label = ttk.Label(right, text="(no preview)", anchor="center", width=18,
                                     foreground=MUTED)
        self.thumb_label.pack()
        self.slot_info = ttk.Label(right, text="", wraplength=180, justify="center",
                                    foreground=MUTED)
        self.slot_info.pack(pady=4)
        self.build_autosave(body)

        # options
        self.build_options(tab("options", "Options"))

        # sound: the built-in synth's sliders, with a player to hear them
        self.build_sound(tab("sound", "Sound"))

        # setup: the game folder and what the launcher needs
        body = tab("setup", "Setup")
        folder = ttk.LabelFrame(body, text="Game folder (contains mif and mod)")
        folder.pack(fill="x", pady=(2, 8))
        self.dump = tk.StringVar(value=self.cfg.get("dump") or find_dump())
        ttk.Entry(folder, textvariable=self.dump).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(folder, text="Browse...", command=self.browse).pack(side="left", padx=6)
        self.dump.trace_add("write", lambda *_: self.refresh())
        req = ttk.LabelFrame(body, text="Requirements")
        req.pack(fill="x")
        self.req_label = ttk.Label(req, text="", wraplength=470, justify="left")
        self.req_label.pack(side="left", padx=6, pady=6, fill="x", expand=True)
        self.install_btn = ttk.Button(req, text="Install", command=self.install)
        self.build_wonderland(body)

        # controls: a two-column key table
        self.build_controls(tab("controls", "Controls"))

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.sync_share()
        self.refresh()
        saved = self.cfg.get("tab")
        if self.setup_needed:
            self.tabs.select(self.tab_frames["setup"])      # nothing works until this is sorted
        elif saved in self.tab_frames:
            self.tabs.select(self.tab_frames[saved])
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        self._watch_timer = self.root.after(STATES_POLL_MS, self.watch_states)
        self.root.bind("<Destroy>", self.window_gone, add="+")
        # looking at the launcher is when a stale list would be noticed, so check right then
        self.root.bind("<Button-1>", lambda e: self.check_states(), add="+")
        self.root.bind("<FocusIn>", lambda e: self.check_states() if e.widget is self.root else None, add="+")

    def set_tab_label(self, tab: str, picture: str):
        """Show a tab's name as its menu-font picture, brighter while the tab is selected (the
        text stays set underneath, for screen readers and as the fallback)."""
        imgs = getattr(self, "tab_labels", {}).get(picture)
        if imgs and tab in self.tab_frames:
            self.tabs.tab(self.tab_frames[tab], image=(imgs[0], "selected", imgs[1]), compound="image")

    def draw_bar(self, c: tk.Canvas):
        """A thin blue-to-green line, the colors of the game's HUD ring."""
        c.delete("all")
        w = max(c.winfo_width(), 2)
        a, b = (0x2f, 0x80, 0xed), (0x58, 0xc4, 0x6b)
        for x in range(0, w, 3):
            t = x / w
            col = "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
            c.create_rectangle(x, 0, x + 3, 3, fill=col, outline=col)

    def build_hero(self, parent):
        """The front card: a snapshot of where you left off and a big Continue button."""
        card = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground="#1d3a5c")
        card.pack(fill="x", pady=(4, 0))
        shot = tk.Frame(card, bg=PANEL)
        shot.pack(side="right", padx=14, pady=12)
        self.hero_img = tk.Label(shot, bg=FIELD, fg=DIM, text="no save yet\nstart a new game",
                                 width=22, height=9, highlightthickness=2, highlightbackground=BLUE)
        self.hero_img.pack()
        info = ttk.Frame(card, style="Card.TFrame")
        info.pack(side="left", fill="both", expand=True, padx=16, pady=14)
        self.hero_kicker = ttk.Label(info, text="", style="Muted.TLabel", font=("Segoe UI", 9, "bold"))
        self.hero_kicker.pack(anchor="w")
        self.hero_title = ttk.Label(info, text="", style="Card.TLabel", font=("Segoe UI", 18, "bold"),
                                    wraplength=330, justify="left")
        self.hero_title.pack(anchor="w", pady=(2, 2))
        self.continue_label = ttk.Label(info, text="", style="Muted.TLabel", wraplength=330, justify="left")
        self.continue_label.pack(anchor="w")
        row = ttk.Frame(info, style="Card.TFrame")
        row.pack(anchor="w", pady=(14, 0))
        self.continue_btn = ttk.Button(row, text="Continue", command=self.resume_newest)
        self.continue_btn.pack(side="left")
        self.play_btn = ttk.Button(row, text="Play from the title screen", command=self.play, style="Soft.TButton")
        self.play_btn.pack(side="left", padx=(8, 0))

    def refresh_hero(self, dump: str, ok: bool):
        newest = newest_state(dump)
        world, when = saved_world(dump) if is_dump(dump) else (None, None)
        self.hero_thumb = None
        if newest:
            key, label, path, mtime = newest
            self.hero_kicker.config(text="CONTINUE WHERE YOU LEFT OFF")
            self.hero_title.config(text=WORLD_TITLES.get(world, label) if world else label)
            self.continue_label.config(
                text=f"{label}, {time.strftime('%b %d, %H:%M', time.localtime(mtime))}"
                     + (f"\nGame saved in {WORLD_NAMES.get(world, world)} ({when})" if world else ""))
            png = os.path.splitext(path)[0] + ".png"
            if os.path.isfile(png):
                try:
                    self.hero_thumb = tk.PhotoImage(file=png)
                except tk.TclError:
                    self.hero_thumb = None
        else:
            self.hero_kicker.config(text="WELCOME")
            self.hero_title.config(text="Start a new game")
            self.continue_label.config(
                text="No save states yet. In game, F5 saves a snapshot of exactly where you are."
                     if is_dump(dump) else "Pick the game folder to get started.")
        if self.hero_thumb:
            self.hero_img.config(image=self.hero_thumb, text="", width=self.hero_thumb.width(),
                                 height=self.hero_thumb.height())
        else:
            self.hero_img.config(image="", text="no save yet\nstart a new game", width=22, height=9)
        self.continue_btn.config(state="normal" if (ok and newest) else "disabled",
                                 style="Accent.TButton" if newest else "Soft.TButton")
        self.play_btn.config(style="Soft.TButton" if newest else "Accent.TButton")

    def resume_newest(self):
        newest = newest_state(self.dump.get().strip())
        if newest:
            self.launch(build_command(self.dump.get().strip(), self.opts(), load_state=newest[0]),
                        "Resuming " + newest[1] + "...")

    def sync_share(self):
        """The address can be edited while sharing is on; it is grayed out when sharing is off."""
        self.share_entry.config(state="normal" if self.share.get() else "disabled")

    def leaderboard_url(self) -> str:
        """The address typed in the box, tidied; the project's own server if the box is empty."""
        return clean_leaderboard_url(self.leaderboard.get())

    # ------------------------------------------------------------------ tabs
    def tab_changed(self, _event=None):
        if getattr(self, "capturing", None):          # leaving the Controls tab ends a key capture
            self.stop_key_capture()
            self.refresh_key_buttons()
            self.status.config(text="")
        for key, frame in self.tab_frames.items():
            if str(frame) == self.tabs.select():
                self.cfg["tab"] = key
                if key == "options":
                    self.refresh_screenshots()
                try:
                    save_config(self.cfg)
                except OSError:
                    pass
                break

    def fit_minsize(self):
        """Hold the minimum window size at whatever the content needs, so nothing can ever be cut off."""
        self.root.update_idletasks()
        self.root.minsize(MIN_WIDTH, self.root.winfo_reqheight())

    # ---------------------------------------------------------------- state
    def opts(self, include_files: bool = True) -> dict:
        scale = self.scale.get()
        return {"scale": int(scale) if scale.isdigit() else 0, "mute": self.mute.get(),
                "font_size": self.font_size.get(), "hires_text": self.hires.get(),
                "soundfont": self.soundfont.get().strip(), "autosave": self.autosave.get(),
                "autosave_minutes": self.autosave_minutes_value(), "autosave_on_quit": self.autosave_on_quit.get(),
                "autosave_on_loading": self.autosave_on_loading.get(),
                "pause_on_focus_loss": self.focus_pause.get(), "screenshots": self.screenshots.get().strip(),
                "dark_screen": self.dark.get(), "ask_before_quit": self.ask_quit.get(),
                "ask_before_deleting_screenshot": self.ask_delete.get(), "custom_keys": dict(self.custom_keys),
                "speed_patches_off": [n for n, v in self.speed_vars.items() if not v.get()],
                "leaderboard": self.leaderboard_url() if self.share.get() else "",
                # kept only when changed, so a later change of the default server reaches everyone else
                "leaderboard_url": self.leaderboard_url() if self.leaderboard_url() != LEADERBOARD_URL else "",
                "share_scores": self.share.get(),
                "filter": self.filter_names.get(self.picture.get(), "nearest"),
                "music": music_settings.to_text(self.music_values()),
                "wonderland_volume": round(self.wl_volume.get(), 2),
                # only when starting the game: it checks the files, and the paths are in music_refs
                "music_files": self.music_files_in_game() if include_files else []}

    def remember(self):
        opts = self.opts(include_files=False)
        opts.pop("music_files")
        self.cfg.update(opts)
        self.cfg["scale"] = self.scale.get()
        self.cfg["dump"] = self.dump.get().strip()
        try:
            save_config(self.cfg)
        except OSError:
            pass

    def refresh(self):
        dump = self.dump.get().strip()
        missing = missing_packages()
        lines = []
        if missing:
            lines.append("Missing Python packages: " + ", ".join(missing) + ". Click Install.")
            self.install_btn.pack(side="right", padx=6)
        else:
            lines.append("Python packages: OK")
            self.install_btn.pack_forget()
        if not shutil.which("ffmpeg"):
            lines.append("ffmpeg not found: sound effects will be silent. Install it with "
                         "'winget install ffmpeg' (then restart this launcher).")
        else:
            lines.append("ffmpeg: OK")
        if not is_dump(dump):
            lines.append("Pick the game folder (the one that contains mif and mod).")
        else:                                # optional, so it never marks Setup with (!)
            music = find_wonderland_music(dump)
            if music:
                lines.append(f"Wonderland theme: OK ({os.path.relpath(music, dump)})")
            else:
                lines.append("Wonderland theme: not found (optional; the installers include it). To hear it on "
                             "the Wonderland screen, put it in the game folder as wonderland/Wonderland.flac "
                             "(or .mid, .ogg, .wav, .mp3).")
        self.req_label.config(text="\n".join(lines))
        self.update_wonderland(dump)
        self.setup_needed = bool(missing) or not shutil.which("ffmpeg") or not is_dump(dump)
        self.tabs.tab(self.tab_frames["setup"], text="Setup (!)" if self.setup_needed else "Setup")
        self.set_tab_label("setup", "setup_warn" if self.setup_needed else "setup")
        ok = is_dump(dump) and not missing and self.proc is None
        self.ready = ok
        for b in (self.play_btn, self.resume_btn, self.world_btn):
            b.config(state="normal" if ok else "disabled")
        self.refresh_hero(dump, ok)
        worlds = world_saves(dump) if is_dump(dump) else []
        self.world.config(values=worlds)
        if worlds and self.world.get() not in worlds:
            self.world.set(worlds[0])
        self.fill_slots(dump)
        self._states_sig = self.states_signature(dump)
        self.fit_minsize()          # the messages above change height; keep it all visible

    def states_signature(self, dump: str) -> tuple:
        """What the save-state files look like right now (name, time and size of each state and
        its preview), so a change made by the running game can be noticed cheaply."""
        sig = []
        if is_dump(dump):
            for key, _label in SLOTS:
                p = slot_file(dump, key)
                for q in (p, os.path.splitext(p)[0] + ".png"):
                    try:
                        st = os.stat(q)
                    except OSError:
                        continue
                    sig.append((q, st.st_mtime_ns, st.st_size))
        return tuple(sig)

    def sync_quit_pref(self):
        """The game's "D = quit and don't ask again" writes the setting into launcher.json: pick it
        up, so this window shows it and does not write the old answer back."""
        try:
            if self.ask_quit.get() and load_config().get("ask_before_quit", True) is False:
                self.ask_quit.set(False)
                self.cfg["ask_before_quit"] = False
        except (tk.TclError, AttributeError):
            pass

    def check_states(self):
        """Bring the list and the Continue card up to date if the game (or anything else) has
        saved or deleted a state, keeping the selected slot. Cheap when nothing changed."""
        self.sync_quit_pref()
        dump = self.dump.get().strip()
        sig = self.states_signature(dump)
        if sig != self._states_sig:
            self._states_sig = sig
            self.fill_slots(dump)
            self.refresh_hero(dump, self.ready)

    def watch_states(self):
        """Check on a timer; the launcher also checks the moment it is clicked or brought forward."""
        try:
            self.check_states()
            if self.cfg.get("tab") == "options":
                self.refresh_screenshots()          # F12 may have taken one since the tab was last looked at
        except tk.TclError:
            return                  # the window is closing
        finally:
            try:
                self._watch_timer = self.root.after(STATES_POLL_MS, self.watch_states)
            except tk.TclError:
                pass

    def window_gone(self, event):
        """The window is being destroyed: cancel the timers, so none fires on a dead window."""
        if event.widget is not self.root:
            return
        for name in ("_watch_timer", "_music_timer", "_music_check", "_shots_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
                setattr(self, name, None)

    def fill_slots(self, dump: str):
        sel = self.slots.curselection()
        self.slots.delete(0, "end")
        self.slot_keys = []
        for key, label in SLOTS:
            p = slot_file(dump, key) if is_dump(dump) else ""
            if p and os.path.isfile(p):
                when = time.strftime("%b %d, %H:%M", time.localtime(os.path.getmtime(p)))
                self.slots.insert("end", f"{label}  -  {when}")
            else:
                self.slots.insert("end", f"{label}  -  empty")
                self.slots.itemconfig("end", foreground=DIM)
            self.slot_keys.append(key)
        files = [(os.path.getmtime(slot_file(dump, k)), i) for i, k in enumerate(self.slot_keys)
                 if is_dump(dump) and os.path.isfile(slot_file(dump, k))]
        if sel and self.slot_picked:        # the player chose a slot: leave it alone
            self.slots.selection_set(sel[0])
        elif files:                         # otherwise follow the newest state, as it is saved
            self.slots.selection_set(max(files)[1])
        elif sel:
            self.slots.selection_set(sel[0])
        picked = self.slots.curselection()
        if picked:
            self.slots.see(picked[0])       # the list is short now: scroll to the highlighted row
        self.show_thumb()

    def slot_chosen(self):
        """The player picked a row (the list's own select event never fires for the launcher's
        own highlighting), so stop following the newest save."""
        self.slot_picked = True
        self.show_thumb()

    def selected_slot(self):
        sel = self.slots.curselection()
        return self.slot_keys[sel[0]] if sel else None

    def show_thumb(self):
        key, dump = self.selected_slot(), self.dump.get().strip()
        self.thumb = None
        text = "(no preview)"
        info = ""
        if key and is_dump(dump):
            p = slot_file(dump, key)
            png = os.path.splitext(p)[0] + ".png"
            if os.path.isfile(png):
                try:
                    self.thumb = fit_photo(tk.PhotoImage(file=png), THUMB_W, THUMB_H)
                except tk.TclError:
                    self.thumb = None
            info = "Double-click or press Resume" if os.path.isfile(p) else "Empty slot"
        self.thumb_label.config(image=self.thumb or "", text="" if self.thumb else text)
        self.slot_info.config(text=info)

    # ---------------------------------------------------------------- actions
    # ---------------------------------------------------------------- options tab
    def build_options(self, o):
        """The Options tab: grouped boxes in two columns."""
        cfg = self.cfg
        left, right = ttk.Frame(o), ttk.Frame(o)
        left.grid(row=0, column=0, sticky="nwe", padx=(0, 5))
        right.grid(row=0, column=1, sticky="nwe", padx=(5, 0))
        o.columnconfigure(0, weight=1)
        o.columnconfigure(1, weight=1)
        pad = dict(padx=6, pady=2)

        # ---- Window
        box = ttk.LabelFrame(left, text="Window")
        box.pack(fill="x", pady=(0, 6))
        self.scale = tk.StringVar(value=str(cfg.get("scale", "Auto")))
        ttk.Label(box, text="Size:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(box, textvariable=self.scale, values=["Auto", "1", "2", "3", "4"], width=6,
                     state="readonly").grid(row=0, column=1, sticky="w")
        self.font_size = tk.StringVar(value=str(cfg.get("font_size", 11)))
        ttk.Label(box, text="Text size:").grid(row=0, column=3, sticky="e", padx=(6, 4))
        ttk.Spinbox(box, from_=8, to=16, textvariable=self.font_size, width=4).grid(row=0, column=4, sticky="w")
        # how the picture is enlarged; F11 cycles the same choices in game
        self.filter_names = dict(zip(PICTURE_FILTERS.values(), PICTURE_FILTERS))
        self.picture = tk.StringVar(value=PICTURE_FILTERS.get(cfg.get("filter", "nearest"), PICTURE_FILTERS["nearest"]))
        ttk.Label(box, text="Picture:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(box, textvariable=self.picture, values=list(PICTURE_FILTERS.values()), width=19,
                     state="readonly").grid(row=1, column=1, columnspan=4, sticky="w")
        self.hires = tk.BooleanVar(value=cfg.get("hires_text", False))
        hires_check = ttk.Checkbutton(box, text="Smooth hi-res text", variable=self.hires)
        hires_check.grid(row=2, column=0, columnspan=3, sticky="w", **pad)
        self.tooltip(hires_check, "Redraws the game's text sharply at your window's resolution.")
        self.dark = tk.BooleanVar(value=bool(cfg.get("dark_screen", False)))
        dark_check = ttk.Checkbutton(box, text="Dark screen", variable=self.dark)
        dark_check.grid(row=2, column=3, columnspan=2, sticky="w", padx=(0, 6), pady=2)
        self.tooltip(dark_check, "Covers the rest of the monitor the game window is on with black, behind the "
                                 "window. Minimising the game removes it.")
        self.icons = getattr(self, "icons", {})
        self.icons.setdefault("info", make_icon("info"))
        size_info = ttk.Label(box, image=self.icons["info"], cursor="question_arrow")
        size_info.grid(row=0, column=2, sticky="w", padx=(4, 0))
        self.tooltip(size_info, "The game was built for flip-phone screens, so it looks best in a small window. "
                                "Auto picks up to 2x; choose 3 or 4 for bigger.")

        # ---- While playing: sound, pausing and quitting (autosave is on the Saves tab)
        box = ttk.LabelFrame(left, text="While playing")
        box.pack(fill="x", pady=(0, 6))
        first = ttk.Frame(box)
        first.pack(anchor="w", padx=6, pady=2)
        self.mute = tk.BooleanVar(value=cfg.get("mute", False))
        ttk.Checkbutton(first, text="Mute", variable=self.mute).pack(side="left")
        self.focus_pause = tk.BooleanVar(value=bool(cfg.get("pause_on_focus_loss", True)))
        pause_check = ttk.Checkbutton(first, text="Pause when I click away", variable=self.focus_pause)
        pause_check.pack(side="left", padx=(12, 0))
        self.tooltip(pause_check, "The game pauses (and the time away is not counted as play time) while its window "
                                  "is not the one you are using.")
        self.ask_quit = tk.BooleanVar(value=bool(cfg.get("ask_before_quit", True)))
        ask_check = ttk.Checkbutton(box, text="Ask before quitting (Esc / X)", variable=self.ask_quit)
        ask_check.pack(anchor="w", padx=6, pady=(2, 4))
        self.tooltip(ask_check, "Esc or the window's X asks \"Quit the game?\" first. Untick to quit at once "
                                "(in the question, D = quit and don't ask again).")

        # ---- Speed: the 3D engine's speed enhancements live in their own window (same picture; each can be turned off)
        box = ttk.LabelFrame(left, text="Speed")
        box.pack(fill="x", pady=(0, 6))
        off = set(cfg.get("speed_patches_off") or ())
        self.speed_vars = {n: tk.BooleanVar(value=n not in off) for n in swerve_patch.NAMES}
        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=4)
        speed_button = ttk.Button(row, text="Speed enhancements...", command=self.open_speed_window,
                                  style="Small.TButton")
        speed_button.pack(side="left")
        self.tooltip(speed_button, "Ways of running the game's 3D engine faster that draw exactly the same picture. "
                                   "All are on unless you turn one off.")
        self.speed_summary = ttk.Label(row, text="", foreground=MUTED, font=("Segoe UI", 8))
        self.speed_summary.pack(side="left", padx=(8, 0))
        for var in self.speed_vars.values():
            var.trace_add("write", lambda *_: self.update_speed_summary())
        self.speed_win = None
        self.update_speed_summary()

        restore = ttk.Frame(left)
        restore.pack(fill="x", pady=(2, 2))
        ttk.Button(restore, text="Restore default settings", command=self.restore_defaults,
                   style="Small.TButton").pack(side="left")
        restore_info = ttk.Label(restore, image=self.icons["info"], cursor="question_arrow")
        restore_info.pack(side="left", padx=(8, 0))
        self.tooltip(restore_info, "Only settings on this tab will reset to default. Your saves, the autosave "
                                   "settings on the Saves tab, the game folder and the Sound tab are not touched.")

        # ---- Screenshots (F12)
        box = ttk.LabelFrame(right, text="Screenshots (F12)")
        box.pack(fill="x", pady=(0, 6))
        self.screenshots = tk.StringVar(value=cfg.get("screenshots", ""))
        self.ask_delete = tk.BooleanVar(value=bool(cfg.get("ask_before_deleting_screenshot", True)))
        top = ttk.Frame(box)
        top.pack(fill="x", padx=6, pady=(4, 2))
        shots_entry = ttk.Entry(top, textvariable=self.screenshots)
        shots_entry.pack(side="left", fill="x", expand=True)
        self.tooltip(shots_entry, "Where F12 saves screenshots. Empty: a khvcemu folder inside your Pictures folder.")
        self.icons.update({name: make_icon(name) for name in ("folder", "picture")})   # kept: Tk drops unreferenced images
        choose = ttk.Button(top, image=self.icons["folder"], command=self.browse_screenshots, style="Small.TButton")
        choose.pack(side="left", padx=(6, 0))
        self.tooltip(choose, "Choose the folder F12 screenshots are saved in")
        mid = ttk.Frame(box)
        mid.pack(fill="x", padx=6, pady=(2, 4))
        listing = ttk.Frame(mid)
        listing.pack(side="left", fill="y")
        self.shots_list = tk.Listbox(listing, height=9, width=14, exportselection=False, activestyle="none",
                                     bg=PANEL, fg=TEXT, selectbackground=BLUE, selectforeground="white",
                                     highlightthickness=1, highlightbackground=DIM, relief="flat", font=("Segoe UI", 8))
        bar = ttk.Scrollbar(listing, orient="vertical", command=self.shots_list.yview)
        self.shots_list.configure(yscrollcommand=bar.set)
        self.shots_list.pack(side="left", fill="y")
        bar.pack(side="left", fill="y")
        self.shots_list.bind("<<ListboxSelect>>", lambda e: self.show_screenshot())
        self.shots_list.bind("<Double-Button-1>", lambda e: self.open_screenshot())
        self.shots_list.bind("<Return>", lambda e: self.open_screenshot())
        pic = ttk.Frame(mid, width=SHOT_W + 6, height=SHOT_H + 6)
        pic.pack(side="left", padx=(8, 0))
        pic.pack_propagate(False)
        self.shots_preview = ttk.Label(pic, text="No screenshots\nyet", foreground=MUTED, justify="center",
                                       anchor="center", font=("Segoe UI", 8))
        self.shots_preview.pack(fill="both", expand=True)
        self.shots_preview.bind("<Double-Button-1>", lambda e: self.open_screenshot())
        icons = ttk.Frame(mid)
        icons.pack(side="left", anchor="n", padx=(8, 0))
        show = ttk.Button(icons, image=self.icons["picture"], command=self.open_screenshot, style="Small.TButton")
        show.pack(pady=(0, 4))
        self.tooltip(show, "Open the selected screenshot (double-click does the same)")
        where = ttk.Button(icons, image=self.icons["folder"], command=self.open_screenshot_folder, style="Small.TButton")
        where.pack(pady=(0, 4))
        self.tooltip(where, "Open the screenshot folder")
        self.icons["delete"] = make_icon("delete")
        drop = ttk.Button(icons, image=self.icons["delete"], command=self.delete_screenshot, style="Small.TButton")
        drop.pack()
        self.tooltip(drop, "Delete the selected screenshot" + (" (it goes to the Recycle Bin)" if sys.platform == "win32" else "")
                     + ". The question has a box to stop asking; Restore default settings brings it back.")
        self._shots_sig = None
        self._shots_image = None
        self._shots_names: list = []
        self._shots_timer = None

        def folder_typed(*_):                         # refresh a moment after the last keystroke
            if self._shots_timer is not None:
                self.root.after_cancel(self._shots_timer)
            self._shots_timer = self.root.after(400, self.refresh_screenshots)
        self.screenshots.trace_add("write", folder_typed)

        # ---- Online scores
        self.soundfont = tk.StringVar(value=cfg.get("soundfont", ""))      # shown on the Sound tab
        box = ttk.LabelFrame(right, text="Online scores")
        box.pack(fill="x")
        # high scores are kept offline either way; this only adds a shared ranking
        self.leaderboard = tk.StringVar(value=cfg.get("leaderboard_url") or LEADERBOARD_URL)
        self.share = tk.BooleanVar(value=bool(cfg.get("share_scores", True)))
        ttk.Checkbutton(box, text="Share high scores with:", variable=self.share, command=self.sync_share).pack(
            anchor="w", padx=6, pady=(2, 0))
        self.share_entry = ttk.Entry(box, textvariable=self.leaderboard)
        self.share_entry.pack(fill="x", padx=6, pady=(2, 4))

    def build_autosave(self, body):
        """The Saves tab's autosave settings: three kinds, each on or off, and the minutes between the timed ones."""
        cfg = self.cfg
        legacy = cfg.get("autosave", True)       # before the split, one switch covered all three kinds
        self.autosave = tk.BooleanVar(value=bool(legacy))
        self.autosave_minutes = tk.StringVar(value=f"{clean_minutes(cfg.get('autosave_minutes', 5)):g}")
        self.autosave_on_quit = tk.BooleanVar(value=bool(cfg.get("autosave_on_quit", legacy)))
        self.autosave_on_loading = tk.BooleanVar(value=bool(cfg.get("autosave_on_loading", legacy)))
        box = ttk.LabelFrame(body, text="Autosave (F8 turns it on and off in game)")
        box.pack(fill="x", padx=6, pady=(4, 6))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=(4, 2))
        timed = ttk.Checkbutton(row, text="Every", variable=self.autosave)
        timed.pack(side="left")
        minutes = ttk.Spinbox(row, from_=1, to=120, textvariable=self.autosave_minutes, width=4)
        minutes.pack(side="left", padx=(4, 4))
        ttk.Label(row, text="min of play").pack(side="left")
        self.tooltip(timed, "A timed autosave while you play (the clock stops while the game is paused).")
        quit_save = ttk.Checkbutton(row, text="When I quit", variable=self.autosave_on_quit)
        quit_save.pack(side="left", padx=(18, 0))
        self.tooltip(quit_save, "One more autosave when the window is closed in the middle of the game.")
        load_save = ttk.Checkbutton(row, text="At loading screens", variable=self.autosave_on_loading)
        load_save.pack(side="left", padx=(18, 0))
        self.tooltip(load_save, "A checkpoint a few seconds after each Loading screen (a new area).")
        ttk.Label(box, text="The newest three are kept, as Autosave, Autosave 2 and Autosave 3 in the list above.",
                  foreground=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=6, pady=(0, 4))

    # ---------------------------------------------------------------- controls tab
    def build_controls(self, body):
        """Game keys that can be changed (click one, press the new key) beside Re:Cast's own keys."""
        try:
            self.custom_keys = keymod.parse_key_options(
                [f"{a}={k}" for a, k in (self.cfg.get("custom_keys") or {}).items()])
        except (ValueError, AttributeError):
            self.custom_keys = {}                     # a hand-edited or damaged setting: start from the defaults
        self.capturing = None
        self._capture_bind = None
        self.key_buttons = {}
        left = ttk.LabelFrame(body, text="Game keys: click one, then press the new key")
        left.pack(side="left", fill="both", padx=(0, 8), pady=2)
        for r, (action, what, _default) in enumerate(keymod.REBINDABLE):
            ttk.Label(left, text=what).grid(row=r, column=0, sticky="w", padx=(8, 6), pady=2)
            btn = ttk.Button(left, width=9, style="Small.TButton", command=lambda a=action: self.start_key_capture(a))
            btn.grid(row=r, column=1, padx=2, pady=2)
            ttk.Label(left, text=keymod.ALSO[action], foreground=MUTED, font=("Segoe UI", 8)).grid(
                row=r, column=2, sticky="w", padx=(6, 8))
            self.key_buttons[action] = btn
        right = ttk.LabelFrame(body, text="Re:Cast keys")
        right.pack(side="left", fill="both", expand=True, pady=2)
        for r, (_act, _keys, emu_act, emu_keys) in enumerate(CONTROLS):
            ttk.Label(right, text=emu_act).grid(row=r, column=0, sticky="w", padx=(8, 6), pady=1)
            ttk.Label(right, text=emu_keys, foreground=MUTED).grid(row=r, column=1, sticky="w", padx=(0, 8))
        ttk.Button(right, text="Reset game keys", command=self.reset_keys, style="Small.TButton").grid(
            row=len(CONTROLS), column=0, columnspan=2, sticky="w", padx=8, pady=(10, 4))
        ttk.Label(right, text="Esc cancels. Letters, tab and ; ' / , . - = ` can be used.", foreground=MUTED,
                  font=("Segoe UI", 8), wraplength=190, justify="left").grid(
            row=len(CONTROLS) + 1, column=0, columnspan=2, sticky="w", padx=8)
        self.refresh_key_buttons()

    def key_label(self, action: str) -> str:
        return keymod.display_key({**keymod.DEFAULT_KEYS, **self.custom_keys}[action])

    def refresh_key_buttons(self):
        for action, btn in self.key_buttons.items():
            changed = action in self.custom_keys
            btn.config(text="Press a key..." if self.capturing == action else self.key_label(action) + (" *" if changed else ""))

    def start_key_capture(self, action: str):
        self.stop_key_capture()
        self.capturing = action
        self.refresh_key_buttons()
        self._capture_bind = self.root.bind("<KeyPress>", self.on_key_capture, add="+")
        self.key_buttons[action].focus_set()
        self.status.config(text=f"Press the key for {keymod.ACTION_NAMES[action].lower()} (Esc cancels).")

    def stop_key_capture(self):
        if self._capture_bind is not None:
            try:
                self.root.unbind("<KeyPress>", self._capture_bind)
            except tk.TclError:
                pass
            self._capture_bind = None
        self.capturing = None

    def on_key_capture(self, event):
        action = self.capturing
        if action is None:
            return None
        if event.keysym == "Escape":
            self.stop_key_capture()
            self.refresh_key_buttons()
            self.status.config(text="")
            return "break"
        self.apply_key(action, event.keysym)
        return "break"

    def apply_key(self, action: str, keysym: str) -> bool:
        """Give `action` the key Tk calls `keysym`, if it can have it. Says why not in the status line."""
        key = keymod.key_from_tk(keysym)
        if key is None:
            self.status.config(text=f"{keysym} cannot be used. Letters, tab and ; ' / , . - = ` can. Esc cancels.")
            return False
        owner = keymod.key_owner(self.custom_keys, key, except_action=action)
        if owner is not None:
            self.status.config(text=f"{keymod.display_key(key)} is already {keymod.ACTION_NAMES[owner].lower()}. "
                                    "Pick another key, or change that one first.")
            return False
        if key == keymod.DEFAULT_KEYS[action]:
            self.custom_keys.pop(action, None)
        else:
            self.custom_keys[action] = key
        self.stop_key_capture()
        self.refresh_key_buttons()
        self.status.config(text=f"{keymod.ACTION_NAMES[action]} is now {keymod.display_key(key)}. "
                                "It applies the next time the game starts.")
        self.remember()
        return True

    def reset_keys(self):
        self.stop_key_capture()
        self.custom_keys = {}
        self.refresh_key_buttons()
        self.status.config(text="Game keys back to their defaults.")
        self.remember()

    def update_speed_summary(self):
        off = sum(1 for v in self.speed_vars.values() if not v.get())
        try:
            self.speed_summary.config(text="All on" if not off else f"{off} of {len(self.speed_vars)} off")
        except tk.TclError:
            pass

    def open_speed_window(self):
        """A small window with a switch for each speed enhancement and an info bubble for each."""
        if self.speed_win is not None:
            self.speed_win.deiconify()
            self.speed_win.lift()
            return
        w = tk.Toplevel(self.root)
        w.title("Speed enhancements")
        w.configure(bg=BG)
        w.transient(self.root)
        w.resizable(False, False)
        self.speed_win = w
        w.protocol("WM_DELETE_WINDOW", self.close_speed_window)
        w.bind("<Destroy>", lambda e: setattr(self, "speed_win", None) if e.widget is w else None, add="+")
        body = ttk.Frame(w, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Speed enhancements", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(body, wraplength=380, justify="left", text=(
            "Faster ways of running parts of the game's 3D engine. Each one draws exactly the same picture "
            "and leaves your saves alone, so there is normally no reason to turn any off. "
            "Changes apply the next time the game starts.")).pack(anchor="w", pady=(6, 10))
        if "info" not in self.icons:
            self.icons["info"] = make_icon("info")
        for n in swerve_patch.NAMES:
            row = ttk.Frame(body)
            row.pack(fill="x", pady=2)
            check = ttk.Checkbutton(row, text=swerve_patch.LABELS[n], variable=self.speed_vars[n])
            check.pack(side="left")
            info = ttk.Label(row, image=self.icons["info"], cursor="question_arrow")
            info.pack(side="left", padx=(8, 0))
            for widget in (check, info):
                self.tooltip(widget, swerve_patch.HINTS[n])
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Turn all on", style="Small.TButton",
                   command=lambda: [v.set(True) for v in self.speed_vars.values()]).pack(side="left")
        ttk.Button(buttons, text="Close", style="Small.TButton", command=self.close_speed_window).pack(side="right")

    def close_speed_window(self):
        if self.speed_win is not None:
            try:
                self.speed_win.destroy()
            except tk.TclError:
                pass
            self.speed_win = None
        self.remember()

    def autosave_minutes_value(self) -> float:
        return clean_minutes(self.autosave_minutes.get())

    # ---- screenshots: a list of the files in the folder and a preview of the selected one
    def shots_folder(self) -> str:
        from .paths import default_screenshot_dir
        return self.screenshots.get().strip() or default_screenshot_dir()

    def refresh_screenshots(self):
        """Fill the list from the screenshot folder (newest first) when it has changed, and keep the selection."""
        try:
            folder = self.shots_folder()
            names = []
            try:
                listing = os.listdir(folder) if os.path.isdir(folder) else []
            except OSError:
                listing = []                # a folder that cannot be read, or that has just gone
            for fn in listing:
                if fn.lower().endswith(SHOT_EXTS):
                    try:
                        names.append((os.path.getmtime(os.path.join(folder, fn)), fn))
                    except OSError:
                        pass
            names.sort(reverse=True)
            names = [fn for _, fn in names[:SHOTS_LISTED]]
            sig = (folder, tuple(names))
            if sig == self._shots_sig:
                return
            self._shots_sig = sig
            keep = self.shots_selected_name()
            self._shots_names = names
            self.shots_list.delete(0, "end")
            for fn in names:
                self.shots_list.insert("end", shot_label(fn))
            if names:
                self.shots_list.selection_set(names.index(keep) if keep in names else 0)    # the latest unless one was picked
            self.show_screenshot()
        except tk.TclError:
            pass                    # the window is closing

    def shots_selected_name(self):
        sel = self.shots_list.curselection()
        return self._shots_names[sel[0]] if sel and sel[0] < len(self._shots_names) else None

    def show_screenshot(self):
        name = self.shots_selected_name()
        self._shots_image = None
        if name is None:
            self.shots_preview.config(image="", text="No screenshots\nyet")
            return
        path = os.path.join(self.shots_folder(), name)
        try:
            if os.path.getsize(path) > SHOT_MAX_BYTES:
                raise OSError("too big to preview")
            img = tk.PhotoImage(file=path)
            self._shots_image = fit_photo(img, SHOT_W, SHOT_H)
            self.shots_preview.config(image=self._shots_image, text="")
        except (tk.TclError, OSError, MemoryError):
            self.shots_preview.config(image="", text="can't preview\nthis file")

    def open_screenshot(self):
        name = self.shots_selected_name()
        if name:
            open_in_viewer(os.path.join(self.shots_folder(), name))

    def confirm_delete_screenshot(self, name: str) -> bool:
        """The delete question, with a box (ticked) to keep asking: unticked and answered Yes, it stops asking."""
        where = "It goes to the Recycle Bin." if sys.platform == "win32" else "This cannot be undone."
        w = tk.Toplevel(self.root)
        w.title("Delete screenshot")
        w.configure(bg=BG)
        w.transient(self.root)
        w.resizable(False, False)
        answer = {"yes": False}
        keep_asking = tk.BooleanVar(value=True)
        body = ttk.Frame(w, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Delete the screenshot from {shot_label(name)}?\n\n{where}", justify="left").pack(anchor="w")
        ttk.Checkbutton(body, text="Ask me before deleting a screenshot", variable=keep_asking).pack(anchor="w", pady=(10, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))

        def finish(yes):
            answer["yes"] = yes
            if yes:
                self.ask_delete.set(keep_asking.get())
            w.destroy()
        yes_button = ttk.Button(row, text="Yes", command=lambda: finish(True), style="Small.TButton")
        yes_button.pack(side="left")
        ttk.Button(row, text="No", command=lambda: finish(False), style="Small.TButton").pack(side="left", padx=(6, 0))
        w.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        w.bind("<Escape>", lambda e: finish(False))
        w.update_idletasks()
        w.geometry(f"+{self.root.winfo_rootx() + 80}+{self.root.winfo_rooty() + 120}")
        yes_button.focus_set()
        try:
            w.grab_set()                              # modal; some window systems refuse until it is shown
        except tk.TclError:
            pass
        self.root.wait_window(w)
        return answer["yes"]

    def delete_screenshot(self):
        name = self.shots_selected_name()
        if not name:
            return
        path = os.path.join(self.shots_folder(), name)
        if self.ask_delete.get() and not self.confirm_delete_screenshot(name):
            return
        index = self._shots_names.index(name) if name in self._shots_names else 0   # the list may have changed meanwhile
        if to_trash(path):
            self.status.config(text=f"Deleted {name}.")
            self._shots_sig = None
            names = [n for n in self._shots_names if n != name]
            nxt = names[min(index, len(names) - 1)] if names else None
            self.shots_list.selection_clear(0, "end")
            if nxt is not None and nxt in self._shots_names:
                self.shots_list.selection_set(self._shots_names.index(nxt))   # the next one along stays selected
            self.refresh_screenshots()
        else:
            self.status.config(text=f"Could not delete {name}.")
            # usually another program has it open (Photos keeps the pictures it shows locked): say so, a status
            # line alone was easy to miss
            messagebox.showwarning("Delete screenshot", f"{name} could not be deleted.\n\nIt is probably open in "
                                   "another program, such as Photos. Close it there and try again.", parent=self.root)

    def open_screenshot_folder(self):
        folder = self.shots_folder()
        if os.path.isdir(folder):
            open_in_viewer(folder)
        else:
            self.status.config(text="That screenshot folder doesn't exist yet: it is made when you take the first one.")

    def browse_screenshots(self):
        from .paths import default_screenshot_dir
        start = self.screenshots.get().strip() or default_screenshot_dir()
        d = filedialog.askdirectory(title="Where F12 screenshots are saved",
                                    initialdir=start if os.path.isdir(start) else os.path.dirname(start) or PROJECT)
        if d:
            self.screenshots.set(os.path.normpath(d))

    def browse(self):
        d = filedialog.askdirectory(title="Game folder (contains mif and mod)",
                                    initialdir=self.dump.get() or PROJECT)
        if d:
            self.dump.set(os.path.normpath(d))

    # ---------------------------------------------------------------- sound
    def build_sound(self, parent):
        """Sliders for the built-in synth (music_settings), a tune to try them on, and an
        optional recording to compare against. Saved with the other options; the game picks
        them up the next time it starts."""
        from .music_preview import TUNES      # stdlib only until something is played
        self.preview = None                  # music_preview.MusicPreview, made on first Play
        self.preview_gen = 0                 # newest render asked for; older ones are dropped
        self.playing = None                  # "ours", "recording" or None: what is heard now
        self.pending = None                  # what is being prepared to play, if anything
        self._music_timer = None             # a re-render waiting for the slider to settle
        self._music_check = None             # the poll for a render in progress
        values = music_settings.clean(music_settings.parse(self.cfg.get("music", ""), strict=False))
        self.music_vars: dict = {}
        self.music_labels: dict = {}
        self.music_scales: dict = {}         # the sliders and their names, to gray out what does not apply
        self.music_names: dict = {}
        self.tunes = TUNES
        names = [n for _f, n in TUNES]

        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 2))
        ttk.Label(top, text="Tune:").pack(side="left", padx=(6, 4))
        self.tune = tk.StringVar(value=self.cfg.get("music_tune") if self.cfg.get("music_tune") in names
                                 else names[0])
        ttk.Combobox(top, textvariable=self.tune, values=names, width=28, state="readonly").pack(side="left")
        self.ours_btn = ttk.Button(top, text="Play", command=self.play_ours, style="Small.TButton")
        self.ours_btn.pack(side="left", padx=(8, 0))
        self.tooltip(self.ours_btn, "Plays the tune with the built-in synth and these sliders "
                                    "(even when a SoundFont is chosen in Advanced...)")
        ttk.Button(top, text="Stop", command=self.stop_clicked, style="Small.TButton").pack(side="left", padx=(4, 0))
        self.adv_btn = ttk.Button(top, text="Advanced...", command=self.open_advanced, style="Small.TButton")
        self.adv_btn.pack(side="right", padx=6)
        self.tooltip(self.adv_btn, "Play the music through a SoundFont instead of the built-in synth")
        self.adv_win = None                  # the Advanced window, while it is open

        # ready-made mixes and the player's own, favorites first
        mixrow = ttk.Frame(parent)
        mixrow.pack(fill="x", pady=(0, 2))
        ttk.Label(mixrow, text="Mix:").pack(side="left", padx=(6, 4))
        self.mix = tk.StringVar()
        self.mix_box = ttk.Combobox(mixrow, textvariable=self.mix, width=28, state="readonly")
        self.mix_box.pack(side="left")
        self.mix_box.bind("<<ComboboxSelected>>", lambda e: self.mix_chosen())
        self.fav_btn = ttk.Button(mixrow, text="\u2606", width=3, command=self.toggle_favorite, style="Small.TButton")
        self.fav_btn.pack(side="left", padx=(8, 0))
        self.tooltip(self.fav_btn, "Favorite: favorites are listed first")
        self.save_btn = ttk.Button(mixrow, text="Save as...", command=self.save_mix, style="Small.TButton")
        self.save_btn.pack(side="left", padx=(4, 0))
        self.del_btn = ttk.Button(mixrow, text="Delete", command=self.delete_mix, style="Small.TButton")
        self.del_btn.pack(side="left", padx=(4, 0))

        cols = ttk.Frame(parent)
        cols.pack(fill="x")
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        for col, (title, items) in enumerate((("Volumes", music_settings.VOLUMES),
                                              ("Character", music_settings.CHARACTER))):
            if col == 0:
                box = ttk.LabelFrame(cols, text=title)
                box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            else:                            # the right-hand column holds two boxes
                right = ttk.Frame(cols)
                right.grid(row=0, column=1, sticky="nsew")
                box = ttk.LabelFrame(right, text=title)
                box.pack(fill="x")
            box.columnconfigure(1, weight=1)
            for r, st in enumerate(items):
                var = tk.DoubleVar(value=values[st.key])
                self.music_vars[st.key] = var
                name = ttk.Label(box, text=st.label, font=("Segoe UI", 9))
                name.grid(row=r, column=0, sticky="w", padx=(6, 4))
                self.music_names[st.key] = name
                sc = ttk.Scale(box, from_=st.low, to=st.high, variable=var, length=110,
                               command=lambda _v, k=st.key: self.show_music_value(k))
                sc.grid(row=r, column=1, sticky="we")
                lab = ttk.Label(box, width=5, anchor="e", foreground=MUTED, font=("Segoe UI", 9))
                lab.grid(row=r, column=2, padx=(2, 6))
                lab.bind("<Double-Button-1>", lambda e, k=st.key: self.reset_music(k))
                self.music_labels[st.key] = lab
                self.music_scales[st.key] = sc
                for ev in ("<ButtonRelease-1>", "<KeyRelease>"):
                    sc.bind(ev, lambda e: self.music_changed(), add="+")
                self.show_music_value(st.key)
                if st.help:
                    self.tooltip(sc, st.help)
            if col == 1:                     # under the shorter column: the comparison player
                row = ttk.Frame(box)
                row.grid(row=len(items), column=0, columnspan=3, sticky="we", padx=6, pady=(4, 2))
                ttk.Label(row, text="Recording:", font=("Segoe UI", 9)).pack(side="left")
                choose = ttk.Button(row, text="Choose...", command=self.pick_recording, style="Small.TButton")
                choose.pack(side="left", padx=(6, 0))
                self.tooltip(choose, "A recording of this tune (for example a restoration) to compare with")
                self.rec_btn = ttk.Button(row, text="Play recording", command=self.play_recording,
                                          style="Small.TButton")
                self.rec_btn.pack(side="left", padx=(4, 0))
                self.rec_name = ""
                self.tooltip(self.rec_btn, lambda: self.rec_name or "No recording chosen for this tune")
                vol = ttk.Frame(box)
                vol.grid(row=len(items) + 1, column=0, columnspan=3, sticky="we", padx=6, pady=(0, 0))
                ttk.Label(vol, text="Its volume", font=("Segoe UI", 9)).pack(side="left")
                self.rec_gain = tk.DoubleVar(value=1.0)
                self.rec_scale = ttk.Scale(vol, from_=0.0, to=4.0, variable=self.rec_gain, length=90,
                                           command=lambda _v: self.show_rec_gain())
                self.rec_scale.pack(side="left", padx=(6, 0), fill="x", expand=True)
                for ev in ("<ButtonRelease-1>", "<KeyRelease>"):
                    self.rec_scale.bind(ev, lambda e: self.rec_gain_changed(), add="+")
                self.rec_gain_label = ttk.Label(vol, width=5, anchor="e", foreground=MUTED, font=("Segoe UI", 9))
                self.rec_gain_label.pack(side="left", padx=(2, 0))
                self.match_btn = ttk.Button(vol, text="Match", command=self.match_level, style="Small.TButton")
                self.match_btn.pack(side="left", padx=(4, 0))
                self.tooltip(self.match_btn, "Set the recording's volume to match the built-in synth's")
                self.rec_in_game = tk.BooleanVar(value=False)
                self.in_game_check = ttk.Checkbutton(box, text="Use the recording in the game",
                                                     variable=self.rec_in_game, command=self.rec_in_game_changed)
                self.in_game_check.grid(row=len(items) + 2, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 2))
        self.music_note = ttk.Label(right, text="", foreground=MUTED, font=("Segoe UI", 8), wraplength=290,
                                    justify="left")
        self.music_note.pack(anchor="w", padx=6, pady=(4, 0))
        self.soundfont.trace_add("write", lambda *_: self.show_music_note())
        self.show_music_note()
        self.tune_changed(save=False)
        self.tune.trace_add("write", lambda *_: self.tune_changed())
        self.sync_mix()

    def tooltip(self, widget, text: str):
        """A small hint that appears while the mouse rests on a slider."""
        tip = {}

        def show(_e):
            if tip:
                return
            w = tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 2}")
            tk.Label(w, text=text() if callable(text) else text, bg=PANEL, fg=TEXT, font=("Segoe UI", 8), padx=6, pady=3,
                     highlightthickness=1, highlightbackground=BLUE, wraplength=360, justify="left").pack()
            tip["w"] = w

        def hide(_e):
            w = tip.pop("w", None)
            if w is not None:
                w.destroy()
        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")
        widget.bind("<ButtonPress-1>", hide, add="+")

    def music_values(self) -> dict:
        """The sliders, in steps of 5%."""
        return {k: round(v.get() / 0.05) * 0.05 for k, v in getattr(self, "music_vars", {}).items()}

    def show_music_value(self, key: str):
        v = round(self.music_vars[key].get() / 0.05) * 0.05
        scale = getattr(self, "music_scales", {}).get(key)
        off = scale is not None and "disabled" in scale.state()
        self.music_labels[key].config(text=f"{v * 100:.0f}%",
                                      foreground=DIM if off else MUTED if abs(v - 1) < 1e-9 else TEXT)

    def soundfont_active(self) -> bool:
        """Will the game play the music through the SoundFont? Decided the way audio.AudioEngine
        decides: a file that exists, and the fluidsynth program installed."""
        sf = self.soundfont.get().strip()
        return bool(sf) and os.path.isfile(sf) and fluidsynth_found()

    def recording_in_game(self) -> bool:
        """Will the game play your recording instead of the selected tune?"""
        if getattr(self, "rec_in_game", None) is None or not self.rec_in_game.get():
            return False
        return os.path.isfile(self.rec_entry(self.current_tune())["path"])

    def show_music_note(self):
        """Say what the game will play for the selected tune, and gray out what does not apply."""
        sf = self.soundfont.get().strip()
        ticked = getattr(self, "rec_in_game", None) is not None and self.rec_in_game.get()
        if self.recording_in_game():
            text = "In game this tune plays your recording, so only its volume and Music volume apply."
        elif ticked and self.soundfont_active():
            text = "Your recording for this tune is missing; the SoundFont plays, so only Music volume applies."
        elif ticked:
            text = "Your recording for this tune is missing, so the game's music plays."
        elif self.soundfont_active():
            text = "In game the SoundFont plays (see Advanced...), so only Music volume applies."
        elif sf and not fluidsynth_found():
            text = "A SoundFont is chosen but fluidsynth is not installed, so the built-in synth plays (Advanced...)."
        elif sf:
            text = "The chosen SoundFont file was not found, so the built-in synth plays (Advanced...)."
        else:
            text = "100% = as tuned (double-click the number to reset). Changes apply when you next start the game."
        self.music_note.config(text=text)
        self.update_sound_states()
        if getattr(self, "adv_win", None) is not None:
            self.update_advanced()

    def update_sound_states(self):
        """A SoundFont, or your recording in the game, replaces the built-in synth, so its sliders
        and the mixes do nothing then: gray them out. Music volume always applies."""
        off = self.recording_in_game() or self.soundfont_active()
        for key in self.music_vars:
            if key == "master":
                continue
            self.music_scales[key].state(["disabled"] if off else ["!disabled"])
            self.music_names[key].config(foreground=DIM if off else TEXT)
            if off:
                self.music_labels[key].config(foreground=DIM)
            else:
                self.show_music_value(key)
        if off:
            for w in (self.fav_btn, self.save_btn, self.del_btn):
                w.config(state="disabled")
            self.mix_box.config(state="disabled")
        else:
            self.mix_box.config(state="readonly")
            self.save_btn.config(state="normal")
            if hasattr(self, "mix"):
                self.sync_mix()              # the star and Delete follow the selected mix

    # ---------------------------------------------------------------- the Advanced window
    def open_advanced(self):
        """A small window for the SoundFont, with what it is and how to use it."""
        if self.adv_win is not None:
            self.adv_win.deiconify()
            self.adv_win.lift()
            self.adv_win.focus_set()
            self.update_cache_status()           # the game may have rendered more since it was opened
            return
        w = tk.Toplevel(self.root)
        w.title("Advanced sound")
        w.configure(bg=BG)
        w.transient(self.root)
        w.resizable(False, False)
        self.adv_win = w
        w.protocol("WM_DELETE_WINDOW", self.close_advanced)
        w.bind("<Destroy>", lambda e: setattr(self, "adv_win", None) if e.widget is w else None, add="+")
        body = ttk.Frame(w, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="SoundFont", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(body, wraplength=460, justify="left", text=(
            "A SoundFont (.sf2) is a bank of recorded instrument samples. Instead of Re:Cast's built-in "
            "synth, the game's music can be played through one, using the free fluidsynth program.\n\n"
            "To use one:\n"
            "  1. Install fluidsynth (fluidsynth.org) so that it is on your PATH, then restart this "
            "launcher. It is not included with Re:Cast.\n"
            "  2. Get a General MIDI SoundFont (.sf2 file) and choose it below.\n"
            "  3. Start the game: every tune is played through it.\n\n"
            "While a SoundFont is in use, the Sound tab's instrument and character sliders and the "
            "mixes do nothing (they are settings of the built-in synth), so they are grayed out; Music "
            "volume still applies. A recording you chose to use in the game still plays instead of its "
            "tune. The Sound tab's Play button always plays the built-in synth. Leave the box empty to "
            "use the built-in synth.")).pack(anchor="w", pady=(6, 10))
        self.adv_status = ttk.Label(body, text="", wraplength=460, justify="left")
        self.adv_status.pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.sf_entry = ttk.Entry(row, textvariable=self.soundfont, width=48)
        self.sf_entry.pack(side="left", fill="x", expand=True)
        self.sf_button = ttk.Button(row, text="Browse...", command=self.pick_soundfont, style="Small.TButton")
        self.sf_button.pack(side="left", padx=(6, 0))
        self.sf_clear = ttk.Button(row, text="Clear", command=lambda: self.soundfont.set(""), style="Small.TButton")
        self.sf_clear.pack(side="left", padx=(4, 0))
        cache = ttk.Frame(body)
        cache.pack(fill="x", pady=(14, 0))
        ttk.Label(cache, text="Rendered music", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(cache, wraplength=460, justify="left", foreground=MUTED, text=(
            "The game renders its tunes with the built-in synth once and keeps them, so they play at once next "
            "time. Changing a slider or updating Re:Cast renders fresh ones by itself; clearing them only gives the "
            "space back (they are made again the next time the game starts).")).pack(anchor="w", pady=(2, 4))
        row = ttk.Frame(cache)
        row.pack(fill="x")
        self.cache_button = ttk.Button(row, text="Clear cached music", command=self.clear_music, style="Small.TButton")
        self.cache_button.pack(side="left")
        self.cache_status = ttk.Label(row, text="", foreground=MUTED)
        self.cache_status.pack(side="left", padx=(8, 0))
        self.update_cache_status()
        ttk.Button(body, text="Close", command=self.close_advanced, style="Small.TButton").pack(anchor="e", pady=(12, 0))
        self.update_advanced()

    def update_cache_status(self):
        count, size = music_cache_size(self.dump.get().strip())
        try:
            self.cache_status.config(text=f"{count} tune{'s' if count != 1 else ''} kept, {size / 1e6:.1f} MB" if count
                                     else "Nothing kept yet")
            self.cache_button.config(state="normal" if count else "disabled")
        except tk.TclError:
            pass

    def clear_music(self):
        count, size = music_cache_size(self.dump.get().strip())
        if not count or not messagebox.askyesno(
                "Clear cached music", f"Delete the {count} rendered tune{'s' if count != 1 else ''} "
                f"({size / 1e6:.1f} MB)? The game renders them again the next time it starts.",
                parent=self.adv_win or self.root):
            return
        gone = clear_music_cache(self.dump.get().strip())
        self.update_cache_status()
        self.status.config(text=f"Cleared {gone} rendered tune{'s' if gone != 1 else ''}.")

    def update_advanced(self):
        """The Advanced window's status line and whether its box can be used."""
        try:
            self._update_advanced()
        except tk.TclError:
            self.adv_win = None              # the window went away

    def _update_advanced(self):
        have = fluidsynth_found()
        exe = shutil.which("fluidsynth") or "on your PATH"
        sf = self.soundfont.get().strip()
        if not have:
            text = "fluidsynth was not found, so a SoundFont cannot be used. Install it, then restart the launcher."
        elif not sf:
            text = f"fluidsynth found ({exe}). No SoundFont chosen: the built-in synth plays."
        elif not os.path.isfile(sf):
            text = "That file was not found, so the built-in synth plays."
        else:
            text = "In use: the game's music plays through this SoundFont from the next game."
        self.adv_status.config(text=text, foreground=TEXT if have else MUTED)
        for widget in (self.sf_entry, self.sf_button):
            widget.config(state="normal" if have else "disabled")

    def close_advanced(self):
        if self.adv_win is not None:
            try:
                self.adv_win.destroy()
            except tk.TclError:
                pass
            self.adv_win = None
        self.remember()

    def music_changed(self):
        """A slider was let go: snap it to 5% steps, remember it, and play the change if our
        version of a tune is playing."""
        for k, var in self.music_vars.items():
            var.set(round(var.get() / 0.05) * 0.05)
            self.show_music_value(k)
        self.sync_mix()
        self.remember()
        if (self.pending or self.playing) == "ours":
            # wait for the slider to settle, so a drag does not queue a render per step
            if self._music_timer is not None:
                self.root.after_cancel(self._music_timer)
            self._music_timer = self.root.after(300, self._replay_ours)

    def _replay_ours(self):
        self._music_timer = None
        if (self.pending or self.playing) == "ours":
            self.play_ours()

    def reset_music(self, key: str = None):
        if key is not None and key in self.music_scales and "disabled" in self.music_scales[key].state():
            return                           # grayed out: it does nothing now, so it is left alone
        for k, var in self.music_vars.items():
            if key in (None, k):
                var.set(music_settings.DEFAULTS[k])
                self.show_music_value(k)
        self.music_changed()

    def music_refs(self) -> dict:
        """The recordings chosen per tune (a hand-edited config may hold anything)."""
        refs = self.cfg.get("music_refs")
        if not isinstance(refs, dict):
            refs = self.cfg["music_refs"] = {}
        return refs

    def rec_entry(self, tune: str) -> dict:
        """The recording chosen for a tune as {"path", "gain", "in_game"}; older configs kept
        just the path as text, and a hand-edited one may hold anything."""
        raw = self.music_refs().get(tune)
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raw = {}
        try:
            gain = float(raw.get("gain", 1.0))
        except (TypeError, ValueError):
            gain = 1.0
        gain = 1.0 if gain != gain else min(4.0, max(0.0, gain))       # NaN: as recorded
        return {"path": raw.get("path", ""), "gain": gain, "in_game": raw.get("in_game") is True}

    def set_rec_entry(self, tune: str, **changes):
        entry = self.rec_entry(tune)
        entry.update(changes)
        self.music_refs()[tune] = entry
        self.remember()

    def music_files_in_game(self) -> list:
        """(tune file, recording, volume) for each tune whose recording plays in the game."""
        out = []
        for f, _n in getattr(self, "tunes", ()):
            e = self.rec_entry(f)
            if e["in_game"] and e["path"] and os.path.isfile(e["path"]):
                out.append((f, e["path"], e["gain"]))
        return out

    def show_rec_gain(self):
        self.rec_gain_label.config(text=f"{round(self.rec_gain.get() / 0.05) * 5:.0f}%")

    def rec_gain_changed(self):
        g = round(self.rec_gain.get() / 0.05) * 0.05
        self.rec_gain.set(g)
        self.show_rec_gain()
        self.set_rec_entry(self.current_tune(), gain=g)
        if (self.pending or self.playing) == "recording":
            self.play_recording()

    def rec_in_game_changed(self):
        self.set_rec_entry(self.current_tune(), in_game=bool(self.rec_in_game.get()))
        self.show_music_note()

    def match_level(self, quiet: bool = False):
        """Set the recording's volume so it is as loud as the built-in synth's version (at Music
        volume 100%: the game applies Music volume to it on top)."""
        from .music_preview import tune_path
        e = self.rec_entry(self.current_tune())
        midi = tune_path(self.dump.get().strip(), self.current_tune())
        if not e["path"] or not os.path.isfile(e["path"]) or not midi:
            if not quiet:
                self.status.config(text="Choose a recording, and the game folder, first.")
            return
        if not self.open_preview():
            return
        settings = dict(self.music_values(), master=1.0)
        tune, path, preview, started = self.current_tune(), e["path"], self.preview, e["gain"]
        result: list = []

        def work():
            try:
                result.append(preview.match_gain(preview.render_tune(midi, settings), preview.decode_recording(path)))
            except Exception as err:
                result.append(err)

        def check():
            if not result:
                self.root.after(50, check)
                return
            if isinstance(result[0], Exception):
                self.status.config(text=f"Could not measure it: {result[0]}")
                return
            gain = round(result[0] / 0.05) * 0.05
            now = self.rec_entry(tune)
            if now["path"] != path or abs(now["gain"] - started) > 1e-9:
                return                       # another recording, or a volume set by hand, meanwhile
            self.set_rec_entry(tune, gain=gain)
            if tune == self.current_tune():
                self.rec_gain.set(gain)
                self.show_rec_gain()
            self.status.config(text=f"Recording volume set to {gain * 100:.0f}% to match the built-in synth.")
            if (self.pending or self.playing) == "recording":
                self.play_recording()
        self.status.config(text="Measuring the recording...")
        threading.Thread(target=work, daemon=True).start()
        self.root.after(50, check)

    def current_tune(self) -> str:
        return dict((n, f) for f, n in self.tunes).get(self.tune.get(), self.tunes[0][0])

    def tune_changed(self, save: bool = True):
        e = self.rec_entry(self.current_tune())
        path = e["path"]
        self.rec_name = os.path.basename(path)
        state = "normal" if path else "disabled"
        for w in (self.rec_btn, self.rec_scale, self.match_btn, self.in_game_check):
            w.config(state=state)
        self.rec_gain.set(e["gain"])
        self.show_rec_gain()
        self.rec_in_game.set(e["in_game"])
        self.show_music_note()
        if save:
            self.cfg["music_tune"] = self.tune.get()
            self.remember()
            busy = self.pending or self.playing
            if busy == "ours":
                self.play_ours()             # the new tune (a render of the old one is dropped)
            elif busy == "recording":
                self.stop_music()

    def pick_recording(self):
        from .music_preview import RECORDING_TYPES
        f = filedialog.askopenfilename(title=f"A recording of {self.tune.get()}", filetypes=RECORDING_TYPES)
        if f:
            old = self.rec_entry(self.current_tune())
            self.music_refs()[self.current_tune()] = {"path": os.path.normpath(f), "gain": 1.0,
                                                      "in_game": old["in_game"]}
            self.tune_changed()
            self.match_level(quiet=True)          # a fair comparison from the start

    def open_preview(self) -> bool:
        if self.preview is None:
            from .music_preview import MusicPreview
            self.preview = MusicPreview()
        try:
            self.preview.open()
            return True
        except ImportError:
            self.status.config(text="Install the requirements first (Setup tab) to play music here.")
        except Exception as e:               # no sound device, or the mixer refused
            self.status.config(text=f"No sound output: {e}")
        return False

    def play_ours(self):
        from .music_preview import tune_path
        path = tune_path(self.dump.get().strip(), self.current_tune())
        if not path:
            self.status.config(text="Pick the game folder first (Setup tab): the music comes from it.")
            return
        settings = self.music_values()
        self.play_async("ours", lambda: self.preview.render_tune(path, settings),
                        f"Playing {self.tune.get()} (built-in synth).")

    def play_recording(self):
        e = self.rec_entry(self.current_tune())
        path, gain = e["path"], e["gain"] * self.music_values().get("master", 1.0)   # as the game plays it
        if not path or not os.path.isfile(path):
            self.status.config(text="That recording is not there any more: choose it again.")
            return
        self.play_async("recording", lambda: self.preview.with_gain(self.preview.decode_recording(path), gain),
                        f"Playing the recording: {os.path.basename(path)} (volume {gain * 100:.0f}%)")

    def play_async(self, what: str, make, msg: str):
        """Render or decode in the background (a tune takes a second or two), then play it,
        unless something newer was asked for in the meantime."""
        if not self.open_preview():
            return
        self.preview_gen += 1
        gen = self.preview_gen
        self.pending = what
        self.status.config(text="Getting it ready...")

        result: list = []                    # filled by the worker; Tk is only touched from here

        def work():
            try:
                result.append((make(), None))
            except Exception as e:
                result.append((None, e))

        def check():
            self._music_check = None
            if gen != self.preview_gen:
                return                       # stopped, or something newer was asked for
            if not result:
                self._music_check = self.root.after(50, check)
                return
            self.pending = None
            raw, err = result[0]
            if err is not None:
                self.status.config(text=f"Could not play it: {err}")
                return
            self.preview.play(raw)
            self.playing = what
            self.show_playing()
            self.status.config(text=msg)
        threading.Thread(target=work, daemon=True).start()
        if self._music_check is not None:
            self.root.after_cancel(self._music_check)
        self._music_check = self.root.after(50, check)

    def stop_clicked(self):
        """The Sound tab's Stop button: stop, and say so at the bottom of the window."""
        was = self.pending or self.playing
        self.stop_music("Music stopped." if was else "Nothing is playing.")

    def stop_music(self, say: str = None):
        """Stop whatever the launcher is playing. `say` is shown in the status line at the bottom (the
        launcher's own stops, such as starting the game, say nothing)."""
        self.preview_gen += 1
        self.playing = self.pending = None
        for name in ("_music_timer", "_music_check"):
            timer = getattr(self, name, None)
            if timer is not None:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        if getattr(self, "preview", None) is not None:
            self.preview.stop()
        self.show_playing()
        if say:
            self.status.config(text=say)

    # ---------------------------------------------------------------- Wonderland theme (Setup tab)
    def build_wonderland(self, body):
        """Play the optional Wonderland theme here, with a volume that the game uses too."""
        frame = ttk.LabelFrame(body, text="Wonderland theme")
        frame.pack(fill="x", pady=(8, 0))
        try:
            vol = float(self.cfg.get("wonderland_volume", 1.0))
        except (TypeError, ValueError):
            vol = 1.0
        self.wl_volume = tk.DoubleVar(value=min(2.0, max(0.0, vol)))
        self.wl_path = None
        self.wl_btn = ttk.Button(frame, text="Play", command=self.toggle_wonderland, style="Small.TButton")
        self.wl_btn.pack(side="left", padx=6, pady=6)
        ttk.Label(frame, text="Volume").pack(side="left", padx=(6, 0))
        self.wl_scale = ttk.Scale(frame, from_=0.0, to=2.0, variable=self.wl_volume, length=150,
                                  command=lambda _v: self.wonderland_volume_changed())
        self.wl_scale.pack(side="left", padx=6, fill="x", expand=True)
        self.wl_label = ttk.Label(frame, width=5, anchor="e")
        self.wl_label.pack(side="left", padx=(0, 6))
        self.show_wonderland_volume()
        self.tooltip(self.wl_btn, "Plays the Wonderland theme from your game folder. The volume applies in the "
                                  "game too, on the Wonderland screen.")

    def show_wonderland_volume(self):
        self.wl_label.config(text=f"{self.wl_volume.get() * 100:.0f}%")

    def update_wonderland(self, dump: str):
        """Called by refresh(): the controls work only when the theme file is in the game folder."""
        self.wl_path = find_wonderland_music(dump) if is_dump(dump) else None
        state = "normal" if self.wl_path else "disabled"
        for w in (self.wl_btn, self.wl_scale):
            w.config(state=state)
        if not self.wl_path and (self.pending or self.playing) == "wonderland":
            self.stop_music()
            if getattr(self, "_wl_timer", None) is not None:
                self.root.after_cancel(self._wl_timer)
                self._wl_timer = None

    def wonderland_volume_changed(self):
        g = round(self.wl_volume.get() / 0.05) * 0.05
        if abs(g - self.wl_volume.get()) > 1e-9:
            self.wl_volume.set(g)
        self.show_wonderland_volume()
        if (self.pending or self.playing) == "wonderland":      # hear the change once the slider settles
            if getattr(self, "_wl_timer", None) is not None:
                self.root.after_cancel(self._wl_timer)
            self._wl_timer = self.root.after(300, self.play_wonderland)

    def toggle_wonderland(self):
        if (self.pending or self.playing) == "wonderland":
            self.stop_music("Wonderland theme stopped.")
        else:
            self.play_wonderland()

    def play_wonderland(self):
        self._wl_timer = None
        path = self.wl_path
        if not path or not os.path.isfile(path):
            self.status.config(text="The Wonderland theme is not in the game folder.")
            return
        gain, settings = self.wl_volume.get(), self.music_values()
        if not self.open_preview():
            return

        def make():
            if path.lower().endswith(".mid"):           # played by the built-in synth, as in the game
                raw = self.preview.render_tune(path, settings)
            else:
                raw = self.preview.decode_recording(path)
            return self.preview.with_gain(raw, gain)
        self.play_async("wonderland", make, f"Playing the Wonderland theme (volume {gain * 100:.0f}%).")

    def show_playing(self):
        """The button of whatever is playing is lit, so it is clear which version is heard."""
        for btn, what in ((getattr(self, "ours_btn", None), "ours"), (getattr(self, "rec_btn", None), "recording"),
                          (getattr(self, "wl_btn", None), "wonderland")):
            if btn is not None:
                try:
                    btn.config(style="SmallOn.TButton" if self.playing == what else "Small.TButton")
                    if what == "wonderland":
                        btn.config(text="Stop" if self.playing == what else "Play")
                except tk.TclError:
                    pass

    # ---------------------------------------------------------------- mixes
    CUSTOM_MIX = "Custom (unsaved)"

    def mix_profiles(self) -> dict:
        """The player's saved mixes, {name: settings text} (a hand-edited config may hold anything)."""
        p = self.cfg.get("music_profiles")
        if not isinstance(p, dict):
            p = self.cfg["music_profiles"] = {}
        return {k: v for k, v in p.items() if isinstance(k, str) and isinstance(v, str)}

    def mix_favorites(self) -> list:
        f = self.cfg.get("music_favorites")
        if f is None:
            f = self.cfg.get("music_favourites")       # the key as an earlier launcher spelled it
        return list(dict.fromkeys(x for x in f if isinstance(x, str))) if isinstance(f, list) else []

    def mix_settings(self, name: str):
        if name in music_settings.PRESETS:
            return music_settings.preset(name)
        text = self.mix_profiles().get(name)
        if text is None:
            return None
        got = music_settings.clean(music_settings.parse(text, strict=False))
        return {k: round(v / 0.05) * 0.05 for k, v in got.items()}       # what the sliders can show

    def mix_names(self) -> list:
        """Favorites first, then the ready-made mixes, then the player's own."""
        favs = [n for n in self.mix_favorites() if self.mix_settings(n) is not None]
        rest = [n for n in music_settings.PRESETS if n not in favs]
        rest += sorted((n for n in self.mix_profiles() if n not in favs and n not in music_settings.PRESETS),
                       key=str.lower)
        return favs + rest

    def mix_label(self, name: str) -> str:
        return ("\u2605 " if name in self.mix_favorites() else "") + name

    def current_mix(self):
        """The mix the sliders are set to (the last one picked, if it still matches), or None."""
        now = music_settings.to_text(self.music_values())
        names = self.mix_names()
        last = self.cfg.get("music_mix")
        for n in ([last] if last in names else []) + names:
            if music_settings.to_text(self.mix_settings(n)) == now:
                return n
        return None

    def sync_mix(self):
        name = self.current_mix()
        self.mix_box.config(values=[self.mix_label(n) for n in self.mix_names()])
        self.mix.set(self.mix_label(name) if name else self.CUSTOM_MIX)
        self.fav_btn.config(text="\u2605" if name in self.mix_favorites() else "\u2606",
                            state="normal" if name else "disabled")
        self.del_btn.config(state="normal" if name and name not in music_settings.PRESETS else "disabled")
        if self.recording_in_game() or self.soundfont_active():      # the mixes do nothing then
            self.fav_btn.config(state="disabled")
            self.del_btn.config(state="disabled")

    def mix_chosen(self):
        name = self.mix.get().removeprefix("\u2605 ")
        settings = self.mix_settings(name)
        if settings is None:
            return
        for k, var in self.music_vars.items():
            var.set(settings[k])
        self.cfg["music_mix"] = name
        self.music_changed()
        self.status.config(text=f"Mix: {name}.")

    def save_mix(self):
        name = simpledialog.askstring("Save mix", "A name for the current sliders:", parent=self.root,
                                      initialvalue=self.current_mix() or "")
        name = (name or "").strip()[:40]
        if not name:
            return
        if name.lower() in (n.lower() for n in music_settings.PRESETS) or name == self.CUSTOM_MIX:
            messagebox.showinfo("Save mix", f"\"{name}\" is a ready-made mix. Pick another name.")
            return
        if name.startswith("\u2605"):
            messagebox.showinfo("Save mix", "The star marks favorites, so a name cannot start with it.")
            return
        profiles = self.mix_profiles()
        if name in profiles and not messagebox.askyesno("Save mix", f"Replace your mix \"{name}\"?"):
            return
        profiles[name] = music_settings.to_text(self.music_values())
        self.cfg["music_profiles"] = profiles
        self.cfg["music_mix"] = name
        self.sync_mix()
        self.remember()
        self.status.config(text=f"Saved the mix \"{name}\".")

    def toggle_favorite(self):
        name = self.current_mix()
        if not name:
            return
        favs = self.mix_favorites()
        favs = [n for n in favs if n != name] if name in favs else favs + [name]
        self.cfg["music_favorites"] = favs
        self.cfg.pop("music_favourites", None)
        self.cfg["music_mix"] = name
        self.sync_mix()
        self.remember()

    def delete_mix(self):
        name = self.current_mix()
        if not name or name in music_settings.PRESETS:
            return
        if not messagebox.askyesno("Delete mix", f"Delete your mix \"{name}\"? The sliders stay as they are."):
            return
        profiles = self.mix_profiles()
        profiles.pop(name, None)
        self.cfg["music_profiles"] = profiles
        self.cfg["music_favorites"] = [n for n in self.mix_favorites() if n != name]
        self.cfg.pop("music_favourites", None)
        self.cfg.pop("music_mix", None)
        self.sync_mix()
        self.remember()
        self.status.config(text=f"Deleted the mix \"{name}\".")

    def restore_defaults(self, ask: bool = True):
        """Put the Options tab back as it was at the start, for when a setting, such as the
        leaderboard address, was changed by mistake. Only that tab: the Saves tab's autosave settings and the
        Sound tab are the player's to manage."""
        if ask and not messagebox.askyesno(
                "Restore default settings",
                "Put window size, text size, mute, hi-res text, picture filter, pausing on focus loss, the quit "
                "question, the dark screen, the speed enhancements, the screenshot folder and score sharing "
                "(and its address) back to their defaults?\n\n"
                "Only the Options tab changes: your saves, autosave settings, game folder and Sound tab stay as "
                "they are."):
            return
        d = OPTION_DEFAULTS
        self.scale.set(d["scale"])
        self.font_size.set(str(d["font_size"]))
        self.mute.set(d["mute"])
        self.hires.set(d["hires_text"])
        self.picture.set(PICTURE_FILTERS[d["filter"]])
        self.focus_pause.set(d["pause_on_focus_loss"])
        self.screenshots.set(d["screenshots"])
        self.dark.set(d["dark_screen"])
        self.ask_quit.set(d["ask_before_quit"])
        self.ask_delete.set(d["ask_before_deleting_screenshot"])
        for var in self.speed_vars.values():
            var.set(True)
        self.share.set(d["share_scores"])
        self.leaderboard.set(LEADERBOARD_URL)
        self.sync_share()
        self.cfg.pop("leaderboard_url", None)
        self.remember()
        self.status.config(text="Default settings restored.")

    def pick_soundfont(self):
        f = filedialog.askopenfilename(title="General MIDI SoundFont", filetypes=[("SoundFont", "*.sf2")],
                                       parent=self.adv_win or self.root)
        if f:
            self.soundfont.set(f)

    def install(self):
        self.install_btn.config(state="disabled")
        self.status.config(text="Installing requirements... (this can take a minute)")
        req = os.path.join(PROJECT, "requirements.txt")

        def work():
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", req],
                               capture_output=True, text=True, **no_window())
            self.root.after(0, lambda: self.install_done(r))
        threading.Thread(target=work, daemon=True).start()

    def install_done(self, r):
        self.install_btn.config(state="normal")
        importlib.invalidate_caches()
        if r.returncode == 0:
            self.status.config(text="Requirements installed.")
        else:
            self.status.config(text="Install failed - see details.")
            messagebox.showerror("Install failed", (r.stdout + r.stderr)[-2000:])
        self.refresh()

    def play(self):
        self.launch(build_command(self.dump.get().strip(), self.opts()), "Starting the game...")

    def resume(self):
        key, dump = self.selected_slot(), self.dump.get().strip()
        if not key or not os.path.isfile(slot_file(dump, key)):
            messagebox.showinfo("Save states", "Pick a slot that has a save state.\n\n"
                                "In game, press F5 to save a state and F9 to load it.")
            return
        self.launch(build_command(dump, self.opts(), load_state=key), "Resuming save state...")

    def start_world(self):
        w = self.world.get()
        if not w:
            return
        if not messagebox.askokcancel(
                "Start at " + w.capitalize(),
                f"This replaces your current game save with the starting {w} save, then you "
                "choose Load Game.\n\nYour current save is backed up first (in save_backups). "
                "To keep playing your own game instead, use Play."):
            return
        self.launch(build_command(self.dump.get().strip(), self.opts(), start=w),
                    f"Starting {w}... choose Load Game on the title screen.")

    def launch(self, cmd: list, msg: str):
        self.stop_music()                    # the game has its own music, and needs the sound device
        if self.preview is not None:
            self.preview.close()
        self.remember()
        self.output = []
        try:
            self.proc = subprocess.Popen(cmd, cwd=PROJECT, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors="replace",
                                         **no_window())
        except OSError as e:
            messagebox.showerror("Could not start", str(e))
            return
        self.status.config(text=msg + "  (the launcher waits until the game closes)")
        self.refresh()
        threading.Thread(target=self.watch, args=(self.proc,), daemon=True).start()

    def watch(self, proc):
        for line in proc.stdout:
            self.output.append(line.rstrip())
            del self.output[:-200]
        code = proc.wait()
        self.root.after(0, lambda: self.game_closed(code))

    def game_closed(self, code: int):
        self.proc = None
        if code == 0:
            self.status.config(text="Game closed. Your autosave is under Autosave (newest).")
        else:
            self.status.config(text=f"The game stopped with an error (code {code}).")
            messagebox.showerror("khvcemu error", "\n".join(self.output[-25:]) or f"exit code {code}")
        self.refresh()

    def close(self):
        if self.proc is not None and not messagebox.askokcancel(
                "Quit launcher", "The game is still running. Close the launcher anyway?\n"
                "(The game keeps running.)"):
            return
        self.remember()
        self.stop_music()
        if self.preview is not None:
            self.preview.close()
        self.root.destroy()


def main():
    use_bundled_tools()
    root = tk.Tk()
    Launcher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
