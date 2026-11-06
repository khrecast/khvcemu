"""Real-time frame rate: how many frames per real second the game actually shows, with and without the
frame-locked clock (Emulator(frame_locked_clock=...), `--no-frame-lock`).

    python tools/bench_realtime.py --root <game folder> [--seconds 15] [--scenes title,course,state:7,state:9]
                                   [--states <folder with slotN.khs>] [--modes off,on]

The virtual-clock benchmarks (android/spike/bench_headless.py, tools/bench_state.py) cannot show this: there the game's
own code takes no clock time. Here the clock is the real one, the loop is the desktop front end's loop (run_due, then
sleep until the next timer), and every frame is stamped with the real time it was drawn.

Scenes: `title` (the menu after boot), `course` (New Game, paged through the intro with Continue, then walking in the
Obstacle Course, the 3D training area), `state:N` (save-state slot N from --states, for example a fight or the lava
scene). Nothing is written to your saves: each run uses a fresh temporary data folder.
"""
import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from khvcemu.keys import AVK  # noqa: E402
from khvcemu.runtime import Emulator  # noqa: E402


class Run:
    """One emulator driven in real time, with its frame times recorded."""

    def __init__(self, root, locked, verbose=False, speed_patches=None):
        self.logs = []
        self.emu = Emulator(root, tempfile.mkdtemp(prefix="khvcemu_rt_"), realtime=True, audio=False,
                            log=self.logs.append, verbose=verbose, frame_locked_clock=locked,
                            speed_patches=speed_patches)
        self.stamps = []
        self.emu.frame_listeners.append(lambda f: self.stamps.append(time.perf_counter()))
        self.busy = 0.0

    def run(self, seconds, keys=(), until=None):
        """Run the loop for `seconds` of real time. keys: (seconds from now, 'down'|'up', KEY) presses."""
        emu = self.emu
        keys = sorted(keys)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            now = time.perf_counter() - t0
            while keys and keys[0][0] <= now:
                _, what, k = keys.pop(0)
                (emu.key_down if what == "down" else emu.key_up)(AVK[k])
            a = time.perf_counter()
            emu.run_due()
            self.busy += time.perf_counter() - a
            if until is not None and until():
                return True
            due = emu.next_due()
            wait = 0.002 if due is None else (due - emu.clock_ms()) / 1000
            if wait > 0.001:
                time.sleep(min(wait, 0.005))
        return False

    def measure(self, seconds, keys=()):
        n0, b0 = len(self.stamps), self.busy
        t0 = time.perf_counter()
        self.run(seconds, keys)
        wall = time.perf_counter() - t0
        st = self.stamps[n0:]
        gaps = [(b - a) * 1000 for a, b in zip(st, st[1:])]
        return {"fps": round(len(st) / wall, 1),
                "median_ms": round(statistics.median(gaps), 1) if gaps else None,
                "p95_ms": round(sorted(gaps)[int(len(gaps) * 0.95)], 1) if gaps else None,
                "host_busy": round(100 * (self.busy - b0) / wall), "faults": self.emu.faults}


def press(t, key, hold=0.15):
    return [(t, "down", key), (t + hold, "up", key)]


def scene_title(run, seconds):
    run.emu.start()
    run.run(8)
    return run.measure(seconds)


def reach_course(run):
    """New Game, then Continue through the intro pages until the Obstacle Course (training_part1) has loaded and
    the screen has settled. Returns True when it got there."""
    emu = run.emu
    emu.verbose = True                                             # the DrawText log lines say which screen it is
    emu.start()
    opened = []

    class Rec:
        def on_file_opened(self, name, mode):
            opened.append(name.lower())
    emu.hooks.append(Rec())
    mark = len(run.logs)
    deadline = time.perf_counter() + 150
    started = False
    while time.perf_counter() < deadline and not any("training_part1" in n for n in opened):
        run.run(1.5)
        drawn = [m.group(1) for line in run.logs[mark:] if "DrawText" in line
                 for m in [re.search(r"'(.*)'", line)] if m]
        mark = len(run.logs)
        if not started and "New Game" in drawn:
            run.run(0.15, press(0, "SELECT", 0.14))                # New Game is the first entry
            started = True
        elif "Continue" in drawn:
            run.run(0.15, press(0, "SOFT1", 0.14))                 # the left softkey carries Continue
    got = any("training_part1" in n for n in opened)
    emu.verbose = False
    emu.cpu.keep_recent_args = False
    run.run(8)
    return got


def scene_course(run, seconds):
    if not reach_course(run):
        print("warning: the Obstacle Course was not reached; measuring whatever is on screen", file=sys.stderr)
    return run.measure(seconds, press(0, "UP", seconds * 0.6) + press(seconds * 0.6, "LEFT", seconds * 0.2))


def scene_state(run, seconds, path):
    run.emu.start()
    run.run(1)
    run.emu.load_state(path)
    run.run(3)
    return run.measure(seconds)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=ROOT, help="the game folder (with mif/ and mod/)")
    ap.add_argument("--seconds", type=float, default=15, help="seconds of real time measured in each scene")
    ap.add_argument("--scenes", default="title,course", help="comma separated: title, course, state:N")
    ap.add_argument("--states", default=None,
                    help="folder with the save states (slotN.khs) for state:N (default: ~/.khvcemu/<game folder name>/states)")
    ap.add_argument("--modes", default="off,on", help="frame-locked clock: off, on or both (default both)")
    ap.add_argument("--speed-patches", default="all", choices=("all", "none"),
                    help="the 3D engine speed enhancements (default all, as the launcher has them)")
    a = ap.parse_args()
    if a.states is None:
        a.states = os.path.join(os.path.expanduser("~"), ".khvcemu", os.path.basename(os.path.abspath(a.root)), "states")
    rows = []
    for scene in [s.strip() for s in a.scenes.split(",") if s.strip()]:
        for mode in [m.strip() for m in a.modes.split(",") if m.strip()]:
            run = Run(a.root, locked=(mode == "on"), speed_patches=None if a.speed_patches == "all" else [])
            if scene == "title":
                r = scene_title(run, a.seconds)
            elif scene == "course":
                r = scene_course(run, a.seconds)
            elif scene.startswith("state:"):
                path = os.path.join(a.states, f"slot{scene.split(':')[1]}.khs")
                if not os.path.isfile(path):
                    print(json.dumps({"scene": scene, "skipped": f"no {path}"}))
                    continue
                r = scene_state(run, a.seconds, path)
            else:
                ap.error(f"unknown scene {scene}")
            r.update(scene=scene, frame_lock=mode, speed=a.speed_patches)
            rows.append(r)
            print(json.dumps(r), flush=True)
    print()
    print(f"{'scene':10} {'speed-ups':9} {'frame lock':10} {'fps':>6} {'median ms':>10} {'p95 ms':>8} {'host busy':>10} {'faults':>7}")
    for r in rows:
        print(f"{r['scene']:10} {r['speed']:9} {r['frame_lock']:10} {r['fps']:>6} {r['median_ms']:>10} {r['p95_ms']:>8} "
              f"{str(r['host_busy']) + '%':>10} {r['faults']:>7}")


if __name__ == "__main__":
    main()
