"""Check that a folder holds the game files the emulator needs (used by the Android app's first-run screen).

The game is two BREW modules: the game itself (`mif/11839.mif` and `mod/11839/kh.mod`) and its helper extension
(`mif/14957.mif` and `mod/14957/swv21brew.mod`). `problems` names whatever is missing, in words a player can act on.
"""

from __future__ import annotations

import os
from typing import List

REQUIRED = (
    ("mif", "11839.mif"),
    ("mod", "11839", "kh.mod"),
    ("mif", "14957.mif"),
    ("mod", "14957", "swv21brew.mod"),
)


def problems(root: str) -> List[str]:
    """What is missing from the game folder `root` (empty list: it is complete)."""
    if not root or not os.path.isdir(root):
        return ["The folder does not exist."]
    if not os.path.isdir(os.path.join(root, "mif")) or not os.path.isdir(os.path.join(root, "mod")):
        return ["This is not the game folder: it has no mif and mod folders inside."]
    return ["Missing " + "/".join(parts) for parts in REQUIRED if not os.path.isfile(os.path.join(root, *parts))]
