"""Save states: snapshot the whole emulator to a file and restore it exactly.

What is saved:
  * guest memory: the module/stack block, the heap and the used part of the
    HLE region, as non-zero 4 KiB pages (zlib-compressed);
  * the Python side: heap bookkeeping, timers, pending events, every HLE
    object's fields, the trap table, the clock, helper RNG and which media
    voices were playing.

CPU registers are not saved: states are only taken between guest calls
(cpu.depth == 0), where cpu.call() has already put the registers back to
their initial values.

The trap table is the subtle part. Every BREW function the game can call has
an address on the trap page, handed out in creation order, and the game keeps
those addresses in memory (vtables, callback cancel pointers). Their Python
handlers are closures, so a load rebuilds each one from what it was: a class
vtable slot (runtime._trap_meta), the callback cancel stub, or one of the
helper-table entries every Emulator creates identically at start-up.

File layout: MAGIC, u32 header length, JSON header, zlib(pickle(payload)).
States are pickles: load only your own, never one from an untrusted source.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import struct
import time
import zlib

import numpy as np

# import every module that defines HleObject classes so pickled classes resolve
from . import display, files, graphics, hle, image, media, shell  # noqa: F401
from .cpu import HEAP_BASE, HEAP_SIZE, HLE_BASE, HLE_SIZE, LOW_BASE, LOW_SIZE, TrapInfo
from .hle import HleObject

MAGIC = b"KHVCEMU\x01"
LEGACY_MAGIC = b"KHEMUSS\x01"        # states made before the rename to khvcemu still load
FORMAT = 1
PAGE = 4096

# object fields never saved: back-references (re-attached on load) and host-side
# caches or handles (pygame fonts/surfaces, audio channels)
_SKIP = {"emu", "cpu"}
_CLASS_SKIP = {"Display": {"_fonts", "_hires"}, "Media": {"voice"}, "Shell": {"res_cache"}}
_DEFAULTS = {"Media": {"voice": lambda: None}, "Shell": {"res_cache": dict}}

_EMU_FIELDS = ("timers", "_timer_seq", "pending_events", "_vtables", "_cstr_cache",
               "_loaded_ext", "_next_ext_base", "applet_cls", "applet_ptr", "handle_event",
               "module_ptr", "frames", "faults", "last_frame", "recent_files", "keys_held",
               "wonderland_splash_up")


class StateError(Exception):
    """A state could not be saved or loaded (nothing was changed)."""


# ----------------------------------------------------------------------------- helpers
def game_fingerprint(emu) -> str:
    """SHA-1 over the game's code modules: states only load on the same files."""
    h = hashlib.sha1()
    paths = sorted({i.mod_path for i in list(emu.applets.values()) + list(emu.extensions.values())})
    for p in paths:
        h.update(os.path.basename(p).lower().encode())
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def read_header(path: str) -> dict:
    with open(path, "rb") as f:
        head = f.read(len(MAGIC) + 4)
        if len(head) < len(MAGIC) + 4 or not head.startswith((MAGIC, LEGACY_MAGIC)):
            raise StateError(f"{os.path.basename(path)} is not a khvcemu save state")
        (n,) = struct.unpack("<I", head[len(MAGIC):])
        return json.loads(f.read(n))


class _Pickler(pickle.Pickler):
    """References to HLE objects and emulator singletons become ids."""

    def __init__(self, f, emu, found: dict):
        super().__init__(f, protocol=pickle.HIGHEST_PROTOCOL)
        self._named = {id(emu): "emu", id(emu.cpu): "cpu", id(emu.heap): "heap",
                       id(emu.helpers): "helpers", id(emu.audio): "audio"}
        if emu.vfs is not None:
            self._named[id(emu.vfs)] = "vfs"
        self._found = found

    def persistent_id(self, obj):
        if isinstance(obj, HleObject):
            self._found.setdefault(obj.ptr, obj)
            return ("obj", obj.ptr)
        name = self._named.get(id(obj))
        return ("emu", name) if name else None


