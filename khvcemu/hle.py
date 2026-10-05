"""HLE interface objects.

A BREW interface pointer points at an object whose first word is its vtable.
Each Python HLE class declares its slot names in vtable order; the emulator
builds one vtable per class (one trap per slot) and dispatches each call to
the Python instance that owns the object pointer passed in R0.

Slots without a Python implementation log once (with their arguments) and
return a configurable default, so unimplemented calls show up by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .cpu import CallCtx

if TYPE_CHECKING:
    from .runtime import Emulator

# AEEError.h
SUCCESS = 0
EFAILED = 1
ENOMEMORY = 2
ECLASSNOTSUPPORT = 3
EBADPARM = 14
EUNSUPPORTED = 20
EITEMBUSY = 32
EFILEEXISTS = 0x101
EFILENOEXISTS = 0x102
EBADFILENAME = 0x104

# ISource / IAStream read results
ISOURCE_END = 0
ISOURCE_ERROR = -1
ISOURCE_WAIT = -2
AEE_STREAM_WAIT = -2


class HleObject:
    """Base class. Subclasses set IFACE and SLOTS (vtable order)."""

    IFACE = "IBase"
    SLOTS: tuple = ("AddRef", "Release")
    OBJ_SIZE = 16          # bytes reserved for the object (vtable ptr + fields)
    STUB_RETURN = 0        # default return for unimplemented slots

    def __init__(self, emu: "Emulator", obj_size: Optional[int] = None):
        self.emu = emu
        self.cpu = emu.cpu
        self.refs = 1
        size = obj_size or self.OBJ_SIZE
        self.ptr = emu.cpu.hle_alloc(max(size, 8), 8)
        emu.cpu.w32(self.ptr, emu.vtable_for(type(self)))
        emu.objects[self.ptr] = self

    # IBase
    def AddRef(self, c: CallCtx):
        self.refs += 1
        return self.refs

    def Release(self, c: CallCtx):
        self.refs = max(0, self.refs - 1)
        if self.refs == 0:
            self.on_final_release()
        return self.refs

    def on_final_release(self):
        pass

    # IQueryInterface-style default
    def QueryInterface(self, c: CallCtx):
        cls, ppo = c.arg(1), c.arg(2)
        if ppo:
            self.cpu.w32(ppo, self.ptr)
            self.refs += 1
        return SUCCESS


class ProbeObject(HleObject):
    """Stand-in for a class nobody implements: 64 logging slots."""

    IFACE = "Probe"
    SLOTS = ("AddRef", "Release") + tuple(f"slot{i}" for i in range(2, 64))
    STUB_RETURN = EUNSUPPORTED

    def __init__(self, emu, clsid: int):
        super().__init__(emu)
        self.clsid = clsid
        self.IFACE = f"Probe[0x{clsid:08x}]"
