"""BREW resource files: .bar archives and .mif module info files share one
container layout (the MIF is itself a resource file).

    0x00  11 00 01 00 01 00  magic, then u16 record count
    0x08  u32 directory offset   u32 directory length (8-byte records)
    0x10  u32 offset table       u32 entry count (count+1 offsets, last = EOF)
    0x18  u32 data start         u32 data size

Directory records are ranges: {u16 type, u16 first_id, u16 last_index,
u16 first_entry} -> ids first_id..first_id+last_index map to consecutive
entries. Resource type 1 = string, 6 = image, 0x5000 = MIF class records.

Class-ID extraction rules (applet record = 20 bytes, extension export = 8
bytes in a MIF with no applet) follow zeebulator's measurements (GPL-3.0).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"\x11\x00\x01\x00\x01\x00"

RT_STRING = 1
RT_IMAGE = 6


@dataclass
class ResourceFile:
    data: bytes
    entries: list = field(default_factory=list)       # (offset, size)
    ranges: list = field(default_factory=list)        # (type, first_id, last_index, first_entry)

    @classmethod
    def parse(cls, data: bytes) -> "ResourceFile":
        if data[:6] != MAGIC or len(data) < 0x20:
            raise ValueError("not a BREW resource file")
        dir_off, dir_len, tab_off, cnt = struct.unpack_from("<4I", data, 8)
        if cnt > 100000 or tab_off + 4 * (cnt + 1) > len(data):
            raise ValueError("corrupt resource file header")
        offs = [struct.unpack_from("<I", data, tab_off + 4 * i)[0] for i in range(cnt + 1)]
        rf = cls(data)
        for i in range(cnt):
            a, b = offs[i], offs[i + 1]
            if not (0 <= a <= b <= len(data)):
                b = a
            rf.entries.append((a, b - a))
        for i in range(dir_len // 8):
            rf.ranges.append(struct.unpack_from("<4H", data, dir_off + 8 * i))
        return rf

    def entry(self, idx: int) -> bytes:
        a, n = self.entries[idx]
        return self.data[a:a + n]

    def find(self, rtype: int, rid: int):
        """Raw payload for (type, id), or None."""
        for t, first, last, e0 in self.ranges:
            if t == rtype and first <= rid <= first + last:
                idx = e0 + (rid - first)
                if 0 <= idx < len(self.entries):
                    return self.entry(idx)
        return None

    def find_any_type(self, rid: int):
        for t, first, last, e0 in self.ranges:
            if first <= rid <= first + last and t < 0x100:
                return t, self.entry(e0 + (rid - first))
        return None

    def section_payloads(self):
        return [self.entry(i) for i in range(len(self.entries))]


def strip_mime(payload: bytes):
    """Image/binary resources carry `u16 hdrlen, "mime/type\\0"` first."""
    if len(payload) >= 4:
        hl = struct.unpack_from("<H", payload, 0)[0]
        if 4 <= hl <= 64 and hl <= len(payload) and payload[hl - 1:hl] == b"\0":
            mime = payload[2:hl - 1]
            if all(32 <= ch < 127 for ch in mime):
                return mime.decode(), payload[hl:]
    return None, payload


def decode_string(payload: bytes) -> str:
    if payload[:2] == b"\xff\xfe":
        return payload[2:].decode("utf-16-le", "replace").split("\0")[0]
    return payload.decode("latin-1").split("\0")[0]


def mif_applet_classes(data: bytes) -> list:
    try:
        rf = ResourceFile.parse(data)
    except ValueError:
        return []
    out = []
    for p in rf.section_payloads():
        if len(p) == 20:
            cls, w1, _w2, w3 = struct.unpack_from("<4I", p, 0)
            if cls and w1 == 0 and w3 == 0:
                out.append(cls)
    return out


def mif_extension_classes(data: bytes) -> list:
    """Classes a MIF *exports* (only MIFs that declare no applet export)."""
    if mif_applet_classes(data):
        return []
    rf = ResourceFile.parse(data)
    out = []
    for p in rf.section_payloads():
        if len(p) == 8:
            cls, flags = struct.unpack("<2I", p)
            if flags == 0 and 0x01000000 <= cls <= 0x01FFFFFF and cls not in out:
                out.append(cls)
    return out


def mif_strings(data: bytes) -> list:
    rf = ResourceFile.parse(data)
    return [decode_string(rf.entry(e0 + k))
            for t, first, last, e0 in rf.ranges if t == RT_STRING
            for k in range(last + 1)]
