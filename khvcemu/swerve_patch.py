"""Speed patches for the game's 3D engine (swv21brew.mod), applied to the module's image in guest memory only:
no game file is modified or stored. Each patch is independent and can be switched off (`--no-speed-patch`, the
launcher's Speed enhancements window, under Options); every patch keeps the original code in place and falls back to it, and only touches a
module whose code is byte for byte the known one.

  span    a tighter version of the per-pixel span fill (about half of all guest instructions in some scenes): the
          commonest span kind (alpha blend mode 0x40, color write on, no alpha buffer) in about half the
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
_SAME = ("No reason in normal play: the picture is identical (checked pixel for pixel) and what your saves "
         "hold is not changed. Turn it off only to see whether it is behind a problem you notice, or to compare speed.")
# name: (label in the launcher, what it does, when you might turn it off)
INFO = {
    "span": ("Faster blended fill",
             "Draws see-through and blended surfaces (water, glows, fades) with a tighter loop. The biggest help "
             "where much of the screen is blended, such as the Island's opening scene.", _SAME),
    "matinv": ("Matrix cache",
               "The 3D engine inverts the same 4x4 matrices hundreds of times a frame. This remembers the answers "
               "(exactly what the engine would work out) in about 580 KB of the emulated phone's memory. Helps "
               "most while walking around.",
               _SAME + " Save states made with it on carry its memory, so they can be a little larger.")
}
LABELS = {n: INFO[n][0] for n in INFO}
HINTS = {n: f"{INFO[n][1]}\n\nWhy turn it off? {INFO[n][2]}" for n in INFO}


def _original_code(cpu, base: int, p: dict) -> bytes:
    return cpu.read(base + p["function_offset"], p["original_length"])


def _is_original(code: bytes, p: dict) -> bool:
    return len(code) == p["original_length"] and hashlib.sha256(code).hexdigest() == p["original_sha256"]


def _unpatched_view(code: bytes, p: dict) -> bytes:
    """The checked range with every entry stub replaced by the original first instruction it covers."""
    out = bytearray(code)
    for s in p["stubs"]:
        at = s["offset"] - p["function_offset"]
        out[at:at + 4] = s["original_first"]
    return bytes(out)


def state(cpu, base: int, name: str) -> str:
    """What the code a patch replaces is at `base`: "original" (the known code), "patched" (the known code with this
    patch fully in place) or "" (anything else, including no module there)."""
    p = PATCHES[name]
    current = _original_code(cpu, base, p)
    if _is_original(current, p):
        return "original"
    in_place = all(current[s["offset"] - p["function_offset"]:][:4] == s["stub"] for s in p["stubs"])
    if (in_place and _is_original(_unpatched_view(current, p), p)
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
    for s in p["stubs"]:
        cpu.write(base + s["offset"], s["stub"])
    return True


def remove(cpu, base: int, name: str) -> bool:
    """Undo one patch (a save state made with it restores it into a run that asked for the original code)."""
    if state(cpu, base, name) != "patched":
        return False
    p = PATCHES[name]
    for s in p["stubs"]:
        cpu.write(base + s["offset"], s["original_first"])
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
