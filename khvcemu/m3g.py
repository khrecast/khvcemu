"""Minimal M3G (JSR-184) container reader/writer, enough to patch the plain-
text scene scripts Superscape stored inside KH's .m3g files.

File: 12-byte identifier, then sections:
    u8  compression (0 = none, 1 = zlib)
    u32 total section length (including these 9 bytes and the checksum)
    u32 uncompressed data length
    ... data ...
    u32 Adler-32 checksum over everything in the section before it
"""

from __future__ import annotations

import struct
import zlib

IDENT = b"\xabJSR184\xbb\r\n\x1a\n"
SWERVE_IDENT = b"\xbbSWERVE\xab\r\n\x1a\n"   # Superscape's own variant


def read_sections(data: bytes):
    if not (data.startswith(IDENT) or data.startswith(SWERVE_IDENT)):
        raise ValueError("not an M3G file")
    p = len(IDENT)
    out = []
    while p + 9 <= len(data):
        comp = data[p]
        total, unc = struct.unpack_from("<II", data, p + 1)
        body = data[p + 9:p + total - 4]
        out.append((comp, zlib.decompress(body) if comp == 1 else body))
        p += total
    return out


def write_sections(sections, ident: bytes = IDENT) -> bytes:
    out = bytearray(ident)
    for comp, raw in sections:
        body = zlib.compress(raw, 9) if comp == 1 else raw
        head = struct.pack("<BII", comp, 9 + len(body) + 4, len(raw))
        sec = head + body
        out += sec + struct.pack("<I", zlib.adler32(sec) & 0xFFFFFFFF)
    return bytes(out)


def replace_text(data: bytes, old: bytes, new: bytes) -> tuple:
    """Replace `old` with `new` (same length) inside every section.
    Returns (patched_bytes, count)."""
    if len(old) != len(new):
        raise ValueError("replacement must keep the same length")
    secs = read_sections(data)
    count = 0
    patched = []
    for comp, raw in secs:
        n = raw.count(old)
        if n:
            raw = raw.replace(old, new)
            count += n
        patched.append((comp, raw))
    return (write_sections(patched, data[:len(IDENT)]) if count else data), count
