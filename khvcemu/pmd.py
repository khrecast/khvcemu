"""CMX ".pmd" (Qualcomm Compact Media Extensions, 'cmid') sound files.

Layout, as found in KH's sound effects:
    "cmid" u32be length, u16be header length, 3 bytes, then header records
    (tag[4] u16be len data): vers, sorc, date, code, wave, poly, tool, ...
    then chunks (tag[4] u32be len data): "trac" holds the event stream.

In the track, `ff f1 <u16be len> <len bytes>` carries wave data. Each wave
block starts with a 7-byte header followed by QCELP-13K packets of 35 bytes
(rate byte 4 = full rate, 20 ms / 160 samples at 8 kHz each). Consecutive
blocks continue the same sound. The packets are wrapped in a QCP (RIFF
'QLCM', RFC 3625) container and decoded with ffmpeg's QCELP decoder.

Tracks without wave data would be synthesised sequences; KH doesn't use
those, so they decode to silence.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from typing import Optional

import numpy as np

from .paths import no_window

QCELP_PACKET = {4: 35, 3: 17, 2: 8, 1: 4, 0: 1}   # rate byte -> packet size


def parse_tracks(data: bytes) -> list:
    if data[:4] != b"cmid":
        raise ValueError("not a CMX file")
    hl = struct.unpack(">H", data[8:10])[0]
    p = 10 + hl
    tracks = []
    while p + 8 <= len(data):
        tag = data[p:p + 4]
        ln = struct.unpack(">I", data[p + 4:p + 8])[0]
        if tag == b"trac":
            tracks.append(data[p + 8:p + 8 + ln])
        p += 8 + ln
    return tracks


def wave_blocks(track: bytes) -> list:
    out = []
    i = track.find(b"\xff\xf1")
    while i >= 0 and i + 4 <= len(track):
        ln = struct.unpack(">H", track[i + 2:i + 4])[0]
        out.append(track[i + 4:i + 4 + ln])
        i = track.find(b"\xff\xf1", i + 4 + ln)
    return out


def qcelp_packets(blocks: list) -> list:
    packets = []
    for b in blocks:
        payload = b[7:]
        i = 0
        while i < len(payload):
            size = QCELP_PACKET.get(payload[i])
            if size is None or i + size > len(payload):
                break
            packets.append(payload[i:i + size])
            i += size
    return packets


def qcp_container(packets: list) -> bytes:
    guid = struct.pack("<IHH8B", 0x5E7F6D41, 0xB115, 0x11D0, 0xBA, 0x91, 0x00, 0x80, 0x5F, 0xB4, 0xB9, 0x7E)
    fmt = struct.pack("<BB", 1, 0) + guid + struct.pack("<H", 2) + b"Qcelp 13K".ljust(80, b"\0")
    fmt += struct.pack("<HHHHH", 13000, 35, 160, 8000, 16)
    fmt += struct.pack("<I", 5) + bytes([34, 4, 16, 3, 7, 2, 3, 1, 0, 0, 0, 0, 0, 0, 0, 0]) + b"\0" * 20
    data = b"".join(packets)
    body = (b"QLCM" + b"fmt " + struct.pack("<I", len(fmt)) + fmt +
            b"vrat" + struct.pack("<III", 8, 1, len(packets)) +
            b"data" + struct.pack("<I", len(data)) + data)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def to_qcp(data: bytes) -> Optional[bytes]:
    packets = []
    for t in parse_tracks(data):
        packets += qcelp_packets(wave_blocks(t))
    return qcp_container(packets) if packets else None


def decode(data: bytes, rate: int, midi_renderer=None, ffmpeg: Optional[str] = None) -> np.ndarray:
    qcp = to_qcp(data)
    if qcp is None:
        return np.zeros(rate // 10, np.int16)
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("PMD sound effects need ffmpeg (QCELP decoder) on PATH")
    r = subprocess.run([ffmpeg, "-v", "error", "-f", "qcp", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                        "-ar", str(rate), "pipe:1"], input=qcp, capture_output=True, timeout=30,
                       **no_window())
    if r.returncode or not r.stdout:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(r.stdout, "<i2").copy()
