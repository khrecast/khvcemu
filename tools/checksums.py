"""Write SHA-256 checksums for the installers in dist/.

    python tools/checksums.py [--dir DIR]

Creates SHA256SUMS.txt in the standard format, so anyone can check a download with
`sha256sum -c SHA256SUMS.txt` (Linux, macOS: `shasum -a 256 -c`) or, on Windows,
`Get-FileHash <file>` in PowerShell and compare by eye. Publish the file (and the hashes on
the web page) next to the downloads: the installers are not code-signed, so this is how a
visitor can tell the file they got is the one you built.

Run it after the final build; changing any installer changes its hash.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX, SUFFIXES = "KH-ReCast-", (".exe", ".zip", ".run")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sums(folder: str) -> list:
    """[(hash, file name, size)] for every installer in the folder, sorted by name."""
    out = []
    for name in sorted(os.listdir(folder)):
        if name.startswith(PREFIX) and name.endswith(SUFFIXES):
            path = os.path.join(folder, name)
            out.append((sha256(path), name, os.path.getsize(path)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(ROOT, "dist"))
    a = ap.parse_args()
    if not os.path.isdir(a.dir):
        sys.exit(f"{a.dir} does not exist; build the installers first.")
    found = sums(a.dir)
    if not found:
        sys.exit(f"No {PREFIX}* installers in {a.dir}.")
    out = os.path.join(a.dir, "SHA256SUMS.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for digest, name, _ in found:
            f.write(f"{digest}  {name}\n")       # two spaces: what sha256sum -c expects
    for digest, name, size in found:
        print(f"{digest}  {name}  ({size / 1e6:.0f} MB)")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
