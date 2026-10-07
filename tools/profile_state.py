"""Where does a scene spend its guest instructions? Resumes a save state and counts executed ARM instructions per
translated block while a key script plays (about 40 times slower than real time).

    python tools/profile_state.py --root <game folder> --state 7 [--seconds 3] [--warm 2] [--patches span,matinv,float]

Prints the hottest 256-byte regions and blocks (with the module they are in), the soft-float calls and the share of
the instructions each known region takes. Like tools/profile_guest.py but starting from your own save state, so it
reaches scenes the headless boot cannot (a fight, the lava). Needs the state in your states folder; nothing is written.
"""
import argparse
import collections
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# named regions of swv21brew.mod (loaded at 0x01000000) and kh.mod (0x00100000), found by profiling
REGIONS = [
    (0x0100A8B4, 0x0100AC0C, "span fill, generic (patched: span)"),
    (0x0100B1B8, 0x0100B2A0, "span fill, flat gouraud"),
    (0x0100E2E0, 0x0100E460, "span fill, textured"),
    (0x0101376C, 0x01013A80, "matrix inversion (patched: matinv)"),
    (0x0103ED00, 0x0103F900, "soft float library"),
    (0x01200000, 0x01400000, "speed patch code"),
    (0x00100000, 0x01000000, "kh.mod (the game)"),
]


def where(addr: int) -> str:
    for lo, hi, name in REGIONS:
        if lo <= addr < hi:
            return name
    return "swv21brew.mod, other" if 0x01000000 <= addr < 0x01200000 else "other"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--state", default="1")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--warm", type=float, default=2.0)
    ap.add_argument("--patches", default="span,matinv")
    ap.add_argument("--keys", choices=("mash", "none"), default="mash")
    a = ap.parse_args()
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import unicorn
    from unicorn.arm_const import UC_ARM_REG_CPSR
    from bench_state import script
    from khvcemu.keys import AVK
    from khvcemu.paths import game_data_dir
    from khvcemu.runtime import Emulator
    from khvcemu.savestate import StateSlots
    path = StateSlots(type("E", (), {"data_dir": game_data_dir(a.root), "clock_ms": lambda s: 0})()).path(
        StateSlots.parse(a.state))
    data = tempfile.mkdtemp(prefix="khv_prof_state_")
    try:
        os.makedirs(os.path.join(data, "states"))
        shutil.copy(path, os.path.join(data, "states", "slot1.khs"))
        emu = Emulator(a.root, data, realtime=False, audio=False, log=lambda s: None,
                       speed_patches=[n for n in a.patches.split(",") if n])
        emu.load_state(os.path.join(data, "states", "slot1.khs"))
        events = script(a.keys, a.warm + a.seconds + 1)
        t = 0

        def step(ms):
            nonlocal t
            end = t + ms
            while t < end:
                while events and events[0][0] <= t:
                    _, what, k = events.pop(0)
                    (emu.key_down if what == "down" else emu.key_up)(AVK[k])
                emu.advance(10)
                emu.run_due()
                t += 10
        step(int(a.warm * 1000))
        prof = {}

        def block(uc, addr, size, _ud):
            k = (addr, size, 1 if uc.reg_read(UC_ARM_REG_CPSR) & 0x20 else 0)
            prof[k] = prof.get(k, 0) + 1
        h = emu.cpu.uc.hook_add(unicorn.UC_HOOK_BLOCK, block)
        emu.cpu.uc.ctl_flush_tb()
        f0 = emu.frames
        step(int(a.seconds * 1000))
        emu.cpu.uc.hook_del(h)
        frames = emu.frames - f0
    finally:
        shutil.rmtree(data, ignore_errors=True)
    ins = {k: n * (k[1] // (2 if k[2] else 4)) for k, n in prof.items()}
    tot = sum(ins.values())
    print(f"state {a.state}: {frames} frames in {a.seconds:g} s of game time, {tot / 1e6:.0f} M guest instructions "
          f"({tot / max(frames, 1) / 1e6:.2f} M per frame)")
    by_region = collections.Counter()
    for (addr, _s, _t), c in ins.items():
        by_region[where(addr)] += c
    print("\nshare of instructions by region:")
    for name, c in by_region.most_common():
        print(f"  {100 * c / tot:5.1f}%  {name}")
    reg = collections.Counter()
    for (addr, _s, _t), c in ins.items():
        reg[addr >> 8] += c
    print("\nhottest 256-byte regions:")
    for r, c in reg.most_common(24):
        print(f"  {r << 8:08x}  {100 * c / tot:5.1f}%   {where(r << 8)}")
    print("\nhottest blocks (address, bytes, runs, share):")
    for (addr, size, th), c in sorted(ins.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {addr:08x} {size:3d}B {prof[(addr, size, th)]:9d} {100 * c / tot:5.1f}%   {where(addr)}")


if __name__ == "__main__":
    main()
