"""Build a macOS app: "Kingdom Hearts Re-Cast.app", zipped, with everything inside.

    python tools/build_mac.py [--arch arm64|x86_64|all] [--game DIR] [--out DIR]

Result: dist/KH-ReCast-macOS-arm64.zip (Apple Silicon) and/or dist/KH-ReCast-macOS-x86_64.zip
(Intel). Unzip, drag the app to Applications, right-click > Open the first time.

It is built on Windows (or anywhere) without a Mac: Python comes from python-build-standalone
(with tkinter), the libraries are downloaded as macOS wheels, ffmpeg is a static macOS build
from osxexperts.net, and the zip is written with the right permissions and symlinks. Every
compiled file in the result is checked to be for the right CPU. It could not be tried on a
Mac here, so treat it as untested until someone has run it.

--game is the folder holding mif/ and mod/ (default: this project folder). The output holds
the game files, so dist/ and build/ are git-ignored.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import plistlib
import re
import shutil
import stat
import struct
import sys
import tarfile
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_installer as bi                                           # noqa: E402

ARCHES = {
    "arm64": dict(triple="aarch64-apple-darwin", wheel_platform="macosx_14_0_arm64", cpu=0x0100000C,
                  ffmpeg="https://www.osxexperts.net/ffmpeg7arm.zip", min_os="11.0"),
    "x86_64": dict(triple="x86_64-apple-darwin", wheel_platform="macosx_14_0_x86_64", cpu=0x01000007,
                   ffmpeg="https://www.osxexperts.net/ffmpeg7intel.zip", min_os="10.15"),
}
APP = "Kingdom Hearts Re-Cast.app"
CPU_NAMES = {0x0100000C: "arm64", 0x01000007: "x86_64"}

LAUNCHER_SH = """#!/bin/bash
# Starts the Kingdom Hearts Re:Cast launcher with the Python that is inside this app.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONPATH="$RES/khvcemu"
export PYTHONDONTWRITEBYTECODE=1
cd "$RES/khvcemu" || exit 1
exec "$RES/python/bin/python3" -m khvcemu.launcher
"""

README_FIRST = """Kingdom Hearts Re:Cast for macOS ({arch})

1. Drag "{app}" into your Applications folder.
2. The first time, macOS will say it cannot verify the developer (the app is not signed
   by Apple). Right-click (or Control-click) the app, choose Open, then Open again.
   If macOS says the app is "damaged", open Terminal and run:
       xattr -dr com.apple.quarantine "/Applications/{app}"
3. Your saves and settings are kept in the folder .khvcemu in your home folder.

