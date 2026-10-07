"""Speed and picture check from a save state, with scripted key presses (for scenes the headless boot cannot reach,
such as a fight).

    python tools/bench_state.py --root <game folder> --state 9 --seconds 12 [--keys mash] [--reps 2]

Copies the state (slot 1-9 or auto, auto2, auto3, from your own states folder) into a scratch data folder, resumes it
on the virtual clock for each combination of the 3D speed patches, plays a fixed key script, and prints the real-time
factor (1.0 = the 25 fps the game asks for) and a digest of every frame drawn. Equal digests mean the patches changed
no pixel. Nothing in your own data folder is written.

--keys mash   walk right and press the action key (SELECT) every 0.4 s, with a turn now and then: a fight, if there
              is one in front of you. --keys none: just let it run.
"""
import argparse
import hashlib
import itertools
import os
import random
import shutil
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def script(kind: str, seconds: float):
    """(time_ms, 'down'/'up', key) events."""
    ev = []
    if kind == "mash":
        t = 0
        step = 0
        while t < seconds * 1000:
            ev += [(t, "down", "SELECT"), (t + 120, "up", "SELECT")]
            if step % 6 == 0:
                ev += [(t, "down", "RIGHT"), (t + 900, "up", "RIGHT")]
            if step % 6 == 3:
                ev += [(t, "down", "LEFT"), (t + 700, "up", "LEFT")]
            if step % 9 == 5:
                ev += [(t, "down", "UP"), (t + 600, "up", "UP")]
            t += 400
            step += 1
    return sorted(ev)


def run_once(root, state_file, names, seconds, keys):
    from khvcemu.keys import AVK
    from khvcemu.runtime import Emulator
    data = tempfile.mkdtemp(prefix="khv_bench_state_")
    try:
        os.makedirs(os.path.join(data, "states"))
        shutil.copy(state_file, os.path.join(data, "states", "slot1.khs"))
        emu = Emulator(root, data, realtime=False, audio=False, log=lambda s: None, speed_patches=names)
        emu.load_state(os.path.join(data, "states", "slot1.khs"))
        events = script(keys, seconds)
        digest = hashlib.sha256()
        last = [-1]
        t = 0
        w0 = time.perf_counter()
        f0 = emu.frames
        while t < seconds * 1000:
            while events and events[0][0] <= t:
                _, what, k = events.pop(0)
                (emu.key_down if what == "down" else emu.key_up)(AVK[k])
            emu.advance(10)
            emu.run_due()
            t += 10
            if emu.frames != last[0] and emu.last_frame is not None:
                last[0] = emu.frames
                digest.update(emu.last_frame.tobytes())
        wall = time.perf_counter() - w0
        return {"factor": seconds / wall, "frames": emu.frames - f0, "faults": emu.faults, "digest": digest.hexdigest()[:16]}
    finally:
        shutil.rmtree(data, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--state", default="1", help="slot 1-9, auto, auto2 or auto3")
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--keys", choices=("mash", "none"), default="mash")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--patches", default="span,matinv")
    ap.add_argument("--sets", default="", help="patch sets to compare, separated by ';' (default: none and --patches)")
    a = ap.parse_args()
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from khvcemu.paths import game_data_dir
    from khvcemu.savestate import StateSlots
    path = StateSlots(type("E", (), {"data_dir": game_data_dir(a.root), "clock_ms": lambda s: 0})()).path(
        StateSlots.parse(a.state))
    if not os.path.isfile(path):
        sys.exit(f"no state at {path}")
    names = [n for n in a.patches.split(",") if n]
    combos = [(), tuple(names)]
    if a.sets:
        combos = [tuple(n for n in s.split(",") if n) for s in a.sets.split(";")]
    results = {c: [] for c in combos}
    for rep in range(a.reps):
        order = list(combos)
        random.Random(rep).shuffle(order)
        for c in order:
            r = run_once(a.root, path, list(c), a.seconds, a.keys)
            results[c].append(r)
            print(f"rep {rep + 1} [{','.join(c) or 'none'}]: {r['factor']:.3f}x  frames {r['frames']}  faults {r['faults']}  digest {r['digest']}",
                  flush=True)
    base = statistics.median(r["factor"] for r in results[combos[0]])
    print()
    for c in combos:
        med = statistics.median(r["factor"] for r in results[c])
        print(f"  {','.join(c) or 'none':40} {med:.3f}x  ({100 * (med / base - 1):+.1f}% vs {','.join(combos[0]) or 'none'})")
    digests = {r["digest"] for rs in results.values() for r in rs}
    print("same frames with and without the patches" if len(digests) == 1 else f"FRAMES DIFFER: {digests}")


if __name__ == "__main__":
    main()
