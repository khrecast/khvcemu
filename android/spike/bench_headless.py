"""Headless speed benchmark for the Android feasibility spike.

Runs the unmodified khvcemu core on a virtual clock and prints one JSON line per
measurement, so the same numbers can be taken on a desktop, in Termux on a phone,
or inside the spike app (Chaquopy). Nothing in khvcemu/ is changed: the HLE trap
counter wraps Cpu._on_trap before the Emulator adds its hook.

    python bench_headless.py --root <game folder> boot          # boot to the title (11 s of game time)
    python bench_headless.py --root <game folder> world         # Island opening scene (3D), 2 x 10 s
    python bench_headless.py --root <game folder> audio         # render the nine tunes with the built-in synth
    options: --count (count guest instructions, about 40x slower), --traps (most called BREW
             functions), --tcg-mib N (Unicorn translation buffer size), --code <folder holding khvcemu/>

boot passes like tests/test_game.py's test_boots_to_title_menu: frames >= 200, faults 0, lit > 0.2.
world needs savegame(island).dat next to mif/ and mod/.
"""

import argparse
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=("boot", "world", "audio"))
ap.add_argument("--root", required=True, help="folder with mif/ and mod/ (and savegame(island).dat for world)")
ap.add_argument("--code", default=os.path.dirname(os.path.dirname(HERE)), help="folder that contains khvcemu/")
ap.add_argument("--data", default=None, help="scratch data folder (default: a temporary folder)")
ap.add_argument("--count", action="store_true", help="count guest instructions (block hook, slow)")
ap.add_argument("--traps", action="store_true", help="print the most called BREW functions")
ap.add_argument("--tcg-mib", type=int, default=0, help="Unicorn TCG buffer size in MiB (0 = Unicorn default)")
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.code))

import unicorn  # noqa: E402
from khvcemu import cpu as cpumod  # noqa: E402

TRAPS = [0]
FRAMES = [-1]
import hashlib
DIGEST = hashlib.sha256()
NAMES = collections.Counter()
INS = [0]
_on_trap = cpumod.Cpu._on_trap


def _counting(self, uc, addr, size, ud):
    TRAPS[0] += 1
    if a.traps:
        info = self.traps.get(addr)
        NAMES[info.name if info else "exit"] += 1
    return _on_trap(self, uc, addr, size, ud)


cpumod.Cpu._on_trap = _counting
if a.tcg_mib:
    _Uc = unicorn.Uc

    def _make_uc(arch, mode):
        uc = _Uc(arch, mode)
        uc.ctl_set_tcg_buffer_size(a.tcg_mib * 2**20)   # must come before the first mem_map
        return uc
    cpumod.Uc = _make_uc

from khvcemu import chapters  # noqa: E402
from khvcemu.keys import AVK  # noqa: E402
from khvcemu.runtime import Emulator  # noqa: E402


