"""IShell: applet lifecycle, class factory, timers, events, resources."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .cpu import CallCtx
from .hle import (ECLASSNOTSUPPORT, EFAILED, EUNSUPPORTED, SUCCESS, HleObject)
from .resfile import ResourceFile, decode_string, strip_mime

if TYPE_CHECKING:
    from .runtime import Emulator

# Well-known class IDs (values as used by zeebulator, from the BREW SDK).
AEECLSID_DISPLAY = 0x01001001
AEECLSID_HEAP = 0x01001002
AEECLSID_FILEMGR = 0x01001003
AEECLSID_MEMASTREAM = 0x0100100C
AEECLSID_LICENSE = 0x0100100F
AEECLSID_BITMAP = 0x01001021
AEECLSID_DIB20 = 0x0100102C
AEECLSID_DIB = 0x01001045
AEECLSID_SOUND = 0x01001056
AEECLSID_GRAPHICS = 0x01002001
AEECLSID_WINBMP = 0x01004001
AEECLSID_GIF = 0x01004003
AEECLSID_PNG = 0x01004004
AEECLSID_JPEG = 0x01004005
AEECLSID_WEB = 0x01005000
AEECLSID_MEDIA = 0x01005500
AEECLSID_MEDIAMIDI = 0x01005501
AEECLSID_MEDIAMP3 = 0x01005502
AEECLSID_MEDIAQCP = 0x01005503
AEECLSID_MEDIAPMD = 0x01005504
AEECLSID_MEDIAADPCM = 0x0100550A
AEECLSID_MEDIAPCM = 0x01005511

CLASS_NAMES = {v: k for k, v in globals().items() if k.startswith("AEECLSID_")}

EVT_APP_START = 0x0
EVT_APP_STOP = 0x1
EVT_APP_SUSPEND = 0x2
EVT_APP_RESUME = 0x3
EVT_KEY = 0x100
EVT_KEY_PRESS = 0x101
EVT_KEY_RELEASE = 0x102

EVTFLG_ASYNC = 0x1

# Media MIME -> handler class (ISHELL_GetHandler(AEECLSID_MEDIA, mime)).
MIME_HANDLERS = {
    "audio/mid": AEECLSID_MEDIAMIDI, "audio/midi": AEECLSID_MEDIAMIDI,
    "audio/mp3": AEECLSID_MEDIAMP3, "audio/mpeg": AEECLSID_MEDIAMP3,
    "audio/qcp": AEECLSID_MEDIAQCP, "audio/qcelp": AEECLSID_MEDIAQCP,
    "audio/pmd": AEECLSID_MEDIAPMD, "audio/cmx": AEECLSID_MEDIAPMD,
    "audio/wav": AEECLSID_MEDIAPCM, "audio/x-wav": AEECLSID_MEDIAPCM,
}
EXT_MIME = {"mid": "audio/mid", "midi": "audio/mid", "mp3": "audio/mp3", "qcp": "audio/qcp",
            "pmd": "audio/pmd", "wav": "audio/wav"}


def clsname(cls: int) -> str:
    return CLASS_NAMES.get(cls, f"0x{cls:08x}")


class Shell(HleObject):
    IFACE = "IShell"
    SLOTS = (
        "AddRef", "Release", "CreateInstance", "QueryClass", "GetDeviceInfo", "StartApplet",
        "CloseApplet", "CanStartApplet", "ActiveApplet", "EnumAppletInit", "EnumNextApplet",
        "SetTimer", "CancelTimer", "GetTimerExpiration", "CreateDialog", "GetActiveDialog",
        "EndDialog", "LoadResString", "LoadResData", "LoadResObject", "FreeResData",
        "SendEvent", "Beep", "GetPrefs", "SetPrefs", "GetItemStyle", "Prompt", "MessageBox",
        "MessageBoxText", "SetAlarm", "CancelAlarm", "AlarmsActive", "GetHandler",
        "RegisterHandler", "RegisterNotify", "Notify", "Resume", "ForceExit", "GetPosition",
        "CheckPrivLevel", "IsValidResource", "LoadResDataEx", "RegisterSystemCallback",
        "DetectType", "GetDeviceInfoEx", "GetClassItemID", "Obsolete", "GetProperty",
        "SetProperty", "RegisterEvent", "Reset", "AppIsInGroup",
    )

    def __init__(self, emu: "Emulator"):
        super().__init__(emu)
        self.res_cache: dict[str, ResourceFile] = {}
        self.res_blocks: set[int] = set()
        self._enum_idx = 0

    def AddRef(self, c):
        return 1

    def Release(self, c):
        return 1

    # ------------------------------------------------------------ classes
    def CreateInstance(self, c: CallCtx):
        cls, pp = c.arg(1), c.arg(2)
        obj = self.emu.create_instance(cls)
        if pp:
            self.cpu.w32(pp, obj or 0)
        if not obj:
            self.emu.log_once(("cls", cls), f"[shell] CreateInstance({clsname(cls)}) -> ECLASSNOTSUPPORT (lr=0x{c.lr:08x})")
            return ECLASSNOTSUPPORT
        self.emu.logv(f"[shell] CreateInstance({clsname(cls)}) -> 0x{obj:08x}")
        return SUCCESS

    def QueryClass(self, c):
        cls, pai = c.arg(1), c.arg(2)
        known = self.emu.class_available(cls)
        if known and pai:
            self.cpu.w32(pai, cls)
        return int(known)

    def CanStartApplet(self, c):
        return int(c.arg(1) in self.emu.applets)

    def ActiveApplet(self, c):
        return self.emu.applet_cls

    def StartApplet(self, c):
        cls = c.arg(1)
        self.emu.log(f"[shell] StartApplet({clsname(cls)})")
        if cls == self.emu.applet_cls:
            return SUCCESS
        return EFAILED

    def CloseApplet(self, c):
        self.emu.log("[shell] CloseApplet -> game asked to exit")
        self.emu.request_exit()
        return SUCCESS

    def EnumAppletInit(self, c):
        self._enum_idx = 0
        return SUCCESS

    def EnumNextApplet(self, c):
        return 0

    def GetDeviceInfo(self, c):
        p = c.arg(1)
        if not p:
            return None
        requested = self.cpu.r16(p + 44)
        self.cpu.write(p, b"\0" * 44)
        w, h = self.emu.screen
        self.cpu.w16(p + 0, w)
        self.cpu.w16(p + 2, h)
        self.cpu.w16(p + 8, 8)          # cxScrollBar
        self.cpu.w16(p + 10, 3)         # wEncoding: ISOLATIN1
        self.cpu.w16(p + 14, 16)        # wColorDepth
        self.cpu.w32(p + 24, 2 << 20)   # dwRAM
        self.cpu.w32(p + 36, 0x656E0000)  # dwLang 'en' (best effort)
        if requested >= 64:
            self.cpu.w16(p + 44, 64)
            self.cpu.w16(p + 56, 64)
        return None

    def GetDeviceInfoEx(self, c):
        return EUNSUPPORTED

    def CheckPrivLevel(self, c):
        return 1

    def GetClassItemID(self, c):
        return 0

    # ------------------------------------------------------------ timers
    def SetTimer(self, c):
        ms, fn, user = c.sarg(1), c.arg(2), c.arg(3)
        self.emu.set_timer(max(0, ms), fn, user)
        return SUCCESS

    def CancelTimer(self, c):
        self.emu.cancel_timer(c.arg(1), c.arg(2))
        return SUCCESS

    def GetTimerExpiration(self, c):
        return self.emu.timer_remaining(c.arg(1), c.arg(2))

    def Resume(self, c):
        self.emu.resume_callback(c.arg(1))
        return SUCCESS

    # ------------------------------------------------------------ events
    def SendEvent(self, c):
        flags, cls, evt, wp, dwp = c.arg(1), c.arg(2), c.arg(3), c.arg(4) & 0xFFFF, c.arg(5)
        if cls not in (0, self.emu.applet_cls):
            return 0
        if flags & EVTFLG_ASYNC:
            self.emu.post_event(evt, wp, dwp)
            return 1
        return int(bool(self.emu.send_event(evt, wp, dwp)))

    def Beep(self, c):
        return SUCCESS

    def Notify(self, c):
        return SUCCESS

    def RegisterNotify(self, c):
        return SUCCESS

    # ------------------------------------------------------------ prefs
    def _prefs_path(self, cls):
        return os.path.join(self.emu.data_dir, f"prefs_{cls:08x}.bin")

    def GetPrefs(self, c):
        cls, _ver, p, n = c.arg(1), c.arg(2), c.arg(3), c.arg(4) & 0xFFFF
        path = self._prefs_path(cls)
        if not os.path.exists(path):
            return EFAILED
        data = open(path, "rb").read()[:n]
        self.cpu.write(p, data)
        return SUCCESS

    def SetPrefs(self, c):
        cls, _ver, p, n = c.arg(1), c.arg(2), c.arg(3), c.arg(4) & 0xFFFF
        with open(self._prefs_path(cls), "wb") as f:
            f.write(self.cpu.read(p, n))
        return SUCCESS

    # ------------------------------------------------------------ resources
    def _res(self, name_ptr):
        name = self.cpu.cstr(name_ptr)
        rf = self.res_cache.get(name.lower())
        if rf is None:
            data = self.emu.vfs.read_file(name)
            if data is None:
                self.emu.log_once(("res", name), f"[shell] resource file '{name}' not found")
                return name, None
            try:
                rf = ResourceFile.parse(data)
            except ValueError:
                return name, None
            self.res_cache[name.lower()] = rf
        return name, rf

    def LoadResString(self, c):
        name, rf = self._res(c.arg(1))
        rid, buf, size = c.arg(2) & 0xFFFF, c.arg(3), c.sarg(4)
        if rf is None:
            return 0
        payload = rf.find(1, rid)
        if payload is None:
            return 0
        text = decode_string(payload)
        if buf and size > 0:
            maxc = size // 2 - 1
            enc = text[:maxc].encode("utf-16-le") + b"\0\0"
            self.cpu.write(buf, enc)
            return len(enc) - 2
        return 2 * (len(text) + 1)

    def _alloc_block(self, data: bytes) -> int:
        p = self.emu.heap.malloc(len(data) + 1)
        self.cpu.write(p, data)
        self.res_blocks.add(p)
        return p

    def LoadResData(self, c):
        name, rf = self._res(c.arg(1))
        rid, rtype = c.arg(2) & 0xFFFF, c.arg(3) & 0xFFFF
        if rf is None:
            return 0
        payload = rf.find(rtype, rid)
        if payload is None:
            self.emu.log_once(("resd", name, rid), f"[shell] LoadResData({name}, {rid}, type {rtype}) missing")
            return 0
        return self._alloc_block(payload)

    def LoadResDataEx(self, c):
        name, rf = self._res(c.arg(1))
        rid, rtype, pbuf, pnsize = c.arg(2) & 0xFFFF, c.arg(3) & 0xFFFF, c.arg(4), c.arg(5)
        if rf is None:
            return 0
        payload = rf.find(rtype, rid)
        if payload is None:
            return 0
        if pbuf == 0xFFFFFFFF:          # size query
            if pnsize:
                self.cpu.w32(pnsize, len(payload))
            return 0xFFFFFFFF
        if pbuf:
            cap = self.cpu.r32(pnsize) if pnsize else len(payload)
            self.cpu.write(pbuf, payload[:cap])
            if pnsize:
                self.cpu.w32(pnsize, min(cap, len(payload)))
            return pbuf
        return self._alloc_block(payload)

    def FreeResData(self, c):
        p = c.arg(1)
        if p in self.res_blocks:
            self.res_blocks.discard(p)
            self.emu.heap.free(p)
        return None

    def LoadResObject(self, c):
        rid, cls = c.arg(2) & 0xFFFF, c.arg(3)
        if rid == 0:
            # ISHELL_LoadImage(pIShell, "file.png"): the whole file is the image
            fname = self.cpu.cstr(c.arg(1))
            data = self.emu.vfs.read_file(fname)
            if data is None:
                self.emu.log_once(("img", fname), f"[shell] image '{fname}' not found")
                return 0
            img = self.emu.make_image(data)
            self.emu.logv(f"[shell] LoadImage('{fname}') -> {img.ptr if img else 0:#x}")
            if fname.lower().endswith("ro_wonderland_splash.png"):
                self.emu.wonderland_splash_up = True     # frontend adds the lost-media screens
            return img.ptr if img else 0
        name, rf = self._res(c.arg(1))
        if rf is None:
            return 0
        payload = rf.find(6, rid) or rf.find_any_type(rid)
        if payload is None:
            return 0
        if isinstance(payload, tuple):
            payload = payload[1]
        mime, raw = strip_mime(payload)
        img = self.emu.make_image(raw)
        return img.ptr if img else 0

    def IsValidResource(self, c):
        name, rf = self._res(c.arg(1))
        return int(rf is not None)

    # ------------------------------------------------------------ media
    def GetHandler(self, c):
        base, mime_p = c.arg(1), c.arg(2)
        mime = self.cpu.cstr(mime_p).lower()
        h = MIME_HANDLERS.get(mime, 0)
        self.emu.logv(f"[shell] GetHandler({clsname(base)}, '{mime}') -> {clsname(h) if h else 0}")
        return h

    def DetectType(self, c):
        pbuf, psize, pname, pmime = c.args(4)
        name = self.cpu.cstr(pname) if pname else ""
        head = self.cpu.read(pbuf, 16) if pbuf else b""
        mime = None
        if head.startswith(b"MThd"):
            mime = "audio/mid"
        elif head.startswith(b"cmid"):
            mime = "audio/pmd"
        elif head.startswith(b"RIFF"):
            mime = "audio/wav"
        elif head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3"):
            mime = "audio/mp3"
        elif head.startswith(b"\x89PNG"):
            mime = "image/png"
        elif head.startswith(b"BM"):
            mime = "image/bmp"
        elif "." in name:
            mime = EXT_MIME.get(name.rsplit(".", 1)[1].lower())
        if not mime:
            return EUNSUPPORTED
        if pmime:
            self.cpu.w32(pmime, self.emu.static_cstr(mime))
        return SUCCESS
