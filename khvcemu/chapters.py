"""Chapter (episode) handling for Kingdom Hearts V CAST.

How the real game moves between worlds (read from kh.mod):
  * savegame.dat holds Sora's stats plus the *name of the current world*
    ("island", "wonderland", "agrabah", "castle"); a 4-digit progress code
    precedes it.
  * Every world's assets (.m3g scenes, .pmd/.mid audio) sit in the game's
    own folder. The phone only ever had one episode installed; finishing a
    world made the game download the next episode's files from
    http://swervenet.superscape.com/disney/download.php (via IWeb), which
    overwrote the folder.
  * The community package merges the files of every recovered episode into
    one folder, so all worlds except Wonderland are present at once.

What this module does:
  * `install_save` seeds savegame.dat from one of the dump's per-world save
    files (savegame(island).dat etc.) so you can start at any world.
  * `install_patches` supplies a stand-in for the lost Wonderland episode that
    ends at once, so a playthrough continues from the Island to Agrabah. The
    download itself isn't served: the dead server can't be reached.
"""

from __future__ import annotations

import glob
import os
import re
from typing import Optional

from .files import backup_progress_file
# the Wonderland theme lookup lives in paths (standard library only) so the launcher can check it too
from .paths import MUSIC_EXTS, find_wonderland_music  # noqa: F401

WORLDS = ("training", "island", "wonderland", "agrabah", "castle")
ALIASES = {"maleficent": "castle", "maleficient": "castle", "maleficents": "castle",
           "castle": "castle", "island": "island", "swashbuckler": "island",
           "agrabah": "agrabah", "wonderland": "wonderland", "training": "training"}
MISSING_WORLDS = {"wonderland"}


def find_save_files(game_root: str) -> dict:
    """{world: path} for savegame(<name>).dat files next to the dump."""
    out = {}
    for p in glob.glob(os.path.join(game_root, "savegame*.dat")) + \
            glob.glob(os.path.join(game_root, "saves", "*.dat")):
        m = re.search(r"\(([^)]+)\)", os.path.basename(p)) or \
            re.match(r"(?:savegame[_-])?([a-z]+)\.dat$", os.path.basename(p).lower())
        if m:
            world = ALIASES.get(m.group(1).lower())
            if world:
                out[world] = p
    return out


def save_world(data: bytes) -> Optional[str]:
    """Current world named inside a savegame.dat, if any."""
    for w in WORLDS:
        if w.encode() in data:
            return w
    return None


def install_save(emu, world: str) -> str:
    world = ALIASES.get(world.lower(), world.lower())
    saves = find_save_files(emu.game_root)
    if world not in saves:
        raise SystemExit(f"no save for '{world}' found; available: {', '.join(sorted(saves)) or 'none'}")
    data = open(saves[world], "rb").read()
    overlay = os.path.join(emu.data_dir, "files")
    os.makedirs(overlay, exist_ok=True)
    target = os.path.join(overlay, "savegame.dat")
    if os.path.isfile(target):
        with open(target, "rb") as f:
            current = f.read()
        stock = [open(p, "rb").read() for p in saves.values()]
        if current != data and current not in stock:
            # a real save with progress: keep a copy before replacing it
            kept = backup_progress_file(target, os.path.join(emu.data_dir, "save_backups"), emu.log)
            emu.log("[chapters] WARNING: --start replaces your current save with the dump's "
                    f"starting {world} save" + (f"; your old one was copied to {kept}" if kept else ""))
    with open(target, "wb") as f:
        f.write(data)
    emu.log(f"[chapters] savegame.dat seeded from {os.path.basename(saves[world])} (world: {world})")
    return world


# island_exit.m3g ends Swashbuckler's Island with this script line. The
# replacement keeps the byte length (scripts are length-prefixed); the
# script parser ignores the trailing spaces.
WONDERLAND_SUMMARY = b"summary wonderland"
AGRABAH_SUMMARY = b"summary agrabah   "


# The world file training.m3g starts with this root script; the stand-in
# Wonderland world is a copy whose root script just ends the world at once.
TRAINING_ROOT_SCRIPT_START = b"if SECTION6\r\n"


def make_wonderland_world(training_m3g: bytes) -> bytes:
    """A stand-in wonderland.m3g: training.m3g with its root script replaced by
    `summary agrabah` (same length, padded with spaces). Loading it makes the
    game show the Summary, autosave and move on to Agrabah's journal and splash."""
    from . import m3g
    for comp, raw in m3g.read_sections(training_m3g):
        i = raw.find(TRAINING_ROOT_SCRIPT_START)
        if i < 0:
            continue
        # the script text runs up to the first non-text byte
        j = i
        while j < len(raw) and (32 <= raw[j] < 127 or raw[j] in (9, 10, 13)):
            j += 1
        old = raw[i:j]
        new = b"summary agrabah".ljust(len(old), b" ")
        patched, n = m3g.replace_text(training_m3g, old, new)
        if n:
            return patched
    raise ValueError("training.m3g root script not found")


def install_patches(emu, skip_wonderland: bool = True):
    """Handle the lost Wonderland episode (the dump on disk is never modified).

    The Island's ending says `summary wonderland`, which makes the game show
    the Wonderland journal text and splash screen (both survive in the dump),
    then look for wonderland.m3g. That file is lost, so khvcemu supplies a
    stand-in that immediately ends the world with `summary agrabah`: Continue
    on the Wonderland splash leads on to Agrabah. If a Wonderland theme is
    present (see find_wonderland_music) it plays on the Wonderland splash as
    wonderland.mid, the name the game asks for."""
    from . import m3g
    if not skip_wonderland:
        return
    vfs = emu.vfs
    if vfs.resolve("wonderland.m3g") is None:
        training = vfs.read_file("training.m3g")
        try:
            world = make_wonderland_world(training) if training else None
        except ValueError:
            world = None
        if world:
            vfs.virtual["wonderland.m3g"] = lambda: world
        else:
            # fall back to skipping the Wonderland screens altogether
            def reroute(data: bytes) -> bytes:
                patched, n = m3g.replace_text(data, WONDERLAND_SUMMARY, AGRABAH_SUMMARY)
                if n:
                    emu.log("[chapters] Wonderland is lost media: Swashbuckler's Island will "
                            "continue to Agrabah")
                return patched
            vfs.patchers["island_exit.m3g"] = reroute
            return
    if vfs.resolve("wonderland.mid") is None:
        music = find_wonderland_music(emu.game_root)
        if music:
            def load(path=music):
                with open(path, "rb") as f:
                    return f.read()
            vfs.virtual["wonderland.mid"] = load
            emu.logv(f"[chapters] Wonderland splash music: {music}")
