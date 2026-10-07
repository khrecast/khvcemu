"""The 3D engine speed patches (khvcemu/swerve_patch.py) must produce exactly what the original code does. Random
inputs are run through the original and the patched module in two bare Unicorn instances and every byte of the
buffers is compared. Needs the game's swv21brew.mod (KH_DUMP or the repository folder); skipped without it."""
import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unicorn  # noqa: E402
from unicorn import UC_ARCH_ARM, UC_MODE_ARM, UC_PROT_ALL, Uc  # noqa: E402
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R4,  # noqa: E402
                               UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
                               UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP)

from khvcemu import swerve_patch  # noqa: E402

BASE = 0x01000000
SPAN = swerve_patch.PATCHES["span"]
MATINV = swerve_patch.PATCHES["matinv"]
SPAN_FUNC = BASE + SPAN["function_offset"]
INV_FUNC = BASE + MATINV["function_offset"]
SENTINEL = 0x01F00000
STACK = 0x02000000
DATA = 0x03000000
STRUCT, FB, DEPTH, ALPHA = DATA, DATA + 0x1000, DATA + 0x3000, DATA + 0x5000
DATA_SIZE = 0x8000
CALLEE_SAVED = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                UC_ARM_REG_R10, UC_ARM_REG_R11)


def find_module():
    for root in (os.environ.get("KH_DUMP"), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        if root:
            p = os.path.join(root, "mod", "14957", "swv21brew.mod")
            if os.path.isfile(p):
                return p
    return None


class FakeCpu:
    """The two methods swerve_patch uses, on a bare Unicorn."""

    def __init__(self, uc):
        self.uc = uc

    def read(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def write(self, a, data):
        self.uc.mem_write(a, data)


def make(image, patches=()):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.mem_map(BASE, 0x1000000, UC_PROT_ALL)        # the module's slot, the patches' code and the cache table
    uc.mem_map(STACK, 0x10000, UC_PROT_ALL)
    uc.mem_map(DATA, DATA_SIZE, UC_PROT_ALL)
    uc.mem_write(BASE, image)
    applied = [swerve_patch.apply(FakeCpu(uc), BASE, n) for n in patches]
    return uc, applied


def call(uc, entry, memory, r0, r1=0):
    """Run one guest function; returns (registers worth comparing, the data memory afterwards)."""
    uc.mem_write(DATA, memory)
    uc.reg_write(UC_ARM_REG_CPSR, 0xD0)
    uc.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
    uc.reg_write(UC_ARM_REG_R0, r0)
    uc.reg_write(UC_ARM_REG_R0 + 1, r1)
    for i, reg in enumerate(CALLEE_SAVED):
        uc.reg_write(reg, 0x11110000 + i)
    uc.reg_write(UC_ARM_REG_LR, SENTINEL)
    uc.emu_start(entry, SENTINEL, count=2_000_000)
    regs = tuple(uc.reg_read(r) for r in (UC_ARM_REG_R0,) + CALLEE_SAVED + (UC_ARM_REG_SP,))
    return regs, bytes(uc.mem_read(DATA, DATA_SIZE))


def count_instructions(uc):
    total = [0]

    def block(_uc, _addr, size, _ud):
        total[0] += size // 4
    uc.hook_add(unicorn.UC_HOOK_BLOCK, block)
    return total


def random_span(rnd, fast):
    """One span: the state structure plus the contents of the buffers. `fast` makes it eligible for the fast path."""
    mem = bytearray(DATA_SIZE)
    for i in range(0x1000, DATA_SIZE):
        mem[i] = rnd.randrange(256)
    s = {}
    x0 = rnd.randrange(0, 60)
    width = rnd.choice((1, 2, 3, 7, 29, 64, 100, 0, -3))
    s[0x04] = rnd.randrange(0, 200)
    s[0x08] = FB
    s[0x0C] = DEPTH
    s[0x10] = x0
    s[0xDC] = x0 + width
    s[0x1C] = rnd.randrange(-0x2000, 0x20000) << 12 | rnd.randrange(4096)
    s[0x4C] = rnd.randrange(-0x3000, 0x3000) << rnd.choice((0, 4, 8))
    s[0x38] = rnd.randrange(-0x6000, 0x16000)
    s[0x3C] = rnd.randrange(-0x6000, 0x1B000)
    s[0x40] = rnd.randrange(-0x6000, 0x16000)
    s[0x44] = rnd.choice((rnd.randrange(-0x800, 0x11000), rnd.randrange(0, 0xFF00), 0xFF00, 0xFFFF, 0x20000))
    for off in (0x68, 0x6C, 0x70):
        s[off] = rnd.randrange(-0x500, 0x500)
    s[0x74] = rnd.choice((0, rnd.randrange(-0x500, 0x500)))
    flags = rnd.randrange(0, 0x1000)
    if fast:
        flags |= 1
        flags = (flags & ~0x60) | rnd.choice((0, 0x20, 0x40, 0x60))
    s[0x258] = flags
    s[0x25C] = rnd.choice((0, 0, 0, 1, 5, 0x80, -2))
    s[0x260] = 0 if fast and rnd.random() < 0.7 else (ALPHA if rnd.random() < 0.6 else 0)
    if fast and s[0x260]:
        s[0x258] &= ~0x800                       # an alpha buffer that is not in use still takes the fast path
    s[0x264] = rnd.randrange(0, 40)
    s[0x268] = 0x40 if fast else rnd.choice((0x40, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0))
    for off, v in s.items():
        struct.pack_into("<i" if v < 0 else "<I", mem, off, v)
    # depth buffer near the interpolated depth so both outcomes of the depth test happen
    z = s[0x1C] >> 12
    for i in range(0, 0x400, 2):
        struct.pack_into("<H", mem, 0x3000 + i, (z + rnd.randrange(-300, 300)) & 0xFFFF)
    return bytes(mem)


def random_matrix(rnd):
    """17 words: a 4x4 float matrix (all sorts: identity-like, general, singular, zero) and the flag word."""
    kind = rnd.choice(("identity", "near", "random", "random", "singular", "zero", "scale", "translate"))
    m = [1.0 if i % 5 == 0 else 0.0 for i in range(16)]
    if kind == "near":
        m = [v + rnd.choice((0.0, 0.0, rnd.uniform(-0.5, 0.5))) for v in m]
    elif kind == "random":
        m = [rnd.uniform(-10, 10) for _ in range(16)]
    elif kind == "singular":
        m = [rnd.uniform(-5, 5) for _ in range(16)]
        m[4:8] = m[0:4]
    elif kind == "zero":
        m = [0.0] * 16
    elif kind == "scale":
        m = [rnd.uniform(0.1, 3) if i % 5 == 0 else 0.0 for i in range(16)]
    elif kind == "translate":
        m[3], m[7], m[11] = rnd.uniform(-100, 100), rnd.uniform(-100, 100), rnd.uniform(-100, 100)
    flag = rnd.choice((0x3, 0x7, 0x13, 0xF, 0x13, 0x3, 0x0, 0x1, 0x20, 0x3F))
    return struct.pack("<16fI", *m, flag)


@unittest.skipUnless(find_module(), "swv21brew.mod not found (set KH_DUMP)")
class SwervePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(find_module(), "rb") as f:
            cls.image = f.read()

    def test_the_whole_module_is_the_known_one(self):
        self.assertTrue(swerve_patch.module_is_known(self.image))
        self.assertFalse(swerve_patch.module_is_known(self.image[:-1] + b"\x01"))

    def test_only_the_known_code_is_patched(self):
        for name, p in swerve_patch.PATCHES.items():
            uc, applied = make(self.image, (name,))
            self.assertEqual(applied, [True])
            at = BASE + p["function_offset"]
            self.assertEqual(bytes(uc.mem_read(at, 4)), p["entry_stub"])
            self.assertTrue(swerve_patch.apply(FakeCpu(uc), BASE, name), "applying twice is harmless")
            self.assertEqual(swerve_patch.state(FakeCpu(uc), BASE, name), "patched")
            self.assertTrue(swerve_patch.remove(FakeCpu(uc), BASE, name))
            self.assertEqual(bytes(uc.mem_read(at, p["original_length"])),
                             self.image[p["function_offset"]:p["function_offset"] + p["original_length"]])
            self.assertEqual(swerve_patch.state(FakeCpu(uc), BASE, name), "original")
            other = bytearray(self.image)
            other[p["function_offset"] + 40] ^= 1                # any other build of the module: leave it alone
            uc2, applied = make(bytes(other), (name,))
            self.assertEqual(applied, [False])
            self.assertEqual(bytes(uc2.mem_read(at, 4)), bytes(other[p["function_offset"]:p["function_offset"] + 4]))

    def test_a_loaded_state_gets_the_patches_even_in_a_fresh_run(self):
        """A state restores the module's memory and the table of loaded modules, but the new run never loaded the
        module itself: the emulator must find it by scanning the slots, and honour --no-speed-patch both ways."""
        from khvcemu.cpu import EXT_MODULE_BASE, EXT_MODULE_STRIDE
        from khvcemu.runtime import Emulator

        class Stand:
            _swerve_base = 0
            log = staticmethod(lambda m: None)
            _loaded_ext = {"mod/14957/swv21brew.mod": 1}
            _next_ext_base = EXT_MODULE_BASE + 2 * EXT_MODULE_STRIDE      # the engine sits in the second slot

        base = EXT_MODULE_BASE + EXT_MODULE_STRIDE
        for was in ((), ("span",), swerve_patch.NAMES):
            for wanted in (swerve_patch.NAMES, ("matinv",), ()):
                uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
                uc.mem_map(EXT_MODULE_BASE, 0x1000000, UC_PROT_ALL)
                uc.mem_write(base, self.image)
                cpu = FakeCpu(uc)
                for n in was:
                    self.assertTrue(swerve_patch.apply(cpu, base, n))
                emu = Stand()
                emu.speed_patches, emu.cpu = set(wanted), cpu
                Emulator.reapply_speed_patch(emu)
                self.assertEqual(emu._swerve_base, base)
                for n in swerve_patch.NAMES:
                    self.assertEqual(swerve_patch.state(cpu, base, n), "patched" if n in wanted else "original")
        other = Stand()                                        # no engine loaded: nothing to do, nothing breaks
        other._loaded_ext = {}
        other.speed_patches, other.cpu = set(swerve_patch.NAMES), cpu
        Emulator.reapply_speed_patch(other)
        self.assertEqual(other._swerve_base, 0)

    def test_span_fill_identical_results_on_random_spans(self):
        rnd = random.Random(20261006)
        orig, _ = make(self.image)
        fast, applied = make(self.image, ("span",))
        self.assertEqual(applied, [True])
        for n in range(3000):
            mem = random_span(rnd, fast=n % 4 != 3)
            r_orig, m_orig = call(orig, SPAN_FUNC, mem, STRUCT)
            r_fast, m_fast = call(fast, SPAN_FUNC, mem, STRUCT)
            self.assertEqual(r_orig, r_fast, f"registers differ in case {n}")
            if m_orig != m_fast:
                first = next(i for i in range(len(m_orig)) if m_orig[i] != m_fast[i])
                self.fail(f"case {n}: memory differs at +{first:#x} (struct {mem[:0x270].hex()[:80]}...)")

    def test_span_fill_does_less_work(self):
        """The point of the patch: fewer guest instructions for a typical blended, depth tested span."""
        rnd = random.Random(7)
        orig, _ = make(self.image)
        fast, _ = make(self.image, ("span",))
        counts = []
        for uc in (orig, fast):
            total = count_instructions(uc)
            for _ in range(40):
                mem = bytearray(random_span(rnd, True))
                struct.pack_into("<I", mem, 0xDC, struct.unpack_from("<I", mem, 0x10)[0] + 64)
                struct.pack_into("<I", mem, 0x258, 0x869)
                struct.pack_into("<I", mem, 0x260, 0)
                struct.pack_into("<I", mem, 0x25C, 0)
                struct.pack_into("<I", mem, 0x44, 0x4000)         # translucent, never opaque
                struct.pack_into("<i", mem, 0x74, 0)
                call(uc, SPAN_FUNC, bytes(mem), STRUCT)
            counts.append(total[0])
            rnd.seed(7)
        self.assertLess(counts[1], counts[0] * 0.7, f"original {counts[0]} fast {counts[1]} instructions")

    def test_matrix_inversion_cache_gives_the_same_answers(self):
        """Hundreds of calls drawn from a small pool of matrices (so there are hits, misses and slot collisions);
        every result, return value and byte of memory must equal the original function's."""
        rnd = random.Random(99)
        pool = [random_matrix(rnd) for _ in range(150)]
        orig, _ = make(self.image)
        cached, applied = make(self.image, ("matinv",))
        self.assertEqual(applied, [True])
        for n in range(1500):
            m = rnd.choice(pool) if rnd.random() < 0.85 else random_matrix(rnd)
            mem = bytes(0x100) + m + bytes(DATA_SIZE - 0x100 - len(m))
            r_orig, m_orig = call(orig, INV_FUNC, mem, DATA + 0x100)
            r_fast, m_fast = call(cached, INV_FUNC, mem, DATA + 0x100)
            self.assertEqual(r_orig, r_fast, f"registers differ in call {n}")
            self.assertEqual(m_orig, m_fast, f"memory differs in call {n}")

    def test_the_cache_table_is_where_the_code_says_and_removal_clears_it_all(self):
        """A review found the table once started a little below the offset the metadata named, so removing the patch
        left half a slot behind. The code's table pointer and the metadata must agree, and remove() must clear it all."""
        p = MATINV
        self.assertEqual(p["table_offset"], p["blob_offset"] + len(p["blob"]))
        rnd = random.Random(3)
        uc, _ = make(self.image, ("matinv",))
        orig, _ = make(self.image)
        for _ in range(300):                                    # fill many slots
            m = random_matrix(rnd)
            call(uc, INV_FUNC, bytes(0x100) + m + bytes(DATA_SIZE - 0x100 - len(m)), DATA + 0x100)
        table = bytes(uc.mem_read(BASE + p["table_offset"], p["table_size"]))
        self.assertTrue(any(table))
        self.assertFalse(any(uc.mem_read(BASE + p["table_offset"] + p["table_size"], 64)),
                         "nothing is written past the end of the table")
        before = bytes(uc.mem_read(BASE + p["blob_offset"] + len(p["blob"]), 0x40))
        self.assertEqual(before, table[:0x40])
        self.assertTrue(swerve_patch.remove(FakeCpu(uc), BASE, "matinv"))
        self.assertFalse(any(uc.mem_read(BASE + p["blob_offset"], p["table_offset"] - p["blob_offset"] + p["table_size"])),
                         "code and table are all zero again")
        self.assertTrue(swerve_patch.apply(FakeCpu(uc), BASE, "matinv"))
        for n in range(200):                                    # a patch put back after removal still answers right
            m = random_matrix(rnd)
            mem = bytes(0x100) + m + bytes(DATA_SIZE - 0x100 - len(m))
            self.assertEqual(call(uc, INV_FUNC, mem, DATA + 0x100), call(orig, INV_FUNC, mem, DATA + 0x100), n)

    def test_matrix_inversion_cache_saves_work_on_repeats(self):
        rnd = random.Random(5)
        mats = [struct.pack("<16fI", *[rnd.uniform(-3, 3) for _ in range(16)], 0x13) for _ in range(20)]
        counts = []
        for patches in ((), ("matinv",)):
            uc, _ = make(self.image, patches)
            total = count_instructions(uc)
            for _ in range(5):
                for m in mats:
                    call(uc, INV_FUNC, bytes(0x100) + m + bytes(DATA_SIZE - 0x100 - len(m)), DATA + 0x100)
            counts.append(total[0])
        self.assertLess(counts[1], counts[0] * 0.3, f"original {counts[0]} cached {counts[1]} instructions")


class SpeedPatchOptionTests(unittest.TestCase):
    """The launcher's Options tab hands the switches to the game as --no-speed-patch (no game files needed)."""

    def test_the_launcher_passes_only_what_is_switched_off(self):
        from khvcemu import launcher
        cmd = launcher.build_command("dump", {})
        self.assertNotIn("--no-speed-patch", cmd)
        cmd = launcher.build_command("dump", {"speed_patches_off": ["matinv"]})
        self.assertEqual(cmd[cmd.index("--no-speed-patch") + 1], "matinv")
        cmd = launcher.build_command("dump", {"speed_patches_off": ["matinv", "span", "bogus"]})
        self.assertEqual(cmd[cmd.index("--no-speed-patch") + 1], "span,matinv")      # known names, in a fixed order
        self.assertEqual(launcher.OPTION_DEFAULTS["speed_patches_off"], [])

    def test_every_patch_has_a_label_and_a_hint(self):
        for name in swerve_patch.NAMES:
            self.assertTrue(swerve_patch.LABELS[name] and swerve_patch.HINTS[name])


if __name__ == "__main__":
    unittest.main()
