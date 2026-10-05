"""AEEHelperFuncs: BREW's stdlib table.

Compiled BREW modules are ROPI: they find this table through the "static
base" word stored 4 bytes before the module's load address. Slot order is
the SDK's AEEHelperFuncs struct (117 entries); the layout was taken from the
zeebulator project's notes on AEEStdLib.h (GPL-3.0).
"""

from __future__ import annotations

import random
import struct
import time
from typing import TYPE_CHECKING, Callable

from .cpu import CallCtx

if TYPE_CHECKING:
    from .runtime import Emulator

HELPER_SLOTS = (
    "memmove", "memset", "strcpy", "strcat", "strcmp", "strlen", "strchr", "strrchr",
    "sprintf", "wstrcpy", "wstrcat", "wstrcmp", "wstrlen", "wstrchr", "wstrrchr",
    "wsprintf", "strtowstr", "wstrtostr", "wstrtofloat", "floattowstr", "utf8towstr",
    "wstrtoutf8", "wstrlower", "wstrupper", "chartype", "SetupNativeImage", "malloc",
    "free", "wstrdup", "realloc", "wwritelongex", "wstrsize", "wstrncopyn", "OEMStrLen",
    "OEMStrSize", "GetAEEVersion", "atoi", "f_op", "f_cmp", "dbgprintf", "wstrcompress",
    "aee_LocalTimeOffset", "aee_GetRand", "aee_GetTimeMS", "aee_GetUpTimeMS",
    "aee_GetSeconds", "aee_GetJulianDate", "sysfree", "GetAppInstance", "strtoul",
    "strncpy", "strncmp", "stricmp", "strnicmp", "strstr", "memcmp", "memchr",
    "strexpand", "stristr", "memstr", "wstrncmp", "strdup", "strbegins", "strends",
    "strchrend", "strchrsend", "memrchr", "memchrend", "memrchrbegin", "strlower",
    "strupper", "wstricmp", "wstrnicmp", "inet_aton", "inet_ntoa", "swapl", "swaps",
    "GetFSFree", "GetRAMFree", "vsprintf", "vsnprintf", "snprintf",
    "aee_JulianToSeconds", "strlcpy", "strlcat", "wstrlcpy", "wstrlcat", "setstaticptr",
    "f_assignstr", "f_assignint", "wwritelong", "dbgheapmark", "lockmem", "unlockmem",
    "dumpheap", "strtod", "f_calc", "sleep", "getlasterror", "wgs84_to_degrees",
    "dbgevent", "aee_IsBadPtr", "aee_basename", "aee_makepath", "aee_splitpath",
    "aee_stribegins", "aee_GetUTCSeconds", "f_toint", "f_get", "qsort", "trunc", "utrunc",
    "err_realloc", "err_strdup", "inet_pton", "inet_ntop", "GetALSContext",
)

# Seconds between the Unix epoch and BREW's (GPS) epoch, 1980-01-06.
GPS_EPOCH_OFFSET = 315964800


class ArgIter:
    """Walks C varargs: first from a register list, then from memory."""

    def __init__(self, cpu, regs: list, mem_ptr: int):
        self.cpu, self.regs, self.mem = cpu, list(regs), mem_ptr

    def next32(self) -> int:
        if self.regs:
            return self.regs.pop(0)
        v = self.cpu.r32(self.mem)
        self.mem += 4
        return v

    def next64(self) -> int:
        lo = self.next32()
        hi = self.next32()
        return lo | (hi << 32)