def peak_rss_mib():
    try:
        import resource                      # Linux, Android (Termux, Chaquopy), macOS
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / (2**20 if sys.platform == "darwin" else 1024), 1)
    except ImportError:
        pass
    try:                                     # Windows
        import ctypes
        import ctypes.wintypes as w

        class PMC(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + \
                       [(n, ctypes.c_size_t) for n in ("Peak", "WS", "a", "b", "c", "d", "e", "f")]
        c = PMC()
        c.cb = ctypes.sizeof(c)
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = w.HANDLE
        p = ctypes.windll.psapi
        p.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
        p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return round(c.Peak / 2**20, 1)
    except Exception:
        return None


def out(d):
    print(json.dumps(d), flush=True)


def step(emu, ms, events=()):
    t = 0
    events = sorted(events)
    while t < ms:
        while events and events[0][0] <= t:
            _, what, k = events.pop(0)
            (emu.key_down if what == "down" else emu.key_up)(AVK[k])
        emu.advance(10)
        emu.run_due()
        t += 10
        if emu.frames != FRAMES[0] and emu.last_frame is not None:     # every distinct frame goes into one digest
            FRAMES[0] = emu.frames
            DIGEST.update(emu.last_frame.tobytes())


def press(t, key, hold=150):
    return [(t, "down", key), (t + hold, "up", key)]


def measure(emu, ms, label, events=()):
    f0, tr0, i0 = emu.frames, TRAPS[0], INS[0]
    w0 = time.perf_counter()
    step(emu, ms, events)
    wall = time.perf_counter() - w0
    frames = emu.frames - f0
    r = {"label": label, "game_ms": ms, "wall_s": round(wall, 3), "realtime_factor": round(ms / 1000 / wall, 3),
         "frames": frames, "game_fps": round(frames / (ms / 1000), 2), "host_fps_capacity": round(frames / wall, 2),
         "ms_per_frame_wall": round(1000 * wall / max(1, frames), 2), "traps_per_game_s": round((TRAPS[0] - tr0) / (ms / 1000)),
         "faults": emu.faults, "peak_rss_mib": peak_rss_mib()}
    if emu.last_frame is not None:
        r["lit"] = round(float((emu.last_frame != 0).mean()), 3)
    if a.count:
        r["instructions"] = INS[0] - i0
        r["insns_per_game_s"] = round((INS[0] - i0) / (ms / 1000))
    if a.traps:
        r["top_traps"] = NAMES.most_common(8)
        NAMES.clear()
    out(r)
    return r


out({"platform": sys.platform, "python": sys.version.split()[0], "unicorn": unicorn.__version__, "mode": a.mode})

if a.mode == "audio":
    from khvcemu import midi_synth
    from khvcemu.audio import AudioEngine
    total = 0.0
    tunes = AudioEngine._game_tunes(a.root)
    for name, path in tunes:
        with open(path, "rb") as f:
            data = f.read()
        t = time.perf_counter()
        pcm = midi_synth.render_midi(data, None)
        dt = time.perf_counter() - t
        total += dt
        out({"tune": name, "render_s": round(dt, 2), "audio_s": round(len(pcm) / midi_synth.RATE, 1)})
    out({"tunes": len(tunes), "total_render_s": round(total, 2), "peak_rss_mib": peak_rss_mib()})
    sys.exit(0)

import atexit
import shutil
import tempfile
data_dir = a.data
if not data_dir:                              # a fresh folder each run, removed at the end
    data_dir = tempfile.mkdtemp(prefix="khvcemu_bench_")
    atexit.register(shutil.rmtree, data_dir, True)
logs = []
emu = Emulator(a.root, data_dir, realtime=False, audio=False, log=logs.append, verbose=(a.mode == "world"),
                   speed_patches=[n for n in os.environ.get("KH_SPEED_PATCHES", "span,matinv,float").split(",") if n])
out({"tcg_buffer_mib": emu.cpu.uc.ctl_get_tcg_buffer_size() / 2**20})
if a.count:
    from unicorn.arm_const import UC_ARM_REG_CPSR

    def _block(uc, addr, size, _ud):
        INS[0] += size // (2 if uc.reg_read(UC_ARM_REG_CPSR) & 0x20 else 4)
    emu.cpu.uc.hook_add(unicorn.UC_HOOK_BLOCK, _block)

t0 = time.perf_counter()
if a.mode == "boot":
    emu.start()
    out({"start_wall_s": round(time.perf_counter() - t0, 3)})
    r = measure(emu, 11000, "boot_to_title")
    ok = r["frames"] >= 200 and r["faults"] == 0 and r.get("lit", 0) > 0.2
    out({"title_reached": ok})
else:
    import re
    chapters.install_save(emu, "island")
    emu.start()
    step(emu, 14000, press(11000, "DOWN") + press(12000, "SELECT"))      # Load Game
    opened = []

    class _Rec:
        def on_file_opened(self, name, mode):
            opened.append(name.lower())
    emu.hooks.append(_Rec())
    t, mark = 0, len(logs)
    while t < 90000 and not any(n.startswith("island_") for n in opened):
        step(emu, 1500)                       # page through the journal and splash with Continue
        t += 1500
        drawn = [m.group(1) for line in logs[mark:] if "DrawText" in line for m in [re.search(r"'(.*)'", line)] if m]
        mark = len(logs)
        if "Continue" in drawn:
            step(emu, 150, press(0, "SOFT1", 140))
    out({"scene_loaded_after_ms": t, "loaded": any(n.startswith("island_") for n in opened)})
    emu.verbose = False
    emu.cpu.keep_recent_args = False
    step(emu, 8000)
    measure(emu, 10000, "world_scene_a")      # the opening cutscene and first dialogue (3D)
    measure(emu, 10000, "world_scene_b", press(0, "UP", 6000) + press(6000, "LEFT", 2000) + press(8000, "UP", 2000))
out({"frame_digest": DIGEST.hexdigest()[:16]})
