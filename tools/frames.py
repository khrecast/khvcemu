"""Dump frames to PNGs while running headless: frames.py <root> <outdir> [--ms N] [--every MS] [--keys t:key,...]"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pygame
from khvcemu.runtime import Emulator
from khvcemu.keys import AVK

ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("out")
ap.add_argument("--data", default=None)
ap.add_argument("--ms", type=int, default=10000)
ap.add_argument("--every", type=int, default=500)
ap.add_argument("--keys", default="", help="comma list of time_ms:KEY[:hold_ms], e.g. 9000:SELECT")
ap.add_argument("--save", default=None, help="chapter save to start from (island/agrabah/castle)")
ap.add_argument("-v", action="store_true")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
emu = Emulator(a.root, a.data or os.path.join(a.out, "data"), verbose=a.v, realtime=False, audio=False)
if a.save:
    from khvcemu.chapters import install_save
    install_save(emu, a.save)
emu.start()
keys = []
for k in filter(None, a.keys.split(",")):
    parts = k.split(":")
    keys.append((int(parts[0]), parts[1], int(parts[2]) if len(parts) > 2 else 120))
def save(t):
    f = emu.last_frame
    if f is None: return
    f = f.astype(np.uint32)
    rgb = np.stack([((f >> 11) & 31) * 255 // 31, ((f >> 5) & 63) * 255 // 63, (f & 31) * 255 // 31], -1).astype(np.uint8)
    pygame.image.save(pygame.surfarray.make_surface(rgb.transpose(1, 0, 2)), os.path.join(a.out, f"f{t:06d}.png"))
t = 0
pending_up = []
while t < a.ms:
    for kt, name, hold in keys:
        if kt == t:
            emu.key_down(AVK[name]); pending_up.append((t + hold, name))
    for ut, name in list(pending_up):
        if ut == t:
            emu.key_up(AVK[name]); pending_up.remove((ut, name))
    emu.advance(10); emu.run_due()
    t += 10
    if t % a.every == 0:
        save(t)
print(f"frames={emu.frames} faults={emu.faults}")
