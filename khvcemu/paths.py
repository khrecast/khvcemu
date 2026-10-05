"""Where khvcemu keeps its per-user files (saves, save states, launcher settings).

Uses only the standard library, so the launcher can import it before the
emulator's own requirements are installed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

APP_DIR = ".khvcemu"
LEGACY_APP_DIR = ".khemu"       # the name before the project became "khvcemu"


def no_window() -> dict:
    """subprocess kwargs that stop Windows flashing a console window for a child
    process (ffmpeg, fluidsynth, pip). Nothing extra is needed elsewhere."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


class _SafeStream:
    """A stream that never raises when the other end has gone away."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        try:
            return self._stream.write(text)
        except (OSError, ValueError):
            return len(text)

    def flush(self):
        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


def protect_output():
    """The launcher reads the game's log through a pipe. If the launcher is closed while the
    game is still running, that pipe breaks and the next line the game prints (saving a state
    prints one) raises an error that ends the game. Make printing harmless instead."""
    import sys
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None and not isinstance(stream, _SafeStream):
            setattr(sys, name, _SafeStream(stream))


def use_bundled_tools():
    """If the installer's `bin` folder (ffmpeg) sits in the project folder, put it first on
    PATH for this process and the ones it starts. Does nothing in a normal checkout."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    b = os.path.join(root, "bin")
    if os.path.isdir(b):
        os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


def icon_file(ext: str = "png") -> str:
    """Path of the Re:Cast window icon (recast_icon.png / .ico), or '' if it is missing."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "recast_icon." + ext)
    return p if os.path.isfile(p) else ""


def set_app_id(app_id: str):
    """Windows only: give this process its own taskbar identity so its window shows our
    icon instead of Python's, and does not group with other Python programs."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass


def _is_empty(path: str) -> bool:
    return os.path.isdir(path) and not os.listdir(path)


def data_home(home: str = None) -> str:
    """~/.khvcemu. If it doesn't exist yet (or is empty) but the pre-rename
    ~/.khemu does, that folder is copied over once so existing saves and save
    states carry on working. The copy is made next to the target and renamed
    into place, so a failure (a locked file, a full disk) never leaves a
    half-copied folder; in that case the old folder keeps being used and the
    copy is retried next time. The old folder is never modified or deleted."""
    home = home or os.path.expanduser("~")
    new, old = os.path.join(home, APP_DIR), os.path.join(home, LEGACY_APP_DIR)
    if (not os.path.exists(new) or _is_empty(new)) and os.path.isdir(old):
        tmp = new + ".migrating"
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(old, tmp)
            if _is_empty(new):
                os.rmdir(new)
            os.replace(tmp, new)
            return new
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            return old
    os.makedirs(new, exist_ok=True)
    return new


def folder_name(game_root: str) -> str:
    """The data folder a game folder maps to: its own name, made filename-safe."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(os.path.abspath(game_root))) or "game"


def has_progress(path: str) -> bool:
    """True if a data folder holds anything worth keeping: the game's own save, a
    save state, or a save backup. Used to tell a real save folder from one the
    emulator created and never wrote to."""
    if os.path.isfile(os.path.join(path, "files", "savegame.dat")):
        return True
    for sub, ext in (("states", ".khs"), ("save_backups", ".bak")):
        d = os.path.join(path, sub)
        try:
            if any(f.endswith(ext) for f in os.listdir(d)):
                return True
        except OSError:
            pass
    return False


def game_data_dir(game_root: str, home: str = None, log=None) -> str:
    """Where this dump's saves, states and settings go: ~/.khvcemu/<game folder name>.

    That name follows the game folder, so renaming or moving the folder would
    otherwise leave the old saves behind and look like they had been lost. When
    the expected folder holds no progress but exactly one other one does, that
    one is used instead. Nothing is moved, copied or deleted: only which folder
    gets opened changes, so pointing the game folder back puts it back as it was.

    Several candidates are never guessed between: the expected folder is used
    and the others are named in the log, for `--data` to choose from."""
    base = data_home(home)
    name = folder_name(game_root)
    want = os.path.join(base, name)
    if has_progress(want):
        return want
    try:
        others = sorted(d for d in os.listdir(base)
                        if d != name and has_progress(os.path.join(base, d)))
    except OSError:
        others = []
    if len(others) == 1:
        if log:
            log(f"[khvcemu] no saves under '{name}', using the existing save folder "
                f"'{others[0]}' (renamed or moved the game folder?). "
                f"--data DIR picks a folder yourself.")
        return os.path.join(base, others[0])
    if others and log:
        log(f"[khvcemu] note: saves also exist under {', '.join(repr(o) for o in others)}; "
            f"using '{name}'. --data DIR picks one of them.")
    return want


def get_launcher_option(key: str, default=None, home: str = None):
    """One option from the launcher's saved settings (launcher.json), or `default`."""
    import json
    try:
        with open(os.path.join(data_home(home), "launcher.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get(key, default) if isinstance(cfg, dict) else default
    except (OSError, ValueError):
        return default


def set_launcher_option(key: str, value, home: str = None) -> bool:
    """Write one option into the launcher's saved settings (launcher.json), keeping the rest, so a
    choice made in the game ("don't ask me again") is what the launcher shows next. True if saved."""
    import json
    path = os.path.join(data_home(home), "launcher.json")
    try:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                cfg = {}
        except (OSError, ValueError):
            cfg = {}
        cfg[key] = value
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def default_screenshot_dir(home: str = None) -> str:
    """Where F12 screenshots go unless told otherwise: Pictures/khvcemu in your home folder
    (made when the first one is taken), or the current folder if there is no Pictures folder."""
    home = home or os.path.expanduser("~")
    pictures = os.path.join(home, "Pictures")
    return os.path.join(pictures, "khvcemu") if os.path.isdir(pictures) else os.getcwd()


MUSIC_EXTS = (".mid", ".flac", ".ogg", ".wav", ".mp3")


def find_wonderland_music(game_root: str) -> str | None:
    """Optional Wonderland theme supplied by the user: wonderland.<ext> in the
    dump folder or in a 'wonderland' sub-folder (.mid preferred, then FLAC...).
    The game is missing it; the installers include it, a copy of the repository does not."""
    for ext in MUSIC_EXTS:
        for folder in (game_root, os.path.join(game_root, "wonderland")):
            if not os.path.isdir(folder):
                continue
            for fn in os.listdir(folder):
                if fn.lower() == "wonderland" + ext:
                    return os.path.join(folder, fn)
    return None
