"""Disassemble a region of a .mod file: dis.py <mod> <base> <addr> [count] [--thumb]"""
import sys

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

path, base, addr = sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0)
count = int(sys.argv[4]) if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else 40
thumb = "--thumb" in sys.argv
data = open(path, "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
off = addr - base
for ins in md.disasm(data[off:off + count * 4], addr):
    print(f"{ins.address:08x}: {ins.bytes.hex():10s} {ins.mnemonic} {ins.op_str}")
