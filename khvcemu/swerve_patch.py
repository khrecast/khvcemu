"""Speed patches for the game's 3D engine (swv21brew.mod), applied to the module's image in guest memory only:
no game file is modified or stored. Each patch is independent and can be switched off (`--no-speed-patch`, the
launcher's Options tab); every patch keeps the original code in place and falls back to it, and only touches a
module whose code is byte for byte the known one.

  span    a tighter version of the per-pixel span fill (about half of all guest instructions in some scenes): the
          commonest span kind (alpha blend mode 0x40, colour write on, no alpha buffer) in about half the
          instructions, drawing exactly the same pixels.
  matinv  a memo cache in front of the engine's 4x4 matrix inversion, which runs hundreds of times a frame on a few
          hundred different matrices (about a fifth of all instructions in a walking scene). The key is all 17
          input words, so a hit returns exactly what the original would have computed.

The machine code is made by tools/gen_swerve_patch.py and checked against the original code with
tests/test_swerve_patch.py.
"""

from __future__ import annotations

import hashlib

from . import _swerve_blob as blob

PATCHES = blob.PATCHES
NAMES = tuple(PATCHES)
LABELS = {"span": "Faster 3D fill", "matinv": "Matrix cache"}
HINTS = {"span": "The 3D engine fills each row of a polygon with a tighter loop. Same picture, about a tenth to a quarter faster in scenes with a lot on screen.",
         "matinv": "The 3D engine inverts the same 4x4 matrices hundreds of times a frame; this remembers the answers. Same picture, faster when you walk around."}


def _original_code(cpu, base: int, p: dict) -> bytes:
    return cpu.read(base + p["function_offset"], p["original_length"])


def _is_original(code: bytes, p: dict) -> bool:
    return len(code) == p["original_length"] and hashlib.sha256(code).hexdigest() == p["original_sha256"]


def state(cpu, base: int, name: str) -> str:
    """What the code a patch replaces is at `base`: "original" (the known code), "patched" (the known code with this
    patch fully in place) or "" (anything else, including no module there)."""
    p = PATCHES[name]
    current = _original_code(cpu, base, p)
    if _is_original(current, p):
        return "original"
    if (current[:4] == p["entry_stub"] and _is_original(p["original_first"] + current[4:], p)
            and cpu.read(base + p["blob_offset"], len(p["blob"])) == p["blob"]):
        return "patched"
    return ""


def apply(cpu, base: int, name: str) -> bool:
    """Put one patch into the module loaded at `base`. Returns True when it is in place afterwards. Calling it again
    (for instance after a save state was loaded) is harmless. The places for the new code (2 MiB into the module's
    4 MiB slot, which the module itself does not use) must be empty."""
    found = state(cpu, base, name)
    if found == "patched":
        return True
    p = PATCHES[name]
    at = base + p["blob_offset"]
    if found != "original" or any(cpu.read(at, len(p["blob"]))):
        return False
    if p["table_size"] and any(cpu.read(base + p["table_offset"], p["table_size"])):
        return False
    cpu.write(at, p["blob"])
    cpu.write(base + p["function_offset"], p["entry_stub"])
    return True


def remove(cpu, base: int, name: str) -> bool:
    """Undo one patch (a save state made with it restores it into a run that asked for the original code)."""
    if state(cpu, base, name) != "patched":
        return False
    p = PATCHES[name]
    cpu.write(base + p["function_offset"], p["original_first"])
    cpu.write(base + p["blob_offset"], bytes(len(p["blob"])))
    if p["table_size"]:
        cpu.write(base + p["table_offset"], bytes(p["table_size"]))
    return True


def module_is_known(image: bytes) -> bool:
    """True for the swv21brew.mod these patches were made for (the whole file, checked when it is loaded)."""
    return hashlib.sha256(image).hexdigest() == blob.MODULE_SHA256


def find_module(cpu, bases) -> int:
    """The load address among `bases` where the engine's code is (patched or not), or 0."""
    for base in bases:
        if any(state(cpu, base, n) for n in NAMES):
            return base
    return 0