class _CompatUnpickler(pickle.Unpickler):
    """Maps classes pickled under the old package name (khemu.*) to khvcemu.*."""

    def find_class(self, module, name):
        if module == "khemu" or module.startswith("khemu."):
            module = "khvcemu" + module[len("khemu"):]
        return super().find_class(module, name)


class _Unpickler(_CompatUnpickler):
    def __init__(self, f, emu, instances: dict):
        super().__init__(f)
        self._emu = emu
        self._instances = instances

    def persistent_load(self, pid):
        kind, key = pid
        if kind == "obj":
            try:
                return self._instances[key]
            except KeyError:
                raise StateError(f"state refers to a missing object 0x{key:08x}") from None
        return {"emu": self._emu, "cpu": self._emu.cpu, "heap": self._emu.heap,
                "helpers": self._emu.helpers, "audio": self._emu.audio, "vfs": self._emu.vfs}[key]


def _dumps(obj, emu, found: dict) -> bytes:
    buf = io.BytesIO()
    _Pickler(buf, emu, found).dump(obj)
    return buf.getvalue()


def _object_state(obj) -> dict:
    skip = _SKIP | _CLASS_SKIP.get(type(obj).__name__, set())
    return {k: v for k, v in obj.__dict__.items() if k not in skip}


def _dump_region(uc, base: int, size: int):
    raw = uc.mem_read(base, size)
    words = np.frombuffer(raw, np.uint64).reshape(-1, PAGE // 8)
    idx = np.nonzero(words.any(axis=1))[0].astype(np.uint32)
    pages = np.frombuffer(raw, np.uint8).reshape(-1, PAGE)[idx]
    return idx.tobytes(), pages.tobytes()


def _restore_region(uc, base: int, size: int, idx_b: bytes, pages_b: bytes):
    uc.mem_write(base, bytes(size))
    idx = np.frombuffer(idx_b, np.uint32)
    if not len(idx):
        return
    pages = np.frombuffer(pages_b, np.uint8).reshape(-1, PAGE)
    # write runs of consecutive pages in one call each
    breaks = np.nonzero(np.diff(idx) != 1)[0] + 1
    for run in np.split(np.arange(len(idx)), breaks):
        first = int(idx[run[0]])
        uc.mem_write(base + first * PAGE, pages[run[0]:run[-1] + 1].tobytes())


def _write_thumbnail(emu, path: str):
    if emu.last_frame is None:
        return
    try:
        import pygame
        f = emu.last_frame.astype(np.uint32)
        rgb = np.stack([((f >> 11) & 31) * 255 // 31, ((f >> 5) & 63) * 255 // 63,
                        (f & 31) * 255 // 31], -1).astype(np.uint8)
        pygame.image.save(pygame.surfarray.make_surface(rgb.transpose(1, 0, 2)), path)
    except Exception:
        pass        # a thumbnail is a nicety; never fail a save over it


# ----------------------------------------------------------------------------- save
def save_state(emu, path: str, thumbnail: bool = True) -> dict:
    cpu = emu.cpu
    if cpu.depth:
        raise StateError("can't save while the game is in the middle of a call")
    if not emu.applet_ptr:
        raise StateError("the game hasn't started yet")

    found: dict = dict(emu.objects)
    emu_fields = {k: getattr(emu, k) for k in _EMU_FIELDS}
    if hasattr(emu, "_cancel_fn"):
        emu_fields["_cancel_fn"] = emu._cancel_fn
    emu_blob = _dumps(emu_fields, emu, found)

    objects: dict = {}
    pending = list(found)
    while pending:
        ptr = pending.pop()
        if ptr in objects:
            continue
        obj = found[ptr]
        before = set(found)
        state = _object_state(obj)
        try:
            blob = _dumps(state, emu, found)
        except Exception as e:
            bad = next((k for k, v in state.items() if not _picklable(v, emu)), "?")
            raise StateError(f"can't save {type(obj).__name__}.{bad}: {e}") from None
        objects[ptr] = (type(obj), blob)
        pending += [p for p in found if p not in before]

    traps = [(addr, info.name, emu._trap_meta.get(addr)) for addr, info in sorted(cpu.traps.items())]
    voices = {ptr: obj.voice_record() for ptr, obj in emu.objects.items()
              if isinstance(obj, media.Media) and obj.voice is not None}
    memory = []
    hle_used = -(-(cpu._hle_cursor - HLE_BASE) // PAGE) * PAGE
    for base, size, dump_size in ((LOW_BASE, LOW_SIZE, LOW_SIZE), (HEAP_BASE, HEAP_SIZE, HEAP_SIZE),
                                  (HLE_BASE, HLE_SIZE, max(PAGE, hle_used))):
        memory.append((base, size) + _dump_region(cpu.uc, base, dump_size))

    payload = {
        "memory": memory,
        "cpu": {"next_trap": cpu._next_trap, "hle_cursor": cpu._hle_cursor},
        "heap": {"free_starts": list(emu.heap.free_starts), "free_sizes": dict(emu.heap.free_sizes),
                 "used": dict(emu.heap.used)},
        "traps": traps,
        "emu": emu_blob,
        "objects": objects,
        "attached": sorted(emu.objects),
        "shell": emu.shell.ptr,
        "display": emu.display.ptr,
        "helpers": {"rng": emu.helpers.rng.getstate(), "last_error": emu.helpers.last_error},
        "voices": {p: r for p, r in voices.items() if r},
        "clock_ms": emu.clock_ms(),
        "playtime_world": getattr(getattr(emu, "playtime", None), "world", None),
    }
    header = {
        "format": FORMAT,
        "game": game_fingerprint(emu),
        "screen": list(emu.screen),
        "skip_wonderland": emu.skip_wonderland,
        "created": time.time(),
        "clock_ms": payload["clock_ms"],
    }
    hb = json.dumps(header).encode()
    blob = zlib.compress(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL), 1)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(MAGIC + struct.pack("<I", len(hb)) + hb + blob)
    os.replace(tmp, path)
    if thumbnail:
        _write_thumbnail(emu, os.path.splitext(path)[0] + ".png")
    return header


def _picklable(v, emu) -> bool:
    try:
        _dumps(v, emu, {})
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------- load
def load_state(emu, path: str) -> dict:
    cpu = emu.cpu
    if cpu.depth:
        raise StateError("can't load while the game is in the middle of a call")
    header = read_header(path)
    if header.get("format") != FORMAT:
        raise StateError("this state was made by a different khvcemu version")
    if header.get("game") != game_fingerprint(emu):
        raise StateError("this state was made with different game files")
    if tuple(header.get("screen", ())) != tuple(emu.screen):
        raise StateError(f"this state was made at screen size {header.get('screen')}")
    if header.get("skip_wonderland") != emu.skip_wonderland:
        raise StateError("this state was made with a different --keep-wonderland setting")
    with open(path, "rb") as f:
        data = f.read()
    hlen = struct.unpack_from("<I", data, len(MAGIC))[0]
    try:
        payload = _CompatUnpickler(io.BytesIO(zlib.decompress(data[len(MAGIC) + 4 + hlen:]))).load()
    except Exception as e:
        raise StateError(f"state file is damaged ({e})") from None

    # ---- decode everything first; nothing in the emulator changes until it all checks out
    traps, meta = {}, {}
    for addr, name, m in payload["traps"]:
        if m is not None:
            cls, idx, slot = m
            traps[addr] = TrapInfo(name, emu._make_dispatch(cls, idx, slot))
            meta[addr] = m
        elif name == "AEECallback::Cancel":
            traps[addr] = TrapInfo(name, emu._make_cancel())
        else:
            info = cpu.traps.get(addr)
            if info is None or info.name != name:
                raise StateError(f"incompatible state: BREW function '{name}' moved")
            traps[addr] = info

    if emu.vfs is None:
        emu.setup_files()
    instances = {}
    for ptr, (cls, _) in payload["objects"].items():
        cur = emu.objects.get(ptr)
        instances[ptr] = cur if type(cur) is cls else cls.__new__(cls)
    states = {ptr: _Unpickler(io.BytesIO(blob), emu, instances).load()
              for ptr, (_, blob) in payload["objects"].items()}
    emu_fields = _Unpickler(io.BytesIO(payload["emu"]), emu, instances).load()

    # ---- commit
    emu.audio.stop_all()
    for obj in emu.objects.values():
        if isinstance(obj, media.Media):
            obj.voice = None
    for base, size, idx_b, pages_b in payload["memory"]:
        _restore_region(cpu.uc, base, size, idx_b, pages_b)
    cpu.uc.ctl_flush_tb()          # drop code translated from the old memory
    cpu._next_trap = payload["cpu"]["next_trap"]
    cpu._hle_cursor = payload["cpu"]["hle_cursor"]
    cpu.traps = traps
    emu._trap_meta = meta
    h = payload["heap"]
    emu.heap.free_starts, emu.heap.free_sizes, emu.heap.used = h["free_starts"], h["free_sizes"], h["used"]

    for ptr, inst in instances.items():
        inst.__dict__.clear()
        inst.__dict__.update(states[ptr])
        inst.emu, inst.cpu = emu, cpu
        for k, make in _DEFAULTS.get(type(inst).__name__, {}).items():
            setattr(inst, k, make())
    emu.objects = {ptr: instances[ptr] for ptr in payload["attached"]}
    emu.shell = instances[payload["shell"]]
    emu.display = instances[payload["display"]]

    cancel = emu_fields.pop("_cancel_fn", None)
    for k, v in emu_fields.items():
        setattr(emu, k, v)
    if cancel is not None:
        emu._cancel_fn = cancel
    elif hasattr(emu, "_cancel_fn"):
        del emu._cancel_fn
    emu.reapply_speed_patch()      # the restored memory has the 3D engine as it was when the state was made
    emu.helpers.rng.setstate(payload["helpers"]["rng"])
    emu.helpers.last_error = payload["helpers"]["last_error"]

    ms = payload["clock_ms"]
    if emu.realtime:
        emu._t0 = time.monotonic() - ms / 1000
    else:
        emu._virtual_ms = float(ms)
    emu.overlay = None
    emu.exit_requested = False
    if getattr(emu, "playtime", None):
        emu.playtime.resync(payload.get("playtime_world"))

    for ptr, rec in payload["voices"].items():
        obj = emu.objects.get(ptr)
        if isinstance(obj, media.Media):
            obj.resume_voice(rec)
    # the player isn't holding anything now: let go of keys held at save time
    for avk in sorted(emu.keys_held):
        emu.key_up(avk)
    return header


# ----------------------------------------------------------------------------- slots
AUTOSAVE_EVERY_MS = 5 * 60 * 1000      # of play time (the clock stops while paused)
AUTOSAVES_KEPT = 3
AREA_SAVE_DELAY_MS = 3000                # an autosave this long after "Loading..." has gone from the screen
AREA_SAVE_MIN_GAP_MS = 30 * 1000         # but never within this long of the last autosave (a door, then another)


class StateSlots:
    """Numbered slots 1-9 plus rotating autosaves, in <data dir>/states/.

    Slot 0 means "the autosave": loading it loads the newest one (auto1);
    auto2 and auto3 are the two before it (loadable with --load-state auto2)."""

    def __init__(self, emu, folder: str = None):
        self.emu = emu
        self.folder = folder or os.path.join(emu.data_dir, "states")
        self.slot = 1
        self.autosave_enabled = True
        self.last_auto_ms = emu.clock_ms()
        self.last_autosave_ms = None          # when the last autosave was written (any kind); None: none yet

    def path(self, slot) -> str:
        name = f"slot{slot}" if isinstance(slot, int) and slot > 0 else (
            "auto1" if slot in (0, "auto") else str(slot))
        return os.path.join(self.folder, name + ".khs")

    @staticmethod
    def parse(name: str):
        """CLI/launcher slot name -> slot: '1'..'9', 'auto' (= auto1), 'auto2', 'auto3'."""
        s = str(name).strip().lower()
        if s.isdigit() and 0 <= int(s) <= 9:
            return int(s)
        if s == "auto" or (s.startswith("auto") and s[4:].isdigit() and 1 <= int(s[4:]) <= AUTOSAVES_KEPT):
            return 0 if s in ("auto", "auto1") else s
        raise ValueError(f"unknown save-state slot '{name}' (use 1-9, auto, auto2 or auto3)")

    @staticmethod
    def label(slot) -> str:
        return "the autosave" if slot in (0, "auto") else (f"slot {slot}" if isinstance(slot, int) else slot)

    def describe(self, slot) -> str:
        p = self.path(slot)
        if not os.path.isfile(p):
            return f"{self.label(slot).capitalize()} (empty)"
        try:
            when = time.strftime("%b %d %H:%M", time.localtime(read_header(p)["created"]))
        except Exception:
            when = "unreadable"
        return f"{self.label(slot).capitalize()} - saved {when}"

    def save(self, slot=None) -> str:
        slot = self.slot if slot is None else slot
        if slot == 0:
            return "Slot 0 is the autosave - pick slot 1-9 with F6/F7 to save"
        self.emu.save_state(self.path(slot))
        # no reset of last_auto_ms: saving by hand into a slot is not a reason to skip the autosave
        return f"Saved to {self.label(slot)}"

    def load(self, slot=None) -> str:
        slot = self.slot if slot is None else slot
        p = self.path(slot)
        if not os.path.isfile(p):
            return f"{self.label(slot).capitalize()} is empty"
        hdr = self.emu.load_state(p)
        self.last_auto_ms = self.emu.clock_ms()
        when = time.strftime("%b %d %H:%M", time.localtime(hdr["created"]))
        return f"Loaded {self.label(slot)} (saved {when})"

    def autosave_due(self) -> bool:
        return (self.autosave_enabled and bool(self.emu.applet_ptr)
                and self.emu.clock_ms() - self.last_auto_ms >= AUTOSAVE_EVERY_MS)

    def area_save_due(self) -> bool:
        """True a few seconds after the game finished a "Loading..." screen (a new area): a good
        moment for a checkpoint. The caller clears emu.last_loading_ms and decides whether to save."""
        loading = getattr(self.emu, "last_loading_ms", None)
        return (self.autosave_enabled and loading is not None and bool(self.emu.applet_ptr)
                and self.emu.clock_ms() - loading >= AREA_SAVE_DELAY_MS)

    def area_save_allowed(self) -> bool:
        """The first area after the window opens may save at once; after that, not within
        AREA_SAVE_MIN_GAP_MS of the previous autosave."""
        last = self.last_autosave_ms
        return last is None or self.emu.clock_ms() - last >= AREA_SAVE_MIN_GAP_MS

    def autosave(self) -> str:
        """Rotate auto1 -> auto2 -> auto3 (oldest dropped), then write auto1."""
        os.makedirs(self.folder, exist_ok=True)
        tmp = os.path.join(self.folder, "auto_new.khs")
        self.emu.save_state(tmp)          # write first, so a failed save rotates nothing
        for i in range(AUTOSAVES_KEPT, 1, -1):
            for ext in (".khs", ".png"):
                src = os.path.join(self.folder, f"auto{i - 1}{ext}")
                if os.path.exists(src):
                    os.replace(src, os.path.join(self.folder, f"auto{i}{ext}"))
        os.replace(tmp, os.path.join(self.folder, "auto1.khs"))
        if os.path.exists(os.path.join(self.folder, "auto_new.png")):
            os.replace(os.path.join(self.folder, "auto_new.png"), os.path.join(self.folder, "auto1.png"))
        self.last_auto_ms = self.last_autosave_ms = self.emu.clock_ms()
        return "Autosaved"
