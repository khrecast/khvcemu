"""The emulator: loads the game + extension modules and runs the BREW shell loop."""

from __future__ import annotations

import glob
import heapq
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .cpu import (EXT_MODULE_BASE, EXT_MODULE_STRIDE, MAIN_MODULE_BASE, Cpu,
                  GuestFault)
from .display import Display
from .files import FileMgr, Vfs
from .heap import Heap
from .helpers import Helpers
from .hle import HleObject, ProbeObject
from .resfile import mif_applet_classes, mif_extension_classes, mif_strings
from .shell import (AEECLSID_DISPLAY, AEECLSID_FILEMGR, EVT_APP_START,
                    EVT_APP_STOP, EVT_KEY, EVT_KEY_PRESS, EVT_KEY_RELEASE,
                    Shell, clsname)


@dataclass
class ModuleInfo:
    mif: str
    mod_path: str
    mod_dir: str
    classes: list
    is_applet: bool
    title: str = ""


@dataclass(order=True)
class Timer:
    due: float
    seq: int
    fn: int = field(compare=False)
    user: int = field(compare=False)
    cancelled: bool = field(default=False, compare=False)
    args: tuple = field(default=(), compare=False)


class Emulator:
    def __init__(self, game_root: str, data_dir: str, screen=(176, 220), verbose=False,
                 log: Callable[[str], None] = None, realtime=True, audio=True,
                 soundfont: Optional[str] = None, skip_wonderland: bool = True,
                 music: Optional[dict] = None, music_files: Optional[dict] = None,
                 wonderland_volume: float = 1.0, speed_patches=None):
        self.game_root = os.path.abspath(game_root)
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.screen = screen
        self.verbose = verbose
        self._log = log or (lambda s: print(s, file=sys.stderr, flush=True))
        self._once: set = set()
        self.realtime = realtime
        self.skip_wonderland = skip_wonderland
        self.vfs_hooks: list = []      # callables(vfs) run when the VFS is created
        self.recent_files: dict = {}   # size -> name of files the game opened
        self._virtual_ms = 0.0
        self._t0 = time.monotonic()

        self.cpu = Cpu(log=self.log)
        self.cpu.keep_recent_args = verbose
        self.cpu.on_trap_error = self._trap_error
        self.heap = Heap(self.cpu)
        self.objects: dict[int, HleObject] = {}
        self._vtables: dict[type, int] = {}
        # trap address -> (class, slot index, slot name) for vtable traps, so a
        # save state can rebuild each trap's dispatcher (see savestate.py)
        self._trap_meta: dict[int, tuple] = {}
        self.keys_held: set = set()    # keys the game has been told are down
        # lost-Wonderland screens (see chapters.py): True while the Wonderland
        # splash waits for Continue
        self.wonderland_splash_up = False
        self.last_loading_ms = None        # game clock when "Loading..." was last drawn (area autosave)
        self._cstr_cache: dict[str, int] = {}
        self.factories: dict[int, Callable[[], Optional[HleObject]]] = {}
        self.extensions: dict[int, ModuleInfo] = {}
        self.applets: dict[int, ModuleInfo] = {}
        self._loaded_ext: dict[str, int] = {}   # mod path -> IModule*
        from . import swerve_patch                # speed patches for the 3D engine (same pictures); None = all
        self.speed_patches = set(swerve_patch.NAMES if speed_patches is None else speed_patches)
        self._swerve_base = 0
        self._next_ext_base = EXT_MODULE_BASE

        self.timers: list[Timer] = []
        self.leaderboard = None        # opened on the first score request (see web_request)
        self.leaderboard_url = ""      # a shared leaderboard to share scores with, if any
        self._timer_seq = 0
        self.pending_events: list = []
        self.exit_requested = False
        self.frame_listeners: list = []
        from .playtime import PlayTimer
        self.playtime = PlayTimer(self, os.path.join(self.data_dir, "playtime.json"))
        self.frame_listeners.append(self.playtime.tick)
        self.last_frame = None
        self.frames = 0
        self.faults = 0

        self.applet_cls = 0
        self.applet_ptr = 0
        self.handle_event = 0
        self.module_ptr = 0

        self._scan_modules()
        self.helpers = Helpers(self)
        self.shell = Shell(self)
        self.display = Display(self, *screen)
        self.vfs: Optional[Vfs] = None
        self.hooks = []      # objects with optional on_file_opened/on_missing_file
        from .audio import AudioEngine
        self.audio = AudioEngine(self, enabled=audio, soundfont=soundfont, music=music, music_files=music_files,
                                  wonderland_volume=wonderland_volume)
        if audio:                          # render the tunes now, not at the moment the game first asks for each
            self.audio.start_prewarm(self.game_root)
        self._register_builtin_classes()

    # ---------------------------------------------------------------- logging
    def log(self, msg: str):
        self._log(msg)

    def logv(self, msg: str):
        if self.verbose:
            self._log(msg)

    def log_once(self, key, msg: str):
        if key not in self._once:
            self._once.add(key)
            self._log(msg)

    def _trap_error(self, name, exc):
        import traceback
        self.log(f"[hle] Python error in {name}: {exc!r}")
        traceback.print_exc()

    # ---------------------------------------------------------------- time
    def clock_ms(self) -> int:
        if self.realtime:
            return int((time.monotonic() - self._t0) * 1000)
        return int(self._virtual_ms)

    def advance(self, ms: float):
        """Headless mode: move the virtual clock forward."""
        self._virtual_ms += ms

    # ---------------------------------------------------------------- vtables
    def vtable_for(self, cls: type) -> int:
        vt = self._vtables.get(cls)
        if vt is not None:
            return vt
        # Pad every vtable with logging slots so a call past the known methods
        # is reported by index instead of jumping through a garbage pointer.
        slots = tuple(cls.SLOTS) + tuple(f"slot{i}" for i in range(len(cls.SLOTS), len(cls.SLOTS) + 24))
        vt = self.cpu.hle_alloc(4 * len(slots), 8)
        for i, name in enumerate(slots):
            addr = self.cpu.trap(f"{cls.IFACE}::{name}", self._make_dispatch(cls, i, name))
            self._trap_meta[addr] = (cls, i, name)
            self.cpu.w32(vt + 4 * i, addr)
        self._vtables[cls] = vt
        return vt

    def _make_dispatch(self, cls, idx, name):
        def dispatch(c):
            obj = self.objects.get(c.arg(0))
            meth = getattr(obj, name, None) if obj is not None else None
            if meth is None:
                iface = getattr(obj, "IFACE", cls.IFACE)
                self.log_once((iface, idx), f"[unimpl] {iface}::{name} (slot {idx}) args="
                              f"{[hex(a) for a in c.args(6)]} lr=0x{c.lr:08x}")
                return getattr(obj, "STUB_RETURN", 0) if obj is not None else 1
            return meth(c)
        return dispatch

    def static_cstr(self, s: str) -> int:
        p = self._cstr_cache.get(s)
        if p is None:
            p = self._cstr_cache[s] = self.cpu.hle_cstr(s)
        return p

    # ---------------------------------------------------------------- modules
    def _scan_modules(self):
        """Find applets and extensions: <root>/mif/<n>.mif + <root>/mod/<n>/*.mod."""
        for mif in sorted(glob.glob(os.path.join(self.game_root, "mif", "*.mif"))):
            stem = os.path.splitext(os.path.basename(mif))[0]
            mod_dir = os.path.join(self.game_root, "mod", stem)
            mods = glob.glob(os.path.join(mod_dir, "*.mod"))
            if not mods:
                continue
            data = open(mif, "rb").read()
            applets = mif_applet_classes(data)
            try:
                strings = mif_strings(data)
            except Exception:
                strings = []
            title = next((s for s in strings if s and not s[0].isdigit() and "(" not in s), stem)
            if applets:
                info = ModuleInfo(mif, mods[0], mod_dir, applets, True, title)
                for cls in applets:
                    self.applets[cls] = info
            else:
                exp = mif_extension_classes(data)
                info = ModuleInfo(mif, mods[0], mod_dir, exp, False, title)
                for cls in exp:
                    self.extensions[cls] = info

    def _load_image(self, path: str, base: int) -> int:
        data = open(path, "rb").read()
        self.cpu.write(base, data)
        self.cpu.w32(base - 4, self.helpers.table)   # ROPI static base -> helper table
        self.log(f"[load] {os.path.basename(path)} ({len(data)} bytes) at 0x{base:08x}")
        return len(data)

    def _module_load(self, base: int) -> int:
        pp = self.heap.malloc(4)
        rc = self.cpu.call(base, self.shell.ptr, self.helpers.table, pp)
        mod = self.cpu.r32(pp)
        self.heap.free(pp)
        if rc != 0 or not mod:
            raise GuestFault(f"AEEMod_Load at 0x{base:08x} failed (rc={rc}, module=0x{mod:08x})")
        return mod

    def _module_create(self, module: int, cls: int) -> int:
        vt = self.cpu.r32(module)
        create = self.cpu.r32(vt + 8)
        pp = self.heap.malloc(4)
        self._pp_applet = pp
        if not self.applet_ptr:
            # AEEApplet_New writes the applet into *pp before its own code runs;
            # GetAppInstance must already see it (as on the phone).
            self.helpers.set_app_source(pp)
        rc = self.cpu.call(create, module, self.shell.ptr, cls, pp)
        obj = self.cpu.r32(pp)
        self._pp_applet = 0
        if self.applet_ptr:
            self.helpers.set_applet(self.applet_ptr)
        self.heap.free(pp)
        return obj if rc == 0 else 0

    def reapply_speed_patch(self):
        """Make the 3D engine's speed patches what `speed_patches` says: each one in place or not (also after a save
        state replaced the module's memory, with or without them, before this run loaded the module)."""
        from . import swerve_patch
        if self._swerve_base:
            bases = [self._swerve_base]
        elif any(os.path.basename(p).lower() == "swv21brew.mod" for p in self._loaded_ext):
            bases = range(EXT_MODULE_BASE, self._next_ext_base, EXT_MODULE_STRIDE)    # restored by a state: find it
        else:
            return
        base = swerve_patch.find_module(self.cpu, bases)
        if not base:
            if self.speed_patches:
                self.log("[load] 3D engine: speed patches not applied (the module is not the known one)")
            return
        self._swerve_base = base
        for name in swerve_patch.NAMES:
            if name in self.speed_patches:
                if swerve_patch.apply(self.cpu, base, name):
                    self.log(f"[load] 3D engine: speed patch '{name}' applied")
            elif swerve_patch.remove(self.cpu, base, name):
                self.log(f"[load] 3D engine: speed patch '{name}' removed")

    def load_extension(self, cls: int) -> int:
        info = self.extensions.get(cls)
        if info is None:
            return 0
        module = self._loaded_ext.get(info.mod_path)
        if module is None:
            base = self._next_ext_base
            size = self._load_image(info.mod_path, base)
            self._next_ext_base += max(EXT_MODULE_STRIDE, (size + 0xFFFFF) & ~0xFFFFF)
            if os.path.basename(info.mod_path).lower() == "swv21brew.mod":
                from . import swerve_patch
                if swerve_patch.module_is_known(self.cpu.read(base, size)):
                    self._swerve_base = base
                    self.reapply_speed_patch()
                elif self.speed_patches:
                    self.log("[load] 3D engine: speed patches not applied (the module is not the known one)")
            module = self._module_load(base)
            self._loaded_ext[info.mod_path] = module
            self.log(f"[load] extension '{info.title}' ready (IModule 0x{module:08x})")
        obj = self._module_create(module, cls)
        self.log(f"[load] extension class {clsname(cls)} -> 0x{obj:08x}")
        return obj

    # ---------------------------------------------------------------- classes
    def _register_builtin_classes(self):
        self.factories[AEECLSID_DISPLAY] = lambda: self.display
        self.factories[AEECLSID_FILEMGR] = lambda: FileMgr(self)
        from .graphics import Graphics
        from .shell import AEECLSID_GRAPHICS
        self.factories[AEECLSID_GRAPHICS] = lambda: Graphics(self)
        from .media import Media
        from .shell import (AEECLSID_MEDIA, AEECLSID_MEDIAADPCM, AEECLSID_MEDIAMIDI,
                            AEECLSID_MEDIAMP3, AEECLSID_MEDIAPCM, AEECLSID_MEDIAPMD,
                            AEECLSID_MEDIAQCP)
        for cls in (AEECLSID_MEDIA, AEECLSID_MEDIAMIDI, AEECLSID_MEDIAMP3, AEECLSID_MEDIAQCP,
                    AEECLSID_MEDIAPMD, AEECLSID_MEDIAADPCM, AEECLSID_MEDIAPCM):
            self.factories[cls] = (lambda k=cls: Media(self, k))
        from .shell import AEECLSID_WEB
        from .web import Web
        self.factories[AEECLSID_WEB] = lambda: Web(self)

    def web_request(self, url: str) -> tuple:
        """Answer one of the game's HTTP requests: (status code, body). Scores are
        always recorded in the offline leaderboard; when a shared one is set up, its
        ranking is the one shown, and the offline table answers if it can't be
        reached. Everything else (the dead servers) is a 404."""
        from .leaderboard import Leaderboard
        from .web import (default_leaderboard_path, share_scores, with_play_time, with_stats,
                          wonderland_post)
        if self.leaderboard is None:
            self.leaderboard = Leaderboard(default_leaderboard_path(self))
        answer = self.leaderboard.handle(url)
        if answer is None:
            self.log(f"[web] {url} -> 404")
            return 404, b""
        code, body = answer
        pt = getattr(self, "playtime", None)
        if pt:
            pt.on_post(url)
        if self.leaderboard_url:
            wonder = wonderland_post(url)
            if wonder and self.leaderboard.has_score("island", wonder[0]):
                # the same run was already shared as an Island score; do not count it twice
                self.log("[web] Wonderland repeats the Island score already shared; not sent again")
            else:
                target = wonder[1] if wonder else url
                if pt:
                    target = with_play_time(target, pt.seconds_for_url(url))
                    target = with_stats(target, pt.stats_for_url(url))
                shared = share_scores(target, self.leaderboard_url)
                if shared is None:
                    self.log("[web] the shared leaderboard didn't answer; using your own scores")
                else:
                    # the game asked about "wonderland", so it must be answered as such
                    body = shared.replace(b"|island~", b"|wonderland~") if wonder else shared
        self.log(f"[web] {url} -> {code} {body.decode('latin-1')}")
        return code, body

    def register_class(self, cls: int, factory):
        self.factories[cls] = factory

    def class_available(self, cls: int) -> bool:
        return cls in self.factories or cls in self.extensions or cls in self.applets

    def create_instance(self, cls: int) -> int:
        f = self.factories.get(cls)
        if f is not None:
            obj = f()
            if obj is None:
                return 0
            if obj is self.display:
                obj.refs += 1
            return obj.ptr
        if cls in self.extensions:
            return self.load_extension(cls)
        if cls in self.probe_classes:
            return ProbeObject(self, cls).ptr
        return 0

    probe_classes: set = set()

    # ---------------------------------------------------------------- applet
    def current_applet_ptr(self) -> int:
        if self.applet_ptr:
            return self.applet_ptr
        pp = getattr(self, "_pp_applet", 0)
        return self.cpu.r32(pp) if pp else 0

    def setup_files(self, applet_cls: int = 0):
        """Mount the game folder + save overlay and install the chapter patches
        (everything start() does before running guest code; load_state needs it too)."""
        if not self.applets:
            raise RuntimeError(f"no applet MIF found under {self.game_root}/mif")
        if not applet_cls:
            applet_cls = next(iter(self.applets))
        info = self.applets[applet_cls]
        self.applet_cls = applet_cls
        overlay = os.path.join(self.data_dir, "files")
        self.vfs = Vfs([info.mod_dir], overlay, self.log)
        from .chapters import install_patches
        install_patches(self, self.skip_wonderland)
        for hook in self.vfs_hooks:
            hook(self.vfs)
        return info

    def start(self, applet_cls: int = 0):
        info = self.setup_files(applet_cls)
        applet_cls = self.applet_cls
        self.log(f"[load] applet '{info.title}' class 0x{applet_cls:08x} from {info.mod_dir}")
        self._load_image(info.mod_path, MAIN_MODULE_BASE)
        self.module_ptr = self._module_load(MAIN_MODULE_BASE)
        self.applet_ptr = self._module_create(self.module_ptr, applet_cls)
        if not self.applet_ptr:
            raise GuestFault("IModule::CreateInstance did not return an applet")
        self.helpers.set_applet(self.applet_ptr)
        vt = self.cpu.r32(self.applet_ptr)
        self.handle_event = self.cpu.r32(vt + 8)
        self.log(f"[load] applet 0x{self.applet_ptr:08x}, HandleEvent 0x{self.handle_event:08x}")
        # AEEAppStart { int error; AEECLSID clsApp; IDisplay *pDisplay; AEERect rc; const char *pszArgs; }
        w, h = self.screen
        st = self.heap.malloc(32)
        self.cpu.write(st, struct.pack("<iII4hI", 0, applet_cls, self.display.ptr, 0, 0, w, h, 0))
        ok = self.send_event(EVT_APP_START, 0, st)
        self.log(f"[load] EVT_APP_START -> {ok}")
        return ok

    def send_event(self, evt: int, wp: int = 0, dwp: int = 0) -> int:
        if not self.handle_event:
            return 0
        try:
            return self.cpu.call(self.handle_event, self.applet_ptr, evt, wp & 0xFFFF, dwp)
        except GuestFault as e:
            self.faults += 1
            self.log(f"[fault] HandleEvent(0x{evt:x}, 0x{wp:x}): {e}")
            self.dump_recent()
            return 0

    def post_event(self, evt, wp=0, dwp=0):
        self.pending_events.append((evt, wp, dwp))

    def key_down(self, avk: int):
        self.keys_held.add(avk)
        self.post_event(EVT_KEY_PRESS, avk, 0)
        self.post_event(EVT_KEY, avk, 0)

    def key_up(self, avk: int):
        self.keys_held.discard(avk)
        self.post_event(EVT_KEY_RELEASE, avk, 0)

    # ---------------------------------------------------------------- save states
    def save_state(self, path: str, thumbnail: bool = True) -> dict:
        from .savestate import save_state
        return save_state(self, path, thumbnail=thumbnail)

    def load_state(self, path: str) -> dict:
        from .savestate import load_state
        return load_state(self, path)

    def request_exit(self):
        self.exit_requested = True

    def stop(self):
        self.send_event(EVT_APP_STOP)

    # ---------------------------------------------------------------- timers
    def set_timer(self, ms: int, fn: int, user: int):
        self.cancel_timer(fn, user)
        self._timer_seq += 1
        heapq.heappush(self.timers, Timer(self.clock_ms() + ms, self._timer_seq, fn, user))

    def cancel_timer(self, fn: int, user: int):
        for t in self.timers:
            if not t.cancelled and t.user == user and (fn == 0 or t.fn == fn):
                t.cancelled = True

    def timer_remaining(self, fn: int, user: int) -> int:
        now = self.clock_ms()
        for t in self.timers:
            if not t.cancelled and t.fn == fn and (user == 0 or t.user == user):
                return max(0, int(t.due - now))
        return 0

    def call_soon(self, fn: int, user: int):
        self._timer_seq += 1
        heapq.heappush(self.timers, Timer(self.clock_ms(), self._timer_seq, fn, user))

    def call_soon_args(self, fn: int, *args: int, delay_ms: int = 0):
        self._timer_seq += 1
        heapq.heappush(self.timers, Timer(self.clock_ms() + delay_ms, self._timer_seq, fn,
                                          args[0] if args else 0, args=tuple(args)))

    def resume_callback(self, pcb: int, delay_ms: int = 0):
        """ISHELL_Resume: AEECallback {pNext, pmc, pfnCancel, pCancelData, pfnNotify, pNotifyData}."""
        fn = self.cpu.r32(pcb + 16)
        data = self.cpu.r32(pcb + 20)
        self.cpu.w32(pcb + 8, self._cancel_trap())   # mark queued
        self.cpu.w32(pcb + 12, pcb)
        for t in self.timers:          # re-queueing the same callback moves it
            if getattr(t, "pcb", None) == pcb:
                t.cancelled = True
        self._timer_seq += 1
        t = Timer(self.clock_ms() + delay_ms, self._timer_seq, fn, data)
        t.pcb = pcb  # type: ignore[attr-defined]
        heapq.heappush(self.timers, t)

    def _cancel_trap(self) -> int:
        if not hasattr(self, "_cancel_fn"):
            self._cancel_fn = self.cpu.trap("AEECallback::Cancel", self._make_cancel())
        return self._cancel_fn

    def _make_cancel(self):
        def cancel(c):
            pcb = c.arg(0)
            for t in self.timers:
                if getattr(t, "pcb", None) == pcb:
                    t.cancelled = True
            self.cpu.w32(pcb + 8, 0)
            return None
        return cancel

    def next_due(self) -> Optional[float]:
        while self.timers and self.timers[0].cancelled:
            heapq.heappop(self.timers)
        return self.timers[0].due if self.timers else None

    def run_due(self, max_calls: int = 64) -> int:
        """Deliver posted events and fire due timers. Returns calls made."""
        n = 0
        while self.pending_events and n < max_calls:
            evt, wp, dwp = self.pending_events.pop(0)
            self.send_event(evt, wp, dwp)
            n += 1
        self.audio.tick()
        now = self.clock_ms()
        while n < max_calls:
            due = self.next_due()
            if due is None or due > now:
                break
            t = heapq.heappop(self.timers)
            pcb = getattr(t, "pcb", None)
            if pcb:
                self.cpu.w32(pcb + 8, 0)
            try:
                self.cpu.call(t.fn, *(t.args or (t.user,)))
            except GuestFault as e:
                self.faults += 1
                self.log(f"[fault] timer 0x{t.fn:08x}(0x{t.user:08x}): {e}")
                self.dump_recent()
            n += 1
        return n

    def dump_recent(self):
        self.log("  last BREW calls (oldest first):")
        for name, a0, a1, a2, lr in self.cpu.recent:
            self.log(f"    {name}(0x{a0:x}, 0x{a1:x}, 0x{a2:x}) lr=0x{lr:08x}")

    # ---------------------------------------------------------------- output
    def present(self, dib):
        self.frames += 1
        self.last_frame = dib.pixels()
        for fn in self.frame_listeners:
            fn(self.last_frame)

    # ---------------------------------------------------------------- hooks
    def on_file_opened(self, name, mode):
        low = name.lower().replace("\\", "/").rsplit("/", 1)[-1]
        if low.startswith("ro_") and low.endswith("_jtext.m3g"):
            self.wonderland_splash_up = False
        pt = getattr(self, "playtime", None)
        if pt:
            pt.file_opened(name)
        for h in self.hooks:
            f = getattr(h, "on_file_opened", None)
            if f:
                f(name, mode)

    def on_missing_file(self, name):
        for h in self.hooks:
            f = getattr(h, "on_missing_file", None)
            if f:
                f(name)

    def make_image(self, raw: bytes):
        from .image import Image
        return Image.from_bytes(self, raw)