Everything the game needs (Python, ffmpeg, the game files) is inside the app.
"""


def macho_cpus(head: bytes):
    """CPU names for a Mach-O file's first bytes (several for a universal binary), else None."""
    if head[:4] == b"\xcf\xfa\xed\xfe" and len(head) >= 8:                    # 64-bit, little endian
        c = struct.unpack_from("<I", head, 4)[0]
        return {CPU_NAMES.get(c, hex(c))}
    if head[:4] == b"\xca\xfe\xba\xbe" and len(head) >= 8:                    # universal (not a Java class)
        n = struct.unpack_from(">I", head, 4)[0]
        if n < 20:
            return {CPU_NAMES.get(struct.unpack_from(">I", head, 8 + 20 * i)[0], "other")
                    for i in range(min(n, (len(head) - 8) // 20))}
    if head[:4] in (b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
        return {"unsupported-macho"}
    return None


class AppZip:
    """Writes the zip with Unix modes and symlinks, and checks every Mach-O file's CPU."""

    def __init__(self, path: str, want_cpu: str):
        self.z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9)
        self.want, self.wrong, self.macho, self.names = want_cpu, [], 0, set()

    def _info(self, name: str, mode: int) -> zipfile.ZipInfo:
        zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        zi.create_system = 3
        zi.external_attr = (mode & 0xFFFF) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        return zi

    def file(self, name: str, data: bytes, mode: int = 0o644):
        if name in self.names:
            return
        self.names.add(name)
        cpus = macho_cpus(data[:8 + 20 * 19])
        if cpus is not None:
            self.macho += 1
            if self.want not in cpus:
                self.wrong.append((name, sorted(cpus)))
            mode |= 0o111
        self.z.writestr(self._info(name, stat.S_IFREG | mode), data)

    def symlink(self, name: str, target: str):
        if name in self.names:
            return
        self.names.add(name)
        zi = self._info(name, stat.S_IFLNK | 0o755)
        zi.compress_type = zipfile.ZIP_STORED
        self.z.writestr(zi, target)

    def tree(self, src: str, prefix: str):
        """Add a folder from disk. Compiled libraries and bin/ files get the executable bit."""
        for d, dirs, files in os.walk(src):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(d, fn)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                exe = fn.endswith((".so", ".dylib")) or fn in ("ffmpeg",)
                with open(full, "rb") as f:
                    self.file(f"{prefix}/{rel}", f.read(), 0o755 if exe else 0o644)

    def close(self):
        self.z.close()


def python_tarball(arch: str) -> str:
    """Download python-build-standalone's 'install_only' CPython (it includes tkinter)."""
    meta = os.path.join(bi.CACHE, f"pbs-{arch}.json")
    if not os.path.isfile(meta):
        ver = re.escape("%d.%d" % sys.version_info[:2])
        req = urllib.request.Request("https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest",
                                     headers={"User-Agent": "khvcemu-build"})
        rel = json.load(urllib.request.urlopen(req))
        pat = re.compile(rf"^cpython-{ver}\.\d+\+\d+-{re.escape(ARCHES[arch]['triple'])}-install_only\.tar\.gz$")
        hit = [a for a in rel["assets"] if pat.match(a["name"])]
        if not hit:
            sys.exit(f"No python-build-standalone {ver} build for {arch} in release {rel['tag_name']}.")
        os.makedirs(bi.CACHE, exist_ok=True)
        json.dump({"name": hit[0]["name"], "url": hit[0]["browser_download_url"]}, open(meta, "w"))
    m = json.load(open(meta))
    return bi.download(m["url"], m["name"])


def icns_bytes() -> bytes:
    """The app icon as .icns (PNG entries at 32, 64, 128 and 256 px)."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    src = pygame.image.load(os.path.join(bi.ROOT, "khvcemu", "assets", "recast_icon.png"))
    entries = b""
    for tag, px in ((b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256)):
        buf = io.BytesIO()
        pygame.image.save(pygame.transform.smoothscale(src, (px, px)), buf, "icon.png")
        data = buf.getvalue()
        entries += tag + struct.pack(">I", 8 + len(data)) + data
    return b"icns" + struct.pack(">I", 8 + len(entries)) + entries


def info_plist(arch: str, version: str) -> bytes:
    return plistlib.dumps({
        "CFBundleName": "Kingdom Hearts Re-Cast", "CFBundleDisplayName": bi.NAME,
        "CFBundleIdentifier": "org.khvcemu.recast", "CFBundleExecutable": "launcher",
        "CFBundleIconFile": "recast", "CFBundlePackageType": "APPL", "CFBundleSignature": "????",
        "CFBundleShortVersionString": version, "CFBundleVersion": version,
        "LSMinimumSystemVersion": ARCHES[arch]["min_os"], "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.games",
    })


def ffmpeg_binary(arch: str) -> bytes:
    z = bi.download(ARCHES[arch]["ffmpeg"], f"ffmpeg-mac-{arch}.zip")
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            if os.path.basename(n) == "ffmpeg" and not n.endswith("/") and "__MACOSX" not in n:
                return zf.read(n)
    sys.exit("No ffmpeg binary found in " + z)


def build(arch: str, game: str, out_dir: str, version: str):
    print(f"=== macOS {arch}")
    stage = os.path.join(bi.BUILD, "mac-" + arch)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    print("1/4 libraries (macOS wheels)")
    site = os.path.join(stage, "site")
    bi.pip_install(site, [ARCHES[arch]["wheel_platform"]])
    bi.trim_site(site)
    print("2/4 khvcemu and the game files")
    proj = os.path.join(stage, "khvcemu")
    bi.build_app(proj, game)
    print("3/4 Python and ffmpeg")
    tarball = python_tarball(arch)
    os.makedirs(out_dir, exist_ok=True)
    zpath = os.path.join(out_dir, f"KH-ReCast-macOS-{arch}.zip")
    az = AppZip(zpath, arch)
    res = f"{APP}/Contents/Resources"
    skip = re.compile(r"(^|/)(__pycache__|include|share)(/|$)|/lib/python[\d.]+/(test|idlelib/idle_test)(/|$)")
    pyver = "%d.%d" % sys.version_info[:2]
    with tarfile.open(tarball) as tf:
        for m in tf:
            name = f"{res}/{m.name}"
            if skip.search(m.name) or m.isdir():
                continue
            if m.issym():
                az.symlink(name, m.linkname)
            elif m.isfile() or m.islnk():
                az.file(name, tf.extractfile(m).read(), m.mode & 0o777 or 0o644)
    az.tree(site, f"{res}/python/lib/python{pyver}/site-packages")
    az.tree(proj, f"{res}/khvcemu")
    az.file(f"{res}/khvcemu/bin/ffmpeg", ffmpeg_binary(arch), 0o755)
    print("4/4 app bundle and zip")
    az.file(f"{APP}/Contents/Info.plist", info_plist(arch, version))
    az.file(f"{APP}/Contents/MacOS/launcher", LAUNCHER_SH.encode(), 0o755)
    az.file(f"{res}/recast.icns", icns_bytes())
    az.file("READ ME FIRST.txt", README_FIRST.format(arch=arch, app=APP).encode())
    az.close()
    if az.wrong:
        print("\nWRONG-CPU FILES (the build is not usable):")
        for n, c in az.wrong[:20]:
            print("  ", n, c)
        sys.exit(1)
    print(f"checked {az.macho} compiled files: all are {arch}")
    print(f"\nBuilt {zpath}  ({os.path.getsize(zpath) / 1e6:.0f} MB)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arch", choices=[*ARCHES, "all"], default="all")
    ap.add_argument("--game", default=bi.ROOT)
    ap.add_argument("--out", default=os.path.join(bi.ROOT, "dist"))
    ap.add_argument("--version", default=bi.project_version())
    a = ap.parse_args()
    game = os.path.abspath(a.game)
    if not (os.path.isdir(os.path.join(game, "mif")) and os.path.isdir(os.path.join(game, "mod"))):
        sys.exit(f"{game} does not contain mif/ and mod/ (the game files).")
    for arch in (list(ARCHES) if a.arch == "all" else [a.arch]):
        build(arch, game, a.out, a.version)


if __name__ == "__main__":
    main()
