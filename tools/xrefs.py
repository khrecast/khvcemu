"""Find code references to strings in a ROPI .mod (ldr rX,[pc,#n] ; add rX,pc,rX).

usage: xrefs.py <mod> <base> [substring ...]
"""
import re
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

path, base = sys.argv[1], int(sys.argv[2], 0)
needles = sys.argv[3:]
data = open(path, "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.skipdata = True
ins = list(md.disasm(data, base))
lit = {}
refs = []
for i, x in enumerate(ins):
    m = re.match(r"(r\d+|sb|sl|fp|ip|lr), \[pc, #(-?0x[0-9a-f]+|-?\d+)\]", x.op_str)
    if x.mnemonic == "ldr" and m:
        reg, off = m.group(1), int(m.group(2), 0)
        a = x.address + 8 + off
        if base <= a < base + len(data) - 3:
            lit[reg] = (x.address, struct.unpack_from("<I", data, a - base)[0])
    m2 = re.match(r"(\w+), pc, (\w+)$", x.op_str)
    if x.mnemonic == "add" and m2 and m2.group(2) in lit:
        la, val = lit[m2.group(2)]
        tgt = (x.address + 8 + val) & 0xFFFFFFFF
        if base <= tgt < base + len(data):
            off = tgt - base
            end = data.find(b"\0", off)
            s = data[off:end] if 0 <= end - off < 80 else b""
            refs.append((x.address, tgt, s))
for a, t, s in refs:
    txt = s.decode("latin-1", "replace")
    if not needles or any(n in txt for n in needles):
        print(f"{a:08x} -> {t:08x} {txt!r}")
