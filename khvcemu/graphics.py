"""IGraphics: 2D primitives (KH uses it for UI panels: polygons/polylines).

Slot order reconstructed from the game's own call sites: slot 2 takes
(r,g,b) [SetBackground], 4 and 8 take (r,g,b,alpha) [SetColor/SetFillColor],
6 takes a boolean [SetFillMode], 28/29 take {len, AEEPoint*}
[DrawPolygon/DrawPolyline]. The Set/Get pairing in between is inferred.
"""

from __future__ import annotations

import struct

import numpy as np

from .hle import SUCCESS, HleObject


def _565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


class Graphics(HleObject):
    IFACE = "IGraphics"
    SLOTS = ("AddRef", "Release", "SetBackground", "GetBackground", "SetColor", "GetColor",
             "SetFillMode", "GetFillMode", "SetFillColor", "GetFillColor", "SetPointSize",
             "GetPointSize", "SetStrokeStyle", "GetStrokeStyle", "SetPaintMode", "GetPaintMode",
             "SetViewport", "GetViewport", "ClearViewport", "ClearRect", "DrawPoint", "DrawLine",
             "DrawRect", "DrawCircle", "DrawArc", "DrawPie", "DrawEllipse", "DrawTriangle",
             "DrawPolygon", "DrawPolyline", "ClearRectBg", "slot31", "Flush", "slot33", "slot34",
             "slot35", "slot36", "slot37", "slot38", "slot39", "slot40", "slot41", "slot42",
             "DrawRoundRect") + tuple(f"slot{i}" for i in range(44, 56))

    def __init__(self, emu):
        super().__init__(emu)
        self.bg = (255, 255, 255)
        self.color = (0, 0, 0, 255)
        self.fill_color = (0, 0, 0, 255)
        self.fill = False
        self.point_size = 1
        self.viewport = None   # (x, y, w, h)

    def _rgbval(self, rgb):
        r, g, b = rgb[:3]
        return (r << 8) | (g << 16) | (b << 24)

    def SetBackground(self, c):
        prev = self._rgbval(self.bg)
        self.bg = (c.arg(1) & 0xFF, c.arg(2) & 0xFF, c.arg(3) & 0xFF)
        return prev

    def SetColor(self, c):
        prev = self._rgbval(self.color)
        self.color = (c.arg(1) & 0xFF, c.arg(2) & 0xFF, c.arg(3) & 0xFF, c.arg(4) & 0xFF)
        return prev

    def SetFillColor(self, c):
        prev = self._rgbval(self.fill_color)
        self.fill_color = (c.arg(1) & 0xFF, c.arg(2) & 0xFF, c.arg(3) & 0xFF, c.arg(4) & 0xFF)
        return prev

    def SetFillMode(self, c):
        prev = self.fill
        self.fill = bool(c.arg(1) & 0xFF)
        return int(prev)

    def GetFillMode(self, c):
        return int(self.fill)

    def SetPointSize(self, c):
        prev = self.point_size
        self.point_size = max(1, c.arg(1) & 0xFF)
        return prev

    def SetStrokeStyle(self, c):
        return 0

    def SetPaintMode(self, c):
        return 0

    def SetViewport(self, c):
        p = c.arg(1)
        self.viewport = struct.unpack("<hhhh", self.cpu.read(p, 8)) if p else None
        return 1

    def GetViewport(self, c):
        p = c.arg(1)
        if p:
            d = self.emu.display.dest
            self.cpu.write(p, struct.pack("<hhhh", *(self.viewport or (0, 0, d.w, d.h))))
        return None

    # ------------------------------------------------------------ raster
    def _target(self):
        return self.emu.display.dest

    def _origin(self):
        return (self.viewport[0], self.viewport[1]) if self.viewport else (0, 0)

    def _plot_spans(self, spans, rgba):
        """spans: list of (y, x0, x1) inclusive, in viewport coords."""
        dst = self._target()
        arr = dst.pixels()
        ox, oy = self._origin()
        col = _565(*rgba[:3])
        alpha = rgba[3] if len(rgba) > 3 else 255
        clipx0, clipy0, clipx1, clipy1 = 0, 0, dst.w, dst.h
        clip = self.emu.display.clip
        if clip:
            clipx0, clipy0 = max(0, clip[0]), max(0, clip[1])
            clipx1, clipy1 = min(dst.w, clip[0] + clip[2]), min(dst.h, clip[1] + clip[3])
        if self.viewport:
            vx, vy, vw, vh = self.viewport
            clipx0, clipy0 = max(clipx0, vx), max(clipy0, vy)
            clipx1, clipy1 = min(clipx1, vx + vw), min(clipy1, vy + vh)
        touched = False
        for y, x0, x1 in spans:
            y += oy
            if not (clipy0 <= y < clipy1):
                continue
            a, b = max(clipx0, x0 + ox), min(clipx1 - 1, x1 + ox)
            if a > b:
                continue
            if alpha >= 250:
                arr[y, a:b + 1] = col
            else:
                arr[y, a:b + 1] = _blend(arr[y, a:b + 1], rgba[:3], alpha)
            touched = True
        if touched:
            dst.store(arr)

    def _line_spans(self, pts, closed):
        spans = []
        n = len(pts)
        segs = n if closed else n - 1
        for i in range(max(0, segs)):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            for x, y in _bresenham(x0, y0, x1, y1):
                spans.append((y, x, x + self.point_size - 1))
        if n == 1:
            spans.append((pts[0][1], pts[0][0], pts[0][0]))
        return spans

    def _poly_fill_spans(self, pts):
        if len(pts) < 3:
            return []
        ys = [p[1] for p in pts]
        spans = []
        n = len(pts)
        for y in range(min(ys), max(ys) + 1):
            xs = []
            for i in range(n):
                (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
                if y0 == y1:
                    continue
                if min(y0, y1) <= y < max(y0, y1):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                spans.append((y, int(round(xs[k])), int(round(xs[k + 1])) - 1))
        return spans

    def _points(self, n, p):
        return [struct.unpack("<hh", self.cpu.read(p + 4 * i, 4)) for i in range(n)]

    def _shape(self, pts, closed=True):
        if self.fill and closed:
            self._plot_spans(self._poly_fill_spans(pts), self.fill_color)
        self._plot_spans(self._line_spans(pts, closed), self.color)

    def DrawPolygon(self, c):
        n, p = struct.unpack("<hxxI", self.cpu.read(c.arg(1), 8))
        self._shape(self._points(n, p), True)
        return SUCCESS

    def DrawPolyline(self, c):
        n, p = struct.unpack("<hxxI", self.cpu.read(c.arg(1), 8))
        self._plot_spans(self._line_spans(self._points(n, p), False), self.color)
        return SUCCESS

    def DrawTriangle(self, c):
        pts = [struct.unpack("<hh", self.cpu.read(c.arg(1) + 4 * i, 4)) for i in range(3)]
        self._shape(pts, True)
        return SUCCESS

    def DrawRect(self, c):
        x, y, w, h = struct.unpack("<hhhh", self.cpu.read(c.arg(1), 8))
        self._shape([(x, y), (x + w - 1, y), (x + w - 1, y + h - 1), (x, y + h - 1)], True)
        return SUCCESS

    def DrawLine(self, c):
        x0, y0, x1, y1 = struct.unpack("<hhhh", self.cpu.read(c.arg(1), 8))
        self._plot_spans(self._line_spans([(x0, y0), (x1, y1)], False), self.color)
        return SUCCESS

    def DrawPoint(self, c):
        x, y = struct.unpack("<hh", self.cpu.read(c.arg(1), 4))
        self._plot_spans([(y, x, x + self.point_size - 1)], self.color)
        return SUCCESS

    def DrawRoundRect(self, c):
        """Slot 43: (AEERect*, arc width, arc height) - KH's dialog boxes."""
        x, y, w, h = struct.unpack("<hhhh", self.cpu.read(c.arg(1), 8))
        rx, ry = max(0, c.sarg(2)) // 2, max(0, c.sarg(3)) // 2
        rx, ry = min(rx, w // 2), min(ry, h // 2)
        pts = []
        corners = ((x + w - 1 - rx, y + ry, -np.pi / 2, 0), (x + w - 1 - rx, y + h - 1 - ry, 0, np.pi / 2),
                   (x + rx, y + h - 1 - ry, np.pi / 2, np.pi), (x + rx, y + ry, np.pi, 1.5 * np.pi))
        for cx, cy, a0, a1 in corners:
            for t in np.linspace(a0, a1, 6):
                pts.append((int(round(cx + rx * np.cos(t))), int(round(cy + ry * np.sin(t)))))
        self._shape(pts, True)
        return SUCCESS

    def DrawCircle(self, c):
        cx, cy, r = struct.unpack("<hhh", self.cpu.read(c.arg(1), 6))
        self._ellipse(cx, cy, r, r)
        return SUCCESS

    def DrawArc(self, c):
        """Slot 24: AEEArc* = {cx, cy, radius, start deg, sweep deg, ...} (int16).
        Inferred from the HUD calls: the magic ring is five 45-degree wedges at
        r=19 and the health gauge a 270-degree wedge at r=13. Angles run
        counter-clockwise from 3 o'clock (negative sweep = clockwise). Drawn as a
        pie wedge: filled with the fill color when fill mode is on, then outlined."""
        cx, cy, r, start, sweep = struct.unpack("<5h", self.cpu.read(c.arg(1), 10))
        if r <= 0 or sweep == 0:
            return SUCCESS
        steps = max(2, int(abs(sweep) / 360 * 2 * np.pi * r / 2) + 1)
        pts = [(cx, cy)]
        for t in np.linspace(np.radians(start), np.radians(start + sweep), steps):
            pts.append((int(round(cx + r * np.cos(t))), int(round(cy - r * np.sin(t)))))
        self._shape(pts, True)
        return SUCCESS

    def DrawEllipse(self, c):
        cx, cy, wx, wy = struct.unpack("<hhhh", self.cpu.read(c.arg(1), 8))
        self._ellipse(cx, cy, wx, wy)
        return SUCCESS

    def _ellipse(self, cx, cy, rx, ry):
        steps = max(12, int(2 * np.pi * max(rx, ry)))
        pts = [(int(round(cx + rx * np.cos(t))), int(round(cy + ry * np.sin(t))))
               for t in np.linspace(0, 2 * np.pi, steps, endpoint=False)]
        self._shape(pts, True)

    def ClearViewport(self, c):
        d = self._target()
        vx, vy, vw, vh = self.viewport or (0, 0, d.w, d.h)
        self._plot_spans([(y - self._origin()[1], vx - self._origin()[0],
                           vx + vw - 1 - self._origin()[0]) for y in range(vy, vy + vh)],
                         self.bg + (255,))
        return SUCCESS

    def Flush(self, c):
        """Slot 32: called with no arguments after UI drawing (likely Update)."""
        return SUCCESS

    def ClearRectBg(self, c):
        """Slot 30: KH calls SetBackground(0,0,0) then this with an AEERect* to
        blank the letterbox around the 3D viewport."""
        return self.ClearRect(c)

    def ClearRect(self, c):
        x, y, w, h = struct.unpack("<hhhh", self.cpu.read(c.arg(1), 8))
        self._plot_spans([(yy, x, x + w - 1) for yy in range(y, y + h)], self.bg + (255,))
        return SUCCESS


def _bresenham(x0, y0, x1, y1):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _blend(dst565, rgb, alpha):
    d = dst565.astype(np.uint32)
    r = ((d >> 11) & 31) * 255 // 31
    g = ((d >> 5) & 63) * 255 // 63
    b = (d & 31) * 255 // 31
    a = alpha / 255.0
    r = (r * (1 - a) + rgb[0] * a).astype(np.uint32)
    g = (g * (1 - a) + rgb[1] * a).astype(np.uint32)
    b = (b * (1 - a) + rgb[2] * a).astype(np.uint32)
    return (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).astype(np.uint16)
