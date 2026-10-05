"""Development probe: boot the game headless for --ms of emulated time, report
faults/unimplemented calls (-v for everything, --trace for every BREW call)
and save the last frame.

    python tools/probe.py <dump> --ms 12000 -v
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu.runtime import Emulator  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("root")
ap.add_argument("--data", default=os.path.join(__import__("khvcemu.paths", fromlist=["data_home"]).data_home(), "probe"))
ap.add_argument("--ms", type=int, default=3000)
ap.add_argument("-v", action="store_true")
ap.add_argument("--trace", action="store_true")
ap.add_argument("--shot", default="probe_last_frame.png")
a = ap.parse_args()

emu = Emulator(a.root, a.data, verbose=a.v, realtime=False, audio=False)
emu.cpu.trace_calls = a.trace
emu.start()
t = 0
while t < a.ms:
    emu.advance(10)
    emu.run_due()
    t += 10
if emu.last_frame is not None:
    import numpy as np, pygame
    f = emu.last_frame.astype(np.uint32)
    rgb = np.stack([((f >> 11) & 31) * 255 // 31, ((f >> 5) & 63) * 255 // 63, (f & 31) * 255 // 31], -1).astype(np.uint8)
    pygame.image.save(pygame.surfarray.make_surface(rgb.transpose(1, 0, 2)), a.shot)
print(f"frames={emu.frames} faults={emu.faults} timers={len(emu.timers)}")
