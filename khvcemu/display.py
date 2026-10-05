"""IDisplay and IBitmap/IDIB (16-bit RGB565 device bitmap).

IDIB layout (AEEBitmap.h): vtbl@0, pPaletteMap@4, pBmp@8, pRGB@12,
ncTransparent@16, cx@20 (u16), cy@22 (u16), nPitch@24 (s16), cntRGB@26,
nDepth@28 (u8), nColorScheme@29 (u8). Pixel buffers live in guest memory so
game code (and the Swerve renderer) can write them directly.

RGBVAL (AEE): MAKE_RGB(r,g,b) = r<<8 | g<<16 | b<<24.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Optional

import numpy as np

from .hle import EFAILED, ENOMEMORY, EUNSUPPORTED, SUCCESS, HleObject

if TYPE_CHECKING:
    from .runtime import Emulator

IDIB_COLORSCHEME_565 = 16
# AEERasterOp. XOR=1 and TRANSPARENT=6 are confirmed by zeebulator's traces;
# the rest follow the SDK enum order (OR, XOR, COPY, NOT, MERGENOT, ANDNOT,
# TRANSPARENT, ...). KH calls FillRect(viewport, 0, 7) right after the 3D
# render every frame; on the phone that left the 3D image intact, so op 7
# is implemented as a mask (dst & ~color), which is a no-op for color 0.
AEE_RO_OR = 0
AEE_RO_XOR = 1
AEE_RO_COPY = 2
AEE_RO_NOT = 3
AEE_RO_MERGENOT = 4
AEE_RO_ANDNOT = 5
AEE_RO_TRANSPARENT = 6
AEE_RO_MASK = 7


def apply_rop(dst, src, rop):
    """Combine src into dst (numpy uint16 arrays, same shape) in place."""
    if rop == AEE_RO_XOR:
        dst ^= src
    elif rop == AEE_RO_OR:
        dst |= src
    elif rop == AEE_RO_NOT:
        dst[...] = ~src
    elif rop == AEE_RO_MERGENOT:
        dst |= ~src
    elif rop in (AEE_RO_ANDNOT, AEE_RO_MASK):
        dst &= ~src
    else:  # COPY, TRANSPARENT (handled by caller), anything unknown
        dst[...] = src

# AEE font ids
AEE_FONT_NORMAL = 0x8000
AEE_FONT_BOLD = 0x8001
AEE_FONT_LARGE = 0x8002


def fix_text(text: str) -> str:
    """Game text is Windows-1252 widened byte-for-byte (e.g. 0x92 for an
    apostrophe); map the C1 range back to the characters the phone showed."""
    out = []
    for ch in text:
        o = ord(ch)
        if 0x80 <= o <= 0x9F:
            try:
                ch = bytes([o]).decode("cp1252")
            except UnicodeDecodeError:
                pass
        out.append(ch)
    return "".join(out)


def rgbval_to_565(v: int) -> int:
    r = (v >> 8) & 0xFF
    g = (v >> 16) & 0xFF
    b = (v >> 24) & 0xFF
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def n565_to_rgbval(n: int) -> int:
    r = ((n >> 11) & 0x1F) << 3
    g = ((n >> 5) & 0x3F) << 2
    b = (n & 0x1F) << 3
    return (r << 8) | (g << 16) | (b << 24)


class Dib(HleObject):
    IFACE = "IBitmap"
    SLOTS = ("AddRef", "Release", "QueryInterface", "RGBToNative", "NativeToRGB",
             "DrawPixel", "GetPixel", "SetPixels", "DrawHScanline", "FillRect", "BltIn",
             "BltOut", "GetInfo", "CreateCompatibleBitmap", "SetTransparencyColor",
             "GetTransparencyColor")
    OBJ_SIZE = 48

    def __init__(self, emu: "Emulator", w: int, h: int, depth: int = 16, buf: int = 0,
                 persistent: bool = False):
        super().__init__(emu)
        self.w, self.h, self.depth = w, h, depth
        self.pitch = ((w * depth + 31) // 32) * 4
        self.owns_buf = buf == 0
        self.buf = buf or emu.heap.malloc(self.pitch * h)
        self.persistent = persistent
        self.transparent = 0xF81F  # magenta, a common BREW default
        p = self.ptr
        cpu = self.cpu
        cpu.w32(p + 8, self.buf)
        cpu.w32(p + 16, self.transparent)
        cpu.w16(p + 20, w)
        cpu.w16(p + 22, h)
        cpu.w16(p + 24, self.pitch)
        cpu.w8(p + 28, depth)
        cpu.w8(p + 29, IDIB_COLORSCHEME_565 if depth == 16 else 0)

    # Game code may rewrite fields in the IDIB directly; re-read them.
    def sync(self):
        cpu, p = self.cpu, self.ptr
        self.buf = cpu.r32(p + 8)
        self.transparent = cpu.r32(p + 16) & 0xFFFF
        self.w = cpu.r16(p + 20)
        self.h = cpu.r16(p + 22)
        self.pitch = struct.unpack("<h", struct.pack("<H", cpu.r16(p + 24)))[0]
        self.depth = cpu.r8(p + 28)

    def pixels(self) -> np.ndarray:
        """Copy of the 16-bit pixels as an (h, w) array."""
        self.sync()
        raw = self.cpu.read(self.buf, abs(self.pitch) * self.h)
        arr = np.frombuffer(raw, dtype="<u2").reshape(self.h, abs(self.pitch) // 2)
        return arr[:, : self.w].copy()

    def store(self, arr: np.ndarray, y0: int = 0):
        """Write rows back (arr is (rows, w))."""
        pitch = abs(self.pitch)
        if pitch == self.w * 2:
            self.cpu.write(self.buf + y0 * pitch, arr.astype("<u2").tobytes())
        else:
            for i, row in enumerate(arr):
                self.cpu.write(self.buf + (y0 + i) * pitch, row.astype("<u2").tobytes())

    def on_final_release(self):
        if self.persistent:
            self.refs = 1
            return
        if self.owns_buf and self.buf:
            self.emu.heap.free(self.buf)
            self.buf = 0
        self.emu.objects.pop(self.ptr, None)

    def QueryInterface(self, c):
        pp = c.arg(2)
        if pp:
            self.cpu.w32(pp, self.ptr)
        self.refs += 1
        return SUCCESS

    def RGBToNative(self, c):
        return rgbval_to_565(c.arg(1))

    def NativeToRGB(self, c):
        return n565_to_rgbval(c.arg(1))

    def _clip(self, x, y, w, h):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        return x0, y0, x1, y1

    def fill(self, x, y, w, h, color, rop=2, clip=None):
        self.sync()
        x0, y0, x1, y1 = self._clip(x, y, w, h)
        if clip:
            cx, cy, cw, ch = clip
            x0, y0 = max(x0, cx), max(y0, cy)
            x1, y1 = min(x1, cx + cw), min(y1, cy + ch)
        if x1 <= x0 or y1 <= y0:
            return
        arr = self.pixels()
        region = arr[y0:y1, x0:x1]
        apply_rop(region, np.full(region.shape, color & 0xFFFF, np.uint16), rop)
        self.store(arr[y0:y1], y0)

    def DrawPixel(self, c):
        x, y, col, rop = c.sarg(1), c.sarg(2), c.arg(3), c.arg(4)
        self.fill(x, y, 1, 1, col, rop)
        return SUCCESS

    def GetPixel(self, c):
        x, y, p = c.sarg(1), c.sarg(2), c.arg(3)
        self.sync()
        if 0 <= x < self.w and 0 <= y < self.h and p:
            self.cpu.w32(p, self.cpu.r16(self.buf + y * abs(self.pitch) + 2 * x))
        return SUCCESS

    def SetPixels(self, c):
        cnt, pts, col, rop = c.arg(1), c.arg(2), c.arg(3), c.arg(4)
        for i in range(cnt):
            x, y = struct.unpack("<hh", self.cpu.read(pts + 4 * i, 4))
            self.fill(x, y, 1, 1, col, rop)
        return SUCCESS

    def DrawHScanline(self, c):
        y, x0, x1, col, rop = c.sarg(1), c.sarg(2), c.sarg(3), c.arg(4), c.arg(5)
        self.fill(x0, y, x1 - x0 + 1, 1, col, rop)
        return SUCCESS

    def FillRect(self, c):
        prc, col, rop = c.arg(1), c.arg(2), c.arg(3)
        x, y, w, h = struct.unpack("<hhhh", self.cpu.read(prc, 8))
        self.fill(x, y, w, h, col, rop)
        return SUCCESS

    def BltIn(self, c):
        xd, yd, dx, dy = c.sarg(1), c.sarg(2), c.sarg(3), c.sarg(4)
        src, xs, ys, rop = c.arg(5), c.sarg(6), c.sarg(7), c.arg(8)
        return blit(self.emu, self.ptr, xd, yd, dx, dy, src, xs, ys, rop)

    def BltOut(self, c):
        xd, yd, dx, dy = c.sarg(1), c.sarg(2), c.sarg(3), c.sarg(4)
        dst, xs, ys, rop = c.arg(5), c.sarg(6), c.sarg(7), c.arg(8)
        return blit(self.emu, dst, xd, yd, dx, dy, self.ptr, xs, ys, rop)

    def GetInfo(self, c):
        p, n = c.arg(1), c.arg(2)
        self.sync()
        if p:
            self.cpu.write(p, struct.pack("<III", self.w, self.h, self.depth)[: max(n, 12)])
        return SUCCESS

    def CreateCompatibleBitmap(self, c):
        pp, w, h = c.arg(1), c.arg(2) & 0xFFFF, c.arg(3) & 0xFFFF
        d = Dib(self.emu, w, h, 16)
        self.cpu.w32(pp, d.ptr)
        return SUCCESS

    def SetTransparencyColor(self, c):
        self.transparent = c.arg(1) & 0xFFFF
        self.cpu.w32(self.ptr + 16, self.transparent)
        return SUCCESS

    def GetTransparencyColor(self, c):
        p = c.arg(1)
        if p:
            self.cpu.w32(p, self.cpu.r32(self.ptr + 16))
        return SUCCESS


def blit(emu, dst_ptr, xd, yd, dx, dy, src_ptr, xs, ys, rop, clip=None) -> int:
    dst = emu.objects.get(dst_ptr)
    src = emu.objects.get(src_ptr)
    if not isinstance(dst, Dib):
        emu.log_once(("blt-dst", dst_ptr), f"[display] blit to unknown bitmap 0x{dst_ptr:08x}")
        return EUNSUPPORTED
    if not isinstance(src, Dib):
        img = getattr(src, "as_dib", None)
        src = img() if img else None
        if src is None:
            emu.log_once(("blt-src", src_ptr), f"[display] blit from unknown bitmap 0x{src_ptr:08x}")
            return EUNSUPPORTED
    sa = src.pixels()
    # clip the rectangle against both bitmaps
    if xs < 0:
        xd -= xs; dx += xs; xs = 0
    if ys < 0:
        yd -= ys; dy += ys; ys = 0
    if xd < 0:
        xs -= xd; dx += xd; xd = 0
    if yd < 0:
        ys -= yd; dy += yd; yd = 0
    dx = min(dx, src.w - xs, dst.w - xd)
    dy = min(dy, src.h - ys, dst.h - yd)
    if clip:
        cx, cy, cw, ch = clip
        if xd < cx:
            d = cx - xd; xd += d; xs += d; dx -= d
        if yd < cy:
            d = cy - yd; yd += d; ys += d; dy -= d
        dx = min(dx, cx + cw - xd)
        dy = min(dy, cy + ch - yd)
    if dx <= 0 or dy <= 0:
        return SUCCESS
    da = dst.pixels()
    patch = sa[ys:ys + dy, xs:xs + dx]
    region = da[yd:yd + dy, xd:xd + dx]
    if rop == AEE_RO_TRANSPARENT:
        mask = patch != (src.transparent & 0xFFFF)
        region[mask] = patch[mask]
    else:
        apply_rop(region, patch, rop)
    dst.store(da[yd:yd + dy], yd)
    return SUCCESS


class Display(HleObject):
    IFACE = "IDisplay"
    SLOTS = ("AddRef", "Release", "GetFontMetrics", "MeasureTextEx", "DrawText", "DrawRect",
             "BitBlt", "Update", "SetAnnunciators", "Backlight", "SetColor", "GetSymbol",
             "DrawFrame", "CreateDIBitmap", "SetDestination", "GetDestination",
             "GetDeviceBitmap", "SetFont", "SetClipRect", "GetClipRect", "Clone",
             "MakeDefault", "IsEnabled", "NotifyEnable", "CreateDIBitmapEx", "SetPrefs")

    CLR_USER_TEXT, CLR_USER_BACKGROUND, CLR_USER_LINE = 1, 2, 3

    def __init__(self, emu: "Emulator", w: int, h: int):
        super().__init__(emu)
        self.device = Dib(emu, w, h, 16, persistent=True)
        self.dest = self.device
        self.colors = {1: 0x00000000, 2: 0xFFFFFF00, 3: 0x00000000}
        self.clip: Optional[tuple] = None
        self.font = None
        self.frames = 0

    def AddRef(self, c):
        return 2

    def Release(self, c):
        return 1

    # --------------------------------------------------------- text
    # The phone's system font is gone (the game asks for a font class,
    # 0x0100a004, that no file provides), so text uses a host font. Verdana
    # is on every Windows PC and stays crisp and readable at phone sizes; the others
    # are fallbacks for macOS/Linux. Override with --font / --font-size.
    FONT_CANDIDATES = "verdana,dejavusans,tahoma,segoeui,arial,liberationsans,freesans,helvetica"
    FONT_SIZE = 11

    def _font(self, font_id: int = AEE_FONT_NORMAL, mult: int = 1):
        """Host font for a game font id. mult > 1 gives the same face at
        mult x the size, used for the high-resolution text overlay."""
        cache = self.__dict__.setdefault("_fonts", {})
        font_id = font_id if font_id in (AEE_FONT_NORMAL, AEE_FONT_BOLD, AEE_FONT_LARGE) else AEE_FONT_NORMAL
        f = cache.get((font_id, mult))
        if f is None:
            try:
                import pygame
                pygame.font.init()
                size = getattr(self.emu, "font_size", None) or self.FONT_SIZE
                names = getattr(self.emu, "font_name", None) or self.FONT_CANDIDATES
                bold = font_id in (AEE_FONT_BOLD, AEE_FONT_LARGE)
                if font_id == AEE_FONT_LARGE:
                    size += 3
                if pygame.font.match_font(names) is None:
                    # pygame's built-in font is heavy and wide: go a size down
                    f = pygame.font.Font(None, (size + 2) * mult)
                    f.set_bold(False)
                else:
                    f = pygame.font.SysFont(names, size * mult, bold=bold)
            except Exception:
                f = False
            cache[(font_id, mult)] = f
        return f

    def _height(self, font_id=AEE_FONT_NORMAL):
        f = self._font(font_id)
        if not f:
            return 10, 3
        return f.get_ascent(), abs(f.get_descent())

    def GetFontMetrics(self, c):
        font_id, pa, pd = c.arg(1), c.arg(2), c.arg(3)
        asc, desc = self._height(font_id)
        if pa:
            self.cpu.w32(pa, asc)
        if pd:
            self.cpu.w32(pd, desc)
        return asc + desc

    def _measure(self, text, font_id=AEE_FONT_NORMAL):
        f = self._font(font_id)
        return f.size(text)[0] if f and text else (6 * len(text) if not f else 0)

    def MeasureTextEx(self, c):
        font_id, ptxt, n, maxw, pfits = c.arg(1), c.arg(2), c.sarg(3), c.sarg(4), c.arg(5)
        text = fix_text(self.cpu.wstr(ptxt))
        if n >= 0:
            text = text[:n]
        fits = len(text)
        if maxw > 0:
            while fits > 0 and self._measure(text[:fits], font_id) > maxw:
                fits -= 1
        if pfits:
            self.cpu.w32(pfits, fits)
        return self._measure(text[:fits], font_id)

    def DrawText(self, c):
        font_id, ptxt, n, x, y, prc, flags = c.arg(1), c.arg(2), c.sarg(3), c.sarg(4), c.sarg(5), c.arg(6), c.arg(7)
        text = self.cpu.wstr(ptxt)
        if n >= 0:
            text = text[:n]
        text = fix_text(text)
        pt = getattr(self.emu, "playtime", None)
        if pt:
            pt.text_drawn(text, x, y)
        if text.startswith("Loading"):                 # "Loading....." between areas (not "Downloading")
            self.emu.last_loading_ms = self.emu.clock_ms()
        rect = struct.unpack("<hhhh", self.cpu.read(prc, 8)) if prc else None
        self.emu.logv(f"[display] DrawText font=0x{font_id:x} '{text}' @({x},{y}) flags=0x{flags:x}")
        f = self._font(font_id)
        dst = self.dest
        fg = rgbval_to_565(self.colors[self.CLR_USER_TEXT])
        if flags & 0x2 and rect:     # IDF_ALIGN_CENTER
            x = rect[0] + (rect[2] - self._measure(text, font_id)) // 2
        if flags & 0x20 and rect:    # IDF_ALIGN_MIDDLE
            y = rect[1] + (rect[3] - sum(self._height(font_id))) // 2
        if not f or not text:
            return SUCCESS
        import pygame
        surf = f.render(text, False, (255, 255, 255))
        mask = pygame.surfarray.array_alpha(surf).T if surf.get_flags() & pygame.SRCALPHA else \
            (pygame.surfarray.array3d(surf).sum(axis=2).T > 0)
        mask = mask > 0
        arr = dst.pixels()
        h, w = mask.shape
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(dst.w, x + w), min(dst.h, y + h)
        if rect and not self.clip:
            x0, y0 = max(x0, rect[0]), max(y0, rect[1])
            x1, y1 = min(x1, rect[0] + rect[2]), min(y1, rect[1] + rect[3])
        if self.clip:
            cx, cy, cw, ch = self.clip
            x0, y0 = max(x0, cx), max(y0, cy)
            x1, y1 = min(x1, cx + cw), min(y1, cy + ch)
        if x1 > x0 and y1 > y0:
            sub = mask[y0 - y:y1 - y, x0 - x:x1 - x]
            region = arr[y0:y1, x0:x1]
            if dst is self.device:
                self._record_text(text, font_id, x, y, (x0, y0, x1, y1), sub, region.copy(), fg, (w, h))
            region[sub] = fg
            dst.store(arr[y0:y1], y0)
        return SUCCESS

    # ------------------------------------------------ high-resolution text
    # Text is still rasterised into the 176x220 device bitmap (the game may
    # read it back, and tests/screenshots use it), but every string drawn
    # straight onto the screen is also remembered. At present time the
    # frontend gets a copy of the frame with those glyph pixels swapped back
    # for the background that was under them, plus the strings, and draws the
    # strings at window resolution with smoothing. A string is only kept
    # while it is still on screen, so anything the game paints over (or
    # redraws) falls back to the plain low-res text.
    #
    # "Still on screen" is decided by rebuilding what the string's box looked
    # like right after it was drawn (the background it was drawn on, with the
    # glyph pixels in the text color) and comparing the whole box against the
    # frame. Looking only at the glyph pixels is not enough, nor is looking at
    # glyphs and surroundings as two separate fractions: a later screen can
    # repaint the glyph pixels the same color (a black selection bar under black
    # text, a white page under white "Loading") and leave part of the old
    # surroundings alone, and each half then passes on its own. The old
    # background would be pasted back in glyph shape: a ghost of text the game
    # stopped drawing. Text the game still shows matches ~100% of its box; a
    # ghost matches well under 75%.
    MAX_TEXT_ITEMS = 300
    MATCH_FRACTION = 0.9

    def _record_text(self, text, font_id, x, y, box, mask, bg, fg, size):
        items = self.__dict__.setdefault("text_items", [])
        key = (font_id, x, y, fg)
        for old in items:
            if old["key"] == key:
                # A label redrawn in place (or grown, like "Loading...") replaces its
                # older version; inherit the true background under the old glyphs.
                ox0, oy0, ox1, oy1 = old["box"]
                bx0, by0, bx1, by1 = box
                ix0, iy0, ix1, iy1 = max(ox0, bx0), max(oy0, by0), min(ox1, bx1), min(oy1, by1)
                if ix1 > ix0 and iy1 > iy0:
                    om = old["mask"][iy0 - oy0:iy1 - oy0, ix0 - ox0:ix1 - ox0]
                    ob = old["bg"][iy0 - oy0:iy1 - oy0, ix0 - ox0:ix1 - ox0]
                    tgt = bg[iy0 - by0:iy1 - by0, ix0 - bx0:ix1 - bx0]
                    tgt[om] = ob[om]
                items.remove(old)
                break
        items.append({"key": key, "text": text, "font_id": font_id, "x": x, "y": y, "box": box,
                      "mask": mask, "bg": bg, "fg": fg, "size": size})
        if len(items) > self.MAX_TEXT_ITEMS:
            del items[: len(items) - self.MAX_TEXT_ITEMS]

    def build_overlay(self, frame):
        """(clean_frame, [items]) for the frame just presented, or None.
        Items are checked newest first so text drawn over text unwinds."""
        items = self.__dict__.get("text_items")
        if not items:
            return None
        cur = frame.copy()
        keep = []
        for it in reversed(items):
            x0, y0, x1, y1 = it["box"]
            m = it["mask"]
            reg = cur[y0:y1, x0:x1]
            if reg.shape != m.shape or not m.any():
                continue
            expected = it["bg"].copy()
            expected[m] = it["fg"]
            if (reg == expected).mean() < self.MATCH_FRACTION:
                continue                                  # painted over, or a ghost
            reg[m] = it["bg"][m]
            keep.append(it)
        keep.reverse()
        self.text_items = keep
        return (cur, keep) if keep else None

    def hires_text(self, it, k: float):
        """Anti-aliased pygame surface for a recorded string at window scale k."""
        import math
        import pygame
        w, h = it["size"]
        tw, th = max(1, round(w * k)), max(1, round(h * k))
        mult = max(2, math.ceil(k))
        key = (it["text"], it["font_id"], it["fg"], tw, th, mult)
        cache = self.__dict__.setdefault("_hires", {})
        s = cache.get(key)
        if s is None:
            f = self._font(it["font_id"], mult)
            if not f:
                return None
            fg = it["fg"]
            rgb = (((fg >> 11) & 31) * 255 // 31, ((fg >> 5) & 63) * 255 // 63, (fg & 31) * 255 // 31)
            s = f.render(it["text"], True, rgb)
            if s.get_size() != (tw, th):
                s = pygame.transform.smoothscale(s, (tw, th))
            if len(cache) > 600:
                cache.clear()
            cache[key] = s
        return s

    # --------------------------------------------------------- drawing
    def SetColor(self, c):
        which, val = c.arg(1), c.arg(2)
        prev = self.colors.get(which, 0)
        self.colors[which] = val
        return prev

    def DrawRect(self, c):
        prc, frame, fill, flags = c.arg(1), c.arg(2), c.arg(3), c.arg(4)
        x, y, w, h = struct.unpack("<hhhh", self.cpu.read(prc, 8))
        dst = self.dest
        if flags & 0x2:   # IDF_RECT_FILL
            dst.fill(x, y, w, h, rgbval_to_565(fill), clip=self.clip)
        if flags & 0x1:   # IDF_RECT_FRAME
            col = rgbval_to_565(frame)
            dst.fill(x, y, w, 1, col, clip=self.clip)
            dst.fill(x, y + h - 1, w, 1, col, clip=self.clip)
            dst.fill(x, y, 1, h, col, clip=self.clip)
            dst.fill(x + w - 1, y, 1, h, col, clip=self.clip)
        return SUCCESS

    def DrawFrame(self, c):
        return SUCCESS

    def BitBlt(self, c):
        xd, yd, dx, dy = c.sarg(1), c.sarg(2), c.sarg(3), c.sarg(4)
        src, xs, ys, rop = c.arg(5), c.sarg(6), c.sarg(7), c.arg(8)
        return blit(self.emu, self.dest.ptr, xd, yd, dx, dy, src, xs, ys, rop, self.clip)

    def Update(self, c):
        self.frames += 1
        self.emu.present(self.device)
        self.emu.overlay = (self.build_overlay(self.emu.last_frame)
                            if getattr(self.emu, "hires_text", False) else None)
        return None

    def SetAnnunciators(self, c):
        return SUCCESS

    def Backlight(self, c):
        return SUCCESS

    def IsEnabled(self, c):
        return 1

    def NotifyEnable(self, c):
        return SUCCESS

    def SetFont(self, c):
        return 0

    def GetSymbol(self, c):
        return 0

    def SetClipRect(self, c):
        p = c.arg(1)
        self.clip = struct.unpack("<hhhh", self.cpu.read(p, 8)) if p else None
        return None

    def GetClipRect(self, c):
        p = c.arg(1)
        rc = self.clip or (0, 0, self.dest.w, self.dest.h)
        if p:
            self.cpu.write(p, struct.pack("<hhhh", *rc))
        return None

    # --------------------------------------------------------- bitmaps
    def GetDeviceBitmap(self, c):
        pp = c.arg(1)
        if pp:
            self.cpu.w32(pp, self.device.ptr)
        self.device.refs += 1
        return SUCCESS

    def SetDestination(self, c):
        p = c.arg(1)
        obj = self.emu.objects.get(p) if p else self.device
        prev = self.dest
        if isinstance(obj, Dib):
            self.dest = obj
        elif p:
            self.emu.log_once(("setdest", p), f"[display] SetDestination unknown 0x{p:08x}")
        return prev.ptr

    def GetDestination(self, c):
        self.dest.refs += 1
        return self.dest.ptr

    def CreateDIBitmap(self, c):
        pp, depth, w, h = c.arg(1), c.arg(2) & 0xFF, c.arg(3) & 0xFFFF, c.arg(4) & 0xFFFF
        return self._new_dib(pp, depth, w, h)

    def CreateDIBitmapEx(self, c):
        pp, depth, h, w = c.arg(1), c.arg(2) & 0xFF, c.arg(3) & 0xFFFF, c.arg(4) & 0xFFFF
        return self._new_dib(pp, depth, w, h)

    def _new_dib(self, pp, depth, w, h):
        if w <= 0 or h <= 0:
            return EFAILED
        d = Dib(self.emu, w, h, depth if depth in (8, 16) else 16)
        if not d.buf:
            return ENOMEMORY
        if pp:
            self.cpu.w32(pp, d.ptr)
        self.emu.logv(f"[display] CreateDIBitmap {w}x{h}x{depth} -> 0x{d.ptr:08x}")
        return SUCCESS

    def Clone(self, c):
        pp = c.arg(1)
        if pp:
            self.cpu.w32(pp, self.ptr)
        return SUCCESS

    def MakeDefault(self, c):
        return SUCCESS
