"""ARM CPU + guest memory, built on Unicorn.

The guest is ARMv5TE code (the phones ran an ARM926EJ-S). Everything the
game calls into BREW goes through a *trap page*: each HLE function gets a
unique address in that page holding a single `bx lr`. A code hook on the
page runs the Python implementation, writes R0, and the `bx lr` then
returns to the caller in whatever state (ARM/Thumb) it came from.

Guest -> host -> guest re-entry (e.g. the shell delivering an event to
the applet from inside a BREW call) uses Unicorn's nested emu_start.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Optional

from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_MEM_INVALID,
                     UC_MODE_ARM, UC_PROT_ALL, Uc, UcError)
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC,
                               UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R3, UC_ARM_REG_SP, UC_CPU_ARM_926)

# ---------------------------------------------------------------------------
# Memory map
# ---------------------------------------------------------------------------
LOW_BASE = 0x00010000          # modules + stack live in one RWX block
LOW_SIZE = 0x03000000 - LOW_BASE
MAIN_MODULE_BASE = 0x00100000  # kh.mod (static-base word at base-4)
EXT_MODULE_BASE = 0x01000000   # extension modules (swv21brew.mod), 4 MiB apart
EXT_MODULE_STRIDE = 0x00400000
STACK_TOP = 0x02F00000
STACK_SIZE = 0x00400000

HEAP_BASE = 0x10000000
HEAP_SIZE = 0x04000000         # 64 MiB guest heap

HLE_BASE = 0x80000000          # HLE objects, vtables, scratch
HLE_SIZE = 0x01000000

TRAP_BASE = 0xF0000000
TRAP_SIZE = 0x00040000         # 64K trap slots
BX_LR = 0xE12FFF1E

REG_ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


class GuestFault(RuntimeError):
    pass


@dataclass
class TrapInfo:
    name: str
    fn: Callable[["CallCtx"], Optional[int]]


class CallCtx:
    """Arguments of one HLE call, read lazily (AAPCS: r0-r3, then stack).
    Register reads through the Python binding are slow, so only what a
    handler asks for is fetched."""

    __slots__ = ("cpu", "_regs", "_sp", "_lr", "name")

    def __init__(self, cpu: "Cpu", name: str):
        self.cpu = cpu
        self._regs = [None, None, None, None]
        self._sp = None
        self._lr = None
        self.name = name

    @property
    def sp(self) -> int:
        if self._sp is None:
            self._sp = self.cpu.uc.reg_read(UC_ARM_REG_SP)
        return self._sp

    @property
    def lr(self) -> int:
        if self._lr is None:
            self._lr = self.cpu.uc.reg_read(UC_ARM_REG_LR)
        return self._lr

    def arg(self, i: int) -> int:
        if i < 4:
            v = self._regs[i]
            if v is None:
                v = self._regs[i] = self.cpu.uc.reg_read(REG_ARGS[i])
            return v
        return self.cpu.r32(self.sp + 4 * (i - 4))

    def sarg(self, i: int) -> int:
        v = self.arg(i)
        return v - (1 << 32) if v & 0x80000000 else v

    def args(self, n: int) -> list:
        return [self.arg(i) for i in range(n)]


class Cpu:
    def __init__(self, log=print):
        self.log = log
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        try:
            uc.ctl_set_cpu_model(UC_CPU_ARM_926)
        except Exception:  # older unicorn: default model still runs ARMv5 code
            pass
        self.uc = uc
        uc.mem_map(LOW_BASE, LOW_SIZE, UC_PROT_ALL)
        uc.mem_map(HEAP_BASE, HEAP_SIZE, UC_PROT_ALL)
        uc.mem_map(HLE_BASE, HLE_SIZE, UC_PROT_ALL)
        uc.mem_map(TRAP_BASE, TRAP_SIZE, UC_PROT_ALL)
        uc.mem_write(TRAP_BASE, struct.pack("<I", BX_LR) * (TRAP_SIZE // 4))
        self.traps: dict[int, TrapInfo] = {}
        self._next_trap = TRAP_BASE + 0x100   # 0..0xff reserved (exit pads)
        self.exit_addr = TRAP_BASE             # call_guest returns here
        uc.hook_add(UC_HOOK_CODE, self._on_trap, begin=TRAP_BASE, end=TRAP_BASE + TRAP_SIZE - 1)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._on_bad_mem)
        # Run guest code in User mode. Swerve checks the mode bits and only
        # pokes the MMU (CP15) when it thinks it is privileged. (Set the mode
        # before SP: SP is banked per mode.)
        uc.reg_write(UC_ARM_REG_CPSR, 0xD0)
        uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        self._hle_cursor = HLE_BASE
        self.depth = 0
        import collections
        self.recent = collections.deque(maxlen=24)
        self.keep_recent_args = False
        self.fault: Optional[str] = None
        self.trace_calls = False
        self.on_trap_error: Optional[Callable[[str, BaseException], None]] = None

    # ------------------------------------------------------------------ memory
    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def r16(self, a):
        return struct.unpack("<H", self.uc.mem_read(a, 2))[0]

    def r32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def s32(self, a):
        return struct.unpack("<i", self.uc.mem_read(a, 4))[0]

    def w8(self, a, v):
        self.uc.mem_write(a, bytes([v & 0xFF]))

    def w16(self, a, v):
        self.uc.mem_write(a, struct.pack("<H", v & 0xFFFF))

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def read(self, a, n) -> bytes:
        return bytes(self.uc.mem_read(a, n)) if n > 0 else b""

    def write(self, a, data: bytes):
        if data:
            self.uc.mem_write(a, bytes(data))

    def cstr(self, a, limit=4096) -> str:
        if not a:
            return ""
        out = bytearray()
        while len(out) < limit:
            chunk = self.uc.mem_read(a + len(out), 64)
            z = chunk.find(0)
            if z >= 0:
                out += chunk[:z]
                break
            out += chunk
        return out.decode("latin-1")

    def cstr_bytes(self, a, limit=1 << 20) -> bytes:
        return self.cstr(a, limit).encode("latin-1")

    def wstr(self, a, limit=4096) -> str:
        if not a:
            return ""
        chars = []
        while len(chars) < limit:
            c = self.r16(a + 2 * len(chars))
            if c == 0:
                break
            chars.append(chr(c))
        return "".join(chars)

    def hle_alloc(self, size: int, align: int = 8) -> int:
        """Permanent allocation in the HLE region (vtables, objects, strings)."""
        a = (self._hle_cursor + align - 1) & ~(align - 1)
        if a + size > HLE_BASE + HLE_SIZE:
            raise MemoryError("HLE region exhausted")
        self._hle_cursor = a + size
        self.uc.mem_write(a, b"\0" * size)
        return a

    def hle_cstr(self, s: str) -> int:
        b = s.encode("latin-1") + b"\0"
        a = self.hle_alloc(len(b), 4)
        self.write(a, b)
        return a

    # ------------------------------------------------------------------- traps
    def trap(self, name: str, fn: Callable[[CallCtx], Optional[int]]) -> int:
        addr = self._next_trap
        self._next_trap += 4
        if self._next_trap >= TRAP_BASE + TRAP_SIZE:
            raise MemoryError("trap page exhausted")
        self.traps[addr] = TrapInfo(name, fn)
        return addr

    def _on_trap(self, uc, addr, size, _ud):
        info = self.traps.get(addr)
        if info is None:
            if addr >= TRAP_BASE + 0x100:
                self.fault = f"jump into unassigned trap 0x{addr:08x}"
                uc.emu_stop()
            return  # exit pad: emu_start's `until` stops us
        ctx = CallCtx(self, info.name)
        if self.keep_recent_args:
            self.recent.append((info.name, ctx.arg(0), ctx.arg(1), ctx.arg(2), ctx.lr))
        else:
            self.recent.append((info.name, 0, 0, 0, ctx.lr))
        if self.trace_calls:
            self.log(f"  -> {info.name}({', '.join(hex(x) for x in ctx.args(4))}) lr=0x{ctx.lr:08x}")
        try:
            ret = info.fn(ctx)
        except GuestFault as e:
            self.fault = f"{info.name}: {e}"
            uc.emu_stop()
            return
        except Exception as e:  # never let a Python bug kill the emulator silently
            if self.on_trap_error:
                self.on_trap_error(info.name, e)
            else:
                import traceback
                traceback.print_exc()
            ret = 1
        if ret is not None:
            if isinstance(ret, tuple):          # 64-bit result in r0:r1
                uc.reg_write(UC_ARM_REG_R0, ret[0] & 0xFFFFFFFF)
                uc.reg_write(UC_ARM_REG_R1, ret[1] & 0xFFFFFFFF)
            else:
                uc.reg_write(UC_ARM_REG_R0, ret & 0xFFFFFFFF)

    def _on_bad_mem(self, uc, access, address, size, value, _ud):
        pc = uc.reg_read(UC_ARM_REG_PC)
        lr = uc.reg_read(UC_ARM_REG_LR)
        self.fault = f"bad memory access 0x{address:08x} (size {size}, type {access}) at pc=0x{pc:08x} lr=0x{lr:08x}"
        return False

    # --------------------------------------------------------------- calls
    def call(self, fn: int, *args: int, max_insns: int = 0) -> int:
        """Call a guest function (AAPCS) and return R0. Re-entrant."""
        if fn == 0:
            raise GuestFault("call to NULL function pointer")
        uc = self.uc
        saved = uc.context_save()
        sp = uc.reg_read(UC_ARM_REG_SP)
        sp = (sp - 0x40) & ~7  # leave a red zone under the caller's frame
        extra = list(args[4:])
        if extra:
            sp -= 4 * len(extra)
            sp &= ~7
            for i, v in enumerate(extra):
                self.w32(sp + 4 * i, v)
        for i, v in enumerate(args[:4]):
            uc.reg_write(REG_ARGS[i], v & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_LR, self.exit_addr)
        # Start in the right instruction set: bit 0 selects Thumb.
        cpsr = uc.reg_read(UC_ARM_REG_CPSR)
        if fn & 1:
            cpsr |= 0x20
        else:
            cpsr &= ~0x20
        uc.reg_write(UC_ARM_REG_CPSR, cpsr)
        self.depth += 1
        self.fault = None
        try:
            uc.emu_start(fn & ~1 | (fn & 1), self.exit_addr, count=max_insns)
        except UcError as e:
            if not self.fault:
                pc = uc.reg_read(UC_ARM_REG_PC)
                self.fault = f"{e} at pc=0x{pc:08x}"
        finally:
            self.depth -= 1
        ret = uc.reg_read(UC_ARM_REG_R0)
        pc = uc.reg_read(UC_ARM_REG_PC)
        fault = self.fault
        if not fault and pc != self.exit_addr and max_insns:
            fault = f"instruction budget exhausted at pc=0x{pc:08x}"
        uc.context_restore(saved)
        if fault:
            self.fault = None
            raise GuestFault(fault)
        return ret
