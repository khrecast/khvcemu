"""Benchmark every combination of the 3D engine speed patches (khvcemu/swerve_patch.py) on the headless Island scenes.

    python tools/bench_speed_patches.py --root <game folder> [--reps 3] [--patches span,matinv,float]

Each combination runs in its own process (android/spike/bench_headless.py world, on the virtual clock, so the numbers
are the emulator's speed and not the game's pace); the combinations are interleaved over the repetitions, so a slow
minute on the machine hits all of them alike. Prints, per combination and scene, the median and best real-time factor
(1.0 = the 25 fps the game asks for) and checks that every combination drew exactly the same frames (a digest of every
frame). Needs the game files. Takes about 45 s per run: 8 combinations x 3 repetitions is about 18 minutes; keep the
PC otherwise idle while it runs.
"""
import argparse
import itertools
import json
import os
import random
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BENCH = os.path.join(ROOT, "android", "spike", "bench_headless.py")


def run_once(game: str, names: tuple) -> dict:
    env = dict(os.environ, KH_SPEED_PATCHES=",".join(names), SDL_AUDIODRIVER="dummy", KH_DUMP=game)
    out = subprocess.run([sys.executable, BENCH, "--root", game, "world"], env=env, capture_output=True, text=True,
                         timeout=600).stdout
    r = {}
    for line in out.splitlines():
        if line.startswith("{"):
            d = json.loads(line)
            if d.get("label") in ("world_scene_a", "world_scene_b"):
                r[d["label"]] = d
            if "frame_digest" in d:
                r["digest"] = d["frame_digest"]
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="folder with mif/, mod/ and savegame(island).dat")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--patches", default="span,matinv,float", help="the patches to combine (all subsets are run)")
    a = ap.parse_args()
    names = [n for n in a.patches.split(",") if n]
    combos = [c for k in range(len(names) + 1) for c in itertools.combinations(names, k)]
    results = {c: [] for c in combos}
    for rep in range(a.reps):
        order = combos[:]
        random.Random(rep).shuffle(order)
        for c in order:
            r = run_once(a.root, c)
            results[c].append(r)
            print(f"rep {rep + 1}/{a.reps} [{','.join(c) or 'none'}]: "
                  + "  ".join(f"{k[-1]}={v['realtime_factor']:.3f}" for k, v in sorted(r.items()) if k.startswith("world")),
                  flush=True)
    base = {s: statistics.median(r[s]["realtime_factor"] for r in results[()]) for s in ("world_scene_a", "world_scene_b")}
    print()
    print(f"{'patches':26} {'scene A median (best)':>24} {'vs none':>8} {'scene B median (best)':>24} {'vs none':>8}")
    for c in sorted(combos, key=lambda c: (len(c), c)):
        cells = []
        for s in ("world_scene_a", "world_scene_b"):
            v = [r[s]["realtime_factor"] for r in results[c] if s in r]
            med = statistics.median(v)
            cells.append(f"{med:>14.3f} ({max(v):.3f}) {100 * (med / base[s] - 1):>+7.1f}%")
        print(f"{','.join(c) or 'none':26} {cells[0]:>34} {cells[1]:>34}")
    digests = {r.get("digest") for rs in results.values() for r in rs}
    print()
    print("every combination drew the same frames" if len(digests) == 1 else f"FRAMES DIFFER: {digests}")


if __name__ == "__main__":
    main()
