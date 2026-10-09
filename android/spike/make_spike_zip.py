"""Pack what the phone needs for Spike 0 (Termux) into one zip, to copy to the phone.

    python android/spike/make_spike_zip.py [--game <folder with mif/ and mod/>] [--out build/spike/recast_spike.zip]

The zip holds the khvcemu package, the benchmark, the Termux script and, from the game folder, mif/, mod/
and savegame(island).dat (the Island scene needs that save). The game files are copyrighted: the zip is for
your own phone only, it is written under build/ (ignored by git) and must never be committed or shared.
"""
import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME_FILES = ("mif", "mod", "savegame(island).dat")


def add_tree(z: zipfile.ZipFile, src: str, dst: str, skip=("__pycache__",)):
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.lower().endswith((".pyc", ".pyo", ".flac", ".wav", ".mp3", ".ogg")):   # no recordings, ever
                continue
            full = os.path.join(base, f)
            z.write(full, os.path.join(dst, os.path.relpath(full, src)).replace("\\", "/"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default=ROOT, help="folder with mif/ and mod/ (default: the repo folder)")
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "spike", "recast_spike.zip"))
    a = ap.parse_args(argv)
    for name in GAME_FILES:
        if not os.path.exists(os.path.join(a.game, name)):
            sys.exit(f"missing {name} in {a.game}")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
        add_tree(z, os.path.join(ROOT, "khvcemu"), "recast_spike/khvcemu")
        z.write(os.path.join(ROOT, "android", "spike", "bench_headless.py"), "recast_spike/android/spike/bench_headless.py")
        z.write(os.path.join(ROOT, "android", "spike", "termux_spike.sh"), "recast_spike/android/spike/termux_spike.sh")
        for name in GAME_FILES:
            full = os.path.join(a.game, name)
            if os.path.isdir(full):
                add_tree(z, full, "recast_spike/game/" + name)
            else:
                z.write(full, "recast_spike/game/" + name)
    print(f"{a.out}  {os.path.getsize(a.out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