def c_format(fmt: str, args: ArgIter, cpu, wide: bool = False) -> str:
    out = []
    i, n = 0, len(fmt)
    while i < n:
        ch = fmt[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        if fmt[i] == "%":
            out.append("%")
            i += 1
            continue
        flags = ""
        while i < n and fmt[i] in "-+ #0":
            flags += fmt[i]
            i += 1
        width = ""
        if i < n and fmt[i] == "*":
            width = str(args.next32())
            i += 1
        while i < n and fmt[i].isdigit():
            width += fmt[i]
            i += 1
        prec = None
        if i < n and fmt[i] == ".":
            i += 1
            prec = ""
            if i < n and fmt[i] == "*":
                prec = str(args.next32())
                i += 1
            while i < n and fmt[i].isdigit():
                prec += fmt[i]
                i += 1
        while i < n and fmt[i] in "hlLqjzt":
            i += 1
        if i >= n:
            break
        conv = fmt[i]
        i += 1
        spec = "%" + flags + width + (("." + prec) if prec is not None else "")
        if conv in "di":
            v = args.next32()
            v = v - (1 << 32) if v & 0x80000000 else v
            out.append((spec + "d") % v)
        elif conv in "uxXo":
            out.append((spec + conv) % args.next32())
        elif conv == "p":
            out.append("0x%08x" % args.next32())
        elif conv == "c":
            out.append((spec + "c") % chr(args.next32() & 0xFFFF))
        elif conv == "s":
            p = args.next32()
            s = cpu.wstr(p) if wide else cpu.cstr(p)
            out.append((spec + "s") % s)
        elif conv == "S":
            p = args.next32()
            s = cpu.cstr(p) if wide else cpu.wstr(p)
            out.append((spec + "s") % s)
        elif conv in "feEgG":
            raw = args.next64()
            v = struct.unpack("<d", struct.pack("<Q", raw))[0]
            out.append((spec + conv) % v)
        else:
            out.append("%" + conv)
    return "".join(out)


class Helpers:
    def __init__(self, emu: "Emulator"):
        self.emu = emu
        self.cpu = emu.cpu
        self.table = self.cpu.hle_alloc(4 * (len(HELPER_SLOTS) + 16), 16)
        self.start = time.monotonic()
        self.rng = random.Random(1234)
        self.last_error = 0
        for i, name in enumerate(HELPER_SLOTS):
            impl: Callable = getattr(self, "h_" + name, None)
            if impl is None:
                impl = self._make_stub(name)
            self.cpu.w32(self.table + 4 * i, self.cpu.trap("Helper::" + name, impl))
        # GetAppInstance is by far the hottest call (tens of thousands per
        # second in 3D scenes), so it runs as native ARM code instead of a
        # trap: return **cell, where the cell points at the word holding the
        # current applet pointer.
        page = self.cpu.hle_alloc(4096, 4096)       # data page, kept apart from code
        self.app_cell, self._zero_word, self._applet_word = page, page + 4, page + 8
        self.cpu.w32(self.app_cell, self._zero_word)
        code = self.cpu.hle_alloc(32, 32)
        self.cpu.write(code, struct.pack("<5I", 0xE59F0008,   # ldr r0, [pc, #8]  -> cell address
                                         0xE5900000,          # ldr r0, [r0]      -> source word
                                         0xE5900000,          # ldr r0, [r0]      -> applet
                                         0xE12FFF1E,          # bx lr
                                         self.app_cell))
        self.cpu.w32(self.table + 4 * HELPER_SLOTS.index("GetAppInstance"), code)

    def set_app_source(self, word_addr: int):
        """GetAppInstance will return the 32-bit value stored at word_addr."""
        self.cpu.w32(self.app_cell, word_addr or self._zero_word)

    def set_applet(self, applet_ptr: int):
        self.cpu.w32(self._applet_word, applet_ptr)
        self.set_app_source(self._applet_word)

    def _make_stub(self, name):
        def stub(c: CallCtx):
            self.emu.log_once(("helper", name),
                              f"[unimpl] helper {name}({', '.join(hex(a) for a in c.args(4))}) lr=0x{c.lr:08x}")
            return 0
        return stub

    # ----------------------------------------------------------- utilities
    @property
    def heap(self):
        return self.emu.heap

    def _cmp(self, a: bytes, b: bytes) -> int:
        return (a > b) - (a < b)

    # ----------------------------------------------------------- memory
    def h_memmove(self, c):
        d, s, n = c.args(3)
        if n:
            self.cpu.write(d, self.cpu.read(s, n))
        return d

    def h_memset(self, c):
        d, v, n = c.args(3)
        if n:
            self.cpu.write(d, bytes([v & 0xFF]) * n)
        return d

    def h_memcmp(self, c):
        a, b, n = c.args(3)
        return self._cmp(self.cpu.read(a, n), self.cpu.read(b, n)) & 0xFFFFFFFF

    def h_memchr(self, c):
        p, ch, n = c.args(3)
        idx = self.cpu.read(p, n).find(bytes([ch & 0xFF]))
        return p + idx if idx >= 0 else 0

    def h_malloc(self, c):
        return self.heap.malloc(c.arg(0))

    def h_free(self, c):
        self.heap.free(c.arg(0))
        return 0

    h_sysfree = h_free

    def h_realloc(self, c):
        p, n = c.args(2)
        old = self.heap.size_of(p)
        q = self.heap.realloc(p, n)
        if q and n > old and p:
            self.cpu.write(q + old, b"\0" * (self.heap.size_of(q) - old))
        return q

    h_err_realloc = h_realloc

    # ----------------------------------------------------------- strings
    def h_strlen(self, c):
        return len(self.cpu.cstr_bytes(c.arg(0)))

    def h_strcpy(self, c):
        d, s = c.args(2)
        self.cpu.write(d, self.cpu.cstr_bytes(s) + b"\0")
        return d

    def h_strncpy(self, c):
        d, s, n = c.args(3)
        b = self.cpu.cstr_bytes(s)[:n]
        self.cpu.write(d, b + b"\0" * (n - len(b)))
        return d

    def h_strlcpy(self, c):
        d, s, n = c.args(3)
        b = self.cpu.cstr_bytes(s)
        if n:
            self.cpu.write(d, b[: n - 1] + b"\0")
        return len(b)

    def h_strcat(self, c):
        d, s = c.args(2)
        self.cpu.write(d + len(self.cpu.cstr_bytes(d)), self.cpu.cstr_bytes(s) + b"\0")
        return d

    def h_strlcat(self, c):
        d, s, n = c.args(3)
        cur = self.cpu.cstr_bytes(d)
        add = self.cpu.cstr_bytes(s)
        room = n - len(cur) - 1
        if room > 0:
            self.cpu.write(d + len(cur), add[:room] + b"\0")
        return len(cur) + len(add)

    def h_strcmp(self, c):
        return self._cmp(self.cpu.cstr_bytes(c.arg(0)), self.cpu.cstr_bytes(c.arg(1))) & 0xFFFFFFFF

    def h_strncmp(self, c):
        a, b, n = c.args(3)
        return self._cmp(self.cpu.cstr_bytes(a)[:n], self.cpu.cstr_bytes(b)[:n]) & 0xFFFFFFFF

    def h_stricmp(self, c):
        return self._cmp(self.cpu.cstr_bytes(c.arg(0)).lower(), self.cpu.cstr_bytes(c.arg(1)).lower()) & 0xFFFFFFFF

    def h_strnicmp(self, c):
        a, b, n = c.args(3)
        return self._cmp(self.cpu.cstr_bytes(a)[:n].lower(), self.cpu.cstr_bytes(b)[:n].lower()) & 0xFFFFFFFF

    def h_strchr(self, c):
        p, ch = c.args(2)
        b = self.cpu.cstr_bytes(p)
        if ch & 0xFF == 0:
            return p + len(b)
        i = b.find(bytes([ch & 0xFF]))
        return p + i if i >= 0 else 0

    def h_strchrend(self, c):
        # STRCHREND(s, ch): like strchr, but a miss returns the end of the string
        p, ch = c.args(2)
        b = self.cpu.cstr_bytes(p)
        i = b.find(bytes([ch & 0xFF])) if ch & 0xFF else -1
        return p + (i if i >= 0 else len(b))

    def h_strrchr(self, c):
        p, ch = c.args(2)
        b = self.cpu.cstr_bytes(p)
        if ch & 0xFF == 0:
            return p + len(b)
        i = b.rfind(bytes([ch & 0xFF]))
        return p + i if i >= 0 else 0

    def h_strstr(self, c):
        p, q = c.args(2)
        i = self.cpu.cstr_bytes(p).find(self.cpu.cstr_bytes(q))
        return p + i if i >= 0 else 0

    def h_stristr(self, c):
        p, q = c.args(2)
        i = self.cpu.cstr_bytes(p).lower().find(self.cpu.cstr_bytes(q).lower())
        return p + i if i >= 0 else 0

    def h_strdup(self, c):
        b = self.cpu.cstr_bytes(c.arg(0)) + b"\0"
        p = self.heap.malloc(len(b))
        self.cpu.write(p, b)
        return p

    h_err_strdup = h_strdup

    def h_strlower(self, c):
        p = c.arg(0)
        self.cpu.write(p, self.cpu.cstr_bytes(p).lower())
        return p

    def h_strupper(self, c):
        p = c.arg(0)
        self.cpu.write(p, self.cpu.cstr_bytes(p).upper())
        return p

    def h_strbegins(self, c):
        pre, s = c.args(2)
        return int(self.cpu.cstr_bytes(s).startswith(self.cpu.cstr_bytes(pre)))

    def h_aee_stribegins(self, c):
        pre, s = c.args(2)
        return int(self.cpu.cstr_bytes(s).lower().startswith(self.cpu.cstr_bytes(pre).lower()))

    def h_strends(self, c):
        suf, s = c.args(2)
        return int(self.cpu.cstr_bytes(s).endswith(self.cpu.cstr_bytes(suf)))

    def h_atoi(self, c):
        s = self.cpu.cstr(c.arg(0)).strip()
        num = ""
        for i, ch in enumerate(s):
            if ch.isdigit() or (i == 0 and ch in "+-"):
                num += ch
            else:
                break
        try:
            return int(num) & 0xFFFFFFFF
        except ValueError:
            return 0

    def h_strtoul(self, c):
        p, endp, base = c.args(3)
        s = self.cpu.cstr(p)
        st = s.lstrip()
        consumed = len(s) - len(st)
        b = base or 10
        if base in (0, 16) and st[:2].lower() == "0x":
            st, consumed, b = st[2:], consumed + 2, 16
        digits = ""
        for ch in st:
            try:
                int(ch, b)
                digits += ch
            except ValueError:
                break
        if endp:
            self.cpu.w32(endp, p + consumed + len(digits))
        return int(digits, b) & 0xFFFFFFFF if digits else 0

    # ----------------------------------------------------------- wide
    def h_wstrlen(self, c):
        return len(self.cpu.wstr(c.arg(0)))

    def _wwrite(self, p, s: str):
        self.cpu.write(p, s.encode("utf-16-le") + b"\0\0")

    def h_wstrcpy(self, c):
        d, s = c.args(2)
        self._wwrite(d, self.cpu.wstr(s))
        return d

    def h_wstrcat(self, c):
        d, s = c.args(2)
        self._wwrite(d, self.cpu.wstr(d) + self.cpu.wstr(s))
        return d

    def h_wstrcmp(self, c):
        a, b = self.cpu.wstr(c.arg(0)), self.cpu.wstr(c.arg(1))
        return ((a > b) - (a < b)) & 0xFFFFFFFF

    def h_wstrncmp(self, c):
        a, b, n = c.args(3)
        a, b = self.cpu.wstr(a)[:n], self.cpu.wstr(b)[:n]
        return ((a > b) - (a < b)) & 0xFFFFFFFF

    def h_wstrsize(self, c):
        return 2 * (len(self.cpu.wstr(c.arg(0))) + 1)

    def h_strtowstr(self, c):
        s, d, nbytes = c.args(3)
        text = self.cpu.cstr(s)
        maxc = max(0, nbytes // 2 - 1)
        self._wwrite(d, text[:maxc])
        return d

    def h_wstrtostr(self, c):
        s, d, n = c.args(3)
        text = self.cpu.wstr(s).encode("latin-1", "replace")
        if n:
            self.cpu.write(d, text[: n - 1] + b"\0")
        return d

    h_utf8towstr = None

    @staticmethod
    def _dbl(v: float):
        raw = struct.unpack("<Q", struct.pack("<d", v))[0]
        return (raw & 0xFFFFFFFF, raw >> 32)

    def h_wstrtofloat(self, c):
        text = self.cpu.wstr(c.arg(0)).strip()
        num = ""
        for ch in text:
            if ch.isdigit() or ch in "+-.eE":
                num += ch
            else:
                break
        try:
            v = float(num)
        except ValueError:
            v = 0.0
        return self._dbl(v)

    def h_strtod(self, c):
        p, endp = c.args(2)
        s = self.cpu.cstr(p)
        st = s.lstrip()
        num = ""
        for ch in st:
            if ch.isdigit() or ch in "+-.eE":
                num += ch
            else:
                break
        try:
            v = float(num)
        except ValueError:
            v, num = 0.0, ""
        if endp:
            self.cpu.w32(endp, p + (len(s) - len(st)) + len(num))
        return self._dbl(v)

    def h_wstrlcpy(self, c):
        d, s, n = c.args(3)
        text = self.cpu.wstr(s)
        if n:
            self._wwrite(d, text[: n - 1])
        return len(text)

    def h_wstrncopyn(self, c):
        d, dsize, src, n = c.sarg(0) & 0xFFFFFFFF, c.sarg(1), c.arg(2), c.sarg(3)
        text = self.cpu.wstr(src)
        if n >= 0:
            text = text[:n]
        if dsize > 0:
            self._wwrite(d, text[: dsize - 1])
        return d

    def h_wstrchr(self, c):
        p, ch = c.args(2)
        i = self.cpu.wstr(p).find(chr(ch & 0xFFFF))
        return p + 2 * i if i >= 0 else 0

    def h_wstrrchr(self, c):
        p, ch = c.args(2)
        i = self.cpu.wstr(p).rfind(chr(ch & 0xFFFF))
        return p + 2 * i if i >= 0 else 0

    def h_wstrdup(self, c):
        text = self.cpu.wstr(c.arg(0))
        p = self.heap.malloc(2 * len(text) + 2)
        self._wwrite(p, text)
        return p

    def h_wstrlower(self, c):
        p = c.arg(0)
        self._wwrite(p, self.cpu.wstr(p).lower())
        return p

    def h_wstrupper(self, c):
        p = c.arg(0)
        self._wwrite(p, self.cpu.wstr(p).upper())
        return p

    def h_wstricmp(self, c):
        a, b = self.cpu.wstr(c.arg(0)).lower(), self.cpu.wstr(c.arg(1)).lower()
        return ((a > b) - (a < b)) & 0xFFFFFFFF

    def h_wstrnicmp(self, c):
        a, b, n = c.args(3)
        a, b = self.cpu.wstr(a)[:n].lower(), self.cpu.wstr(b)[:n].lower()
        return ((a > b) - (a < b)) & 0xFFFFFFFF

    def h_wstrlcat(self, c):
        d, s, n = c.args(3)
        cur, add = self.cpu.wstr(d), self.cpu.wstr(s)
        if n:
            self._wwrite(d, (cur + add)[: n - 1])
        return len(cur) + len(add)

    def h_wsprintf(self, c):
        d, size, fmt = c.args(3)
        text = c_format(self.cpu.wstr(fmt), ArgIter(self.cpu, [c.arg(3)], c.sp), self.cpu, wide=True)
        maxc = max(0, size // 2 - 1)
        self._wwrite(d, text[:maxc])
        return len(text[:maxc])

    # ----------------------------------------------------------- printf
    def h_sprintf(self, c):
        d, fmt = c.args(2)
        text = c_format(self.cpu.cstr(fmt), ArgIter(self.cpu, [c.arg(2), c.arg(3)], c.sp), self.cpu)
        b = text.encode("latin-1", "replace")
        self.cpu.write(d, b + b"\0")
        return len(b)

    def h_snprintf(self, c):
        d, n, fmt = c.args(3)
        text = c_format(self.cpu.cstr(fmt), ArgIter(self.cpu, [c.arg(3)], c.sp), self.cpu)
        b = text.encode("latin-1", "replace")
        if n:
            self.cpu.write(d, b[: n - 1] + b"\0")
        return len(b)

    def h_vsprintf(self, c):
        d, fmt, va = c.args(3)
        text = c_format(self.cpu.cstr(fmt), ArgIter(self.cpu, [], va), self.cpu)
        b = text.encode("latin-1", "replace")
        self.cpu.write(d, b + b"\0")
        return len(b)

    def h_vsnprintf(self, c):
        d, n, fmt, va = c.args(4)
        text = c_format(self.cpu.cstr(fmt), ArgIter(self.cpu, [], va), self.cpu)
        b = text.encode("latin-1", "replace")
        if n:
            self.cpu.write(d, b[: n - 1] + b"\0")
        return len(b)

    def h_dbgprintf(self, c):
        text = c_format(self.cpu.cstr(c.arg(0)), ArgIter(self.cpu, c.args(4)[1:], c.sp), self.cpu)
        self.emu.log(f"[guest] {text.rstrip()}")
        return 0

    # ----------------------------------------------------------- time / misc
    def _uptime_ms(self) -> int:
        return int((time.monotonic() - self.start) * 1000)

    def h_aee_GetUpTimeMS(self, c):
        return self.emu.clock_ms() & 0xFFFFFFFF

    def h_aee_GetTimeMS(self, c):
        lt = time.localtime()
        return ((lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) * 1000 +
                int(time.time() * 1000) % 1000)

    def h_aee_GetSeconds(self, c):
        return (int(time.time()) - GPS_EPOCH_OFFSET + time.localtime().tm_gmtoff) & 0xFFFFFFFF

    def h_aee_GetUTCSeconds(self, c):
        return (int(time.time()) - GPS_EPOCH_OFFSET) & 0xFFFFFFFF

    def h_aee_LocalTimeOffset(self, c):
        return time.localtime().tm_gmtoff & 0xFFFFFFFF

    def h_aee_GetRand(self, c):
        p, n = c.args(2)
        if p and n:
            self.cpu.write(p, bytes(self.rng.getrandbits(8) for _ in range(n)))
        return 0

    def h_GetAppInstance(self, c):
        return self.emu.current_applet_ptr()

    def h_GetAEEVersion(self, c):
        p, n = c.args(2)
        ver = "2.1.3.8"
        if p and n:
            self.cpu.write(p, ver.encode()[: n - 1] + b"\0")
        return 0x02010308

    def h_GetRAMFree(self, c):
        p = c.arg(0)
        if p:
            self.cpu.w32(p, self.heap.size)
        return self.heap.free_bytes()

    def h_GetFSFree(self, c):
        p = c.arg(0)
        if p:
            self.cpu.w32(p, 32 << 20)
        return 16 << 20

    def h_swapl(self, c):
        return struct.unpack(">I", struct.pack("<I", c.arg(0)))[0]

    def h_swaps(self, c):
        v = c.arg(0) & 0xFFFF
        return ((v >> 8) | (v << 8)) & 0xFFFF

    def h_getlasterror(self, c):
        return self.last_error

    def h_setstaticptr(self, c):
        return 0

    def h_lockmem(self, c):
        return c.arg(0)

    def h_unlockmem(self, c):
        return 0

    def h_aee_IsBadPtr(self, c):
        return 0

    def h_qsort(self, c):
        base, num, size, cmp = c.args(4)
        items = [self.cpu.read(base + i * size, size) for i in range(num)]
        # Use the guest comparator via temporary buffers.
        a = self.heap.malloc(size)
        b = self.heap.malloc(size)
        import functools

        def guest_cmp(x, y):
            self.cpu.write(a, x)
            self.cpu.write(b, y)
            r = self.cpu.call(cmp, a, b)
            return r - (1 << 32) if r & 0x80000000 else r

        items.sort(key=functools.cmp_to_key(guest_cmp))
        self.heap.free(a)
        self.heap.free(b)
        self.cpu.write(base, b"".join(items))
        return 0

    def h_chartype(self, c):
        return 0
