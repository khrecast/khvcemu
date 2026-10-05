"""IImage (BMP/PNG resources) decoded on the host with pygame."""

from __future__ import annotations

import io
import struct
from typing import TYPE_CHECKING, Optional

import numpy as np

from .display import AEE_RO_TRANSPARENT, Dib, blit
from .hle import SUCCESS, HleObject

if TYPE_CHECKING:
    from .runtime import Emulator

IPARM_SIZE, IPARM_OFFSET, IPARM_CXFRAME, IPARM_NFRAMES, IPARM_RATE, IPARM_ROP = 1, 2, 3, 4, 5, 6
IPARM_DISPLAY = 7


def decode_image(raw: bytes):
    """-> (rgb565 (h,w) uint16, alpha mask (h,w) bool)."""
    import pygame
    surf = pygame.image.load(io.BytesIO(raw))
    has_alpha = surf.get_flags() & pygame.SRCALPHA or surf.get_colorkey() is not None
    if surf.get_colorkey() is not None:
        surf = surf.convert_alpha() if pygame.display.get_init() and pygame.display.get_surface() else surf
    rgb = pygame.surfarray.array3d(surf).transpose(1, 0, 2).astype(np.uint16)
    try:
        alpha = pygame.surfarray.array_alpha(surf).T > 127
    except Exception:
        alpha = np.ones(rgb.shape[:2], bool)
    ck = surf.get_colorkey()
    if ck is not None:
        alpha &= ~((rgb[..., 0] == ck[0]) & (rgb[..., 1] == ck[1]) & (rgb[..., 2] == ck[2]))
    px = ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)
    return px.astype(np.uint16), alpha


class Image(HleObject):
    IFACE = "IImage"
    SLOTS = ("AddRef", "Release", "Draw", "DrawFrame", "GetInfo", "SetParm", "Start", "Stop",
             "SetStream", "HandleEvent", "Notify")

    def __init__(self, emu: "Emulator", px: np.ndarray, alpha: np.ndarray):
        super().__init__(emu)
        self.px, self.alpha = px, alpha
        self.h, self.w = px.shape
        self.cxframe = self.w
        self.nframes = 1
        self.rop = 0
        self.size = (self.w, self.h)
        self.offset = (0, 0)
        self._dib: Optional[Dib] = None

    @classmethod
    def from_bytes(cls, emu, raw: bytes):
        try:
            px, alpha = decode_image(raw)
        except Exception as e:
            emu.log(f"[image] decode failed: {e}")
            return None
        return cls(emu, px, alpha)

    def as_dib(self) -> Dib:
        if self._dib is None:
            d = Dib(self.emu, self.w, self.h, 16, persistent=True)
            key = 0xF81F
            arr = np.where(self.alpha, self.px, key).astype(np.uint16)
            d.store(arr)
            d.transparent = key
            self.cpu.w32(d.ptr + 16, key)
            self._dib = d
        return self._dib

    def on_final_release(self):
        self.emu.objects.pop(self.ptr, None)

    def _draw(self, frame, x, y, whole=False):
        disp = self.emu.display
        dib = self.as_dib()
        # whole: IImage_Draw paints the entire image even after IPARM_CXFRAME was set
        # (KH's 14x14 Mickey emblem is set to 7px frames but drawn with plain Draw, and
        # only DrawFrame/animation select a single frame).
        fw = self.cxframe if self.nframes > 1 and not whole else self.w
        sx = frame * fw + self.offset[0]
        w = min(self.size[0], fw) if self.size else fw
        h = min(self.size[1], self.h) if self.size else self.h
        rop = self.rop if self.rop else AEE_RO_TRANSPARENT
        blit(self.emu, disp.dest.ptr, x, y, w, h, dib.ptr, sx, self.offset[1], rop, disp.clip)

    def Draw(self, c):
        self._draw(0, c.sarg(1), c.sarg(2), whole=True)
        return None

    def DrawFrame(self, c):
        self._draw(c.sarg(1), c.sarg(2), c.sarg(3))
        return None

    def GetInfo(self, c):
        p = c.arg(1)
        if p:
            # AEEImageInfo { uint16 cx, cy, nColors; boolean bAnimated; uint16 cxFrame; }
            self.cpu.write(p, struct.pack("<HHHBxH", self.w, self.h, 256, int(self.nframes > 1),
                                          self.cxframe))
        return None

    def SetParm(self, c):
        parm, p1, p2 = c.arg(1), c.sarg(2), c.sarg(3)
        if parm == IPARM_CXFRAME and p1 > 0:
            self.cxframe = p1
            self.nframes = max(1, self.w // p1)
        elif parm == IPARM_NFRAMES and p1 > 0:
            self.nframes = p1
            self.cxframe = self.w // p1
        elif parm == IPARM_ROP:
            self.rop = p1
        elif parm == IPARM_SIZE:
            self.size = (p1, p2)
        elif parm == IPARM_OFFSET:
            self.offset = (p1, p2)
        else:
            self.emu.log_once(("iparm", parm), f"[image] SetParm({parm}, {p1}, {p2}) ignored")
        return None

    def Start(self, c):
        self._draw(0, c.sarg(1), c.sarg(2))
        return None

    def Stop(self, c):
        return None

    def HandleEvent(self, c):
        return 0

    def Notify(self, c):
        fn, user = c.arg(1), c.arg(2)
        if fn:
            self.emu.call_soon_args(fn, user, self.ptr, SUCCESS)
        return None
