"""Build a Linux installer: one self-extracting file with everything inside.

    python tools/build_linux.py [--arch x86_64|aarch64|all] [--game DIR] [--out DIR]

Result: dist/KH-ReCast-Linux-x86_64.run and/or dist/KH-ReCast-Linux-aarch64.run. Run it with
`sh KH-ReCast-Linux-x86_64.run`: it installs for the current user only (no root) under
~/.local/share/khvcemu, adds an entry to the applications menu, and can uninstall itself
(`sh KH-ReCast-Linux-x86_64.run --uninstall`).

Built on any OS (it is made on Windows): Python is python-build-standalone (with tkinter),
the libraries are manylinux wheels, ffmpeg is a static Linux build, and the payload is a tar
written with the right permissions and symlinks. Every compiled file is checked to be for the
right CPU. Needs a glibc 2.28 or newer Linux (Ubuntu 20.04, Debian 10, Fedora 29 or later)
with an X11 or Wayland desktop; musl systems such as Alpine are not supported.

--game is the folder holding mif/ and mod/ (default: this project folder). The output holds
the game files, so dist/ and build/ are git-ignored.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import stat
import struct
import sys
import tarfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_installer as bi                                           # noqa: E402

ARCHES = {
    "x86_64": dict(triple="x86_64-unknown-linux-gnu", machine=0x3E,
                   ffmpeg="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"),
    "aarch64": dict(triple="aarch64-unknown-linux-gnu", machine=0xB7,
                    ffmpeg="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"),
}
# wheels are tagged with older "manylinux" names; list every one this glibc generation accepts
MANYLINUX = ("manylinux_2_28", "manylinux_2_27", "manylinux_2_17", "manylinux2014", "manylinux_2_12",
             "manylinux2010", "manylinux_2_5", "manylinux1", "linux")

LAUNCH_SH = """#!/bin/sh
# Starts the Kingdom Hearts Re:Cast launcher with the Python that is installed next to this file.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
export PYTHONPATH="$DIR/khvcemu"
cd "$DIR/khvcemu" || exit 1
exec "$DIR/python/bin/python3" -m khvcemu.launcher "$@"
"""

UNINSTALL_SH = """#!/bin/sh
# Removes Kingdom Hearts Re:Cast. Your saves and settings (in ~/.khvcemu) are kept.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$HOME" 2>/dev/null || cd /            # do not stand inside the folder that is about to be deleted
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
[ -f "$DIR/.khvcemu-install" ] || { echo "This is not a Kingdom Hearts Re:Cast install folder." >&2; exit 1; }
rm -f "$APPS/khvcemu.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1
rm -rf "$DIR"
echo "Kingdom Hearts Re:Cast was removed. Your saves and settings in ~/.khvcemu were kept."
"""

INSTALLER_HEAD = r"""#!/bin/sh
# Kingdom Hearts Re:Cast - self-extracting installer for Linux (__ARCH__), version __VERSION__.
# Installs for the current user only (no root). Options:
#   --dir PATH     install somewhere else (default: ~/.local/share/khvcemu)
#   --yes          do not ask questions
#   --no-launch    do not offer to start it afterwards
#   --uninstall    remove an existing install
set -e
NAME="Kingdom Hearts Re:Cast"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/khvcemu"
APPS="$DATA/applications"
YES=0; LAUNCH=1; UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dir) DEST="$2"; shift ;;
        --yes|-y) YES=1 ;;
        --no-launch) LAUNCH=0 ;;
        --uninstall) UNINSTALL=1 ;;
        --help|-h) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

if [ "$UNINSTALL" = 1 ]; then
    [ -f "$DEST/uninstall.sh" ] || { echo "No install found in $DEST" >&2; exit 1; }
    exec sh "$DEST/uninstall.sh"
fi

if [ "$(uname -m)" != "__ARCH__" ]; then
    echo "This installer is for __ARCH__ computers, but this one is $(uname -m)." >&2; exit 1
fi
if ldd --version 2>&1 | grep -qi musl; then
    echo "This system uses musl libc (for example Alpine). The installer needs a glibc-based Linux." >&2; exit 1
fi
if [ "$YES" = 0 ] && [ -t 0 ]; then
    printf "Install %s into %s? [Y/n] " "$NAME" "$DEST"
    read -r ans
    case "$ans" in n|N|no|No) echo "Cancelled."; exit 0 ;; esac
fi

if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
    if [ -f "$DEST/.khvcemu-install" ]; then
        echo "Replacing the existing install in $DEST ..."
        rm -rf "$DEST"
    else
        echo "$DEST already exists and is not a $NAME install, so it was left alone." >&2; exit 1
    fi
fi
mkdir -p "$DEST" "$APPS"
echo "Installing $NAME (this takes a minute) ..."
SKIP=$(awk '/^__ARCHIVE_BELOW__$/ { print NR + 1; exit }' "$0")
tail -n +"$SKIP" "$0" | tar xzf - -C "$DEST"

cat > "$APPS/khvcemu.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$NAME
Comment=The 2005 Verizon V CAST Kingdom Hearts game, on your computer
Exec="$DEST/launch.sh"
Icon=$DEST/khvcemu/khvcemu/assets/recast_icon.png
Terminal=false
Categories=Game;
StartupNotify=true
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
echo "Installed. Find \"$NAME\" in your applications menu, or run: $DEST/launch.sh"
echo "To remove it later: sh \"$0\" --uninstall   (or run $DEST/uninstall.sh)"

if [ "$LAUNCH" = 1 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ -t 0 ] && [ "$YES" = 0 ]; then
    printf "Start it now? [Y/n] "
    read -r ans
    case "$ans" in n|N|no|No) ;; *) nohup "$DEST/launch.sh" >/dev/null 2>&1 & ;; esac
fi
exit 0
__ARCHIVE_BELOW__
"""


def elf_machine(head: bytes):
    """The CPU code of an ELF file (0x3E x86-64, 0xB7 aarch64), or None if it isn't ELF."""
    if head[:4] == b"\x7fELF" and len(head) >= 20:
        return struct.unpack_from("<H", head, 18)[0]
    return None


class Payload:
    """A gzip'd tar written with Unix modes and symlinks; checks every ELF file's CPU."""

    def __init__(self, path: str, want_machine: int):
        self.t = tarfile.open(path, "w:gz", compresslevel=9, format=tarfile.GNU_FORMAT)
        self.want, self.wrong, self.elf, self.names = want_machine, [], 0, set()

    def file(self, name: str, data: bytes, mode: int = 0o644):
        if name in self.names:
            return
        self.names.add(name)
        m = elf_machine(data[:32])
        if m is not None:
            self.elf += 1
            if m != self.want:
                self.wrong.append((name, hex(m)))
            mode |= 0o111
        ti = tarfile.TarInfo(name)
        ti.size, ti.mode, ti.mtime = len(data), mode, 1767225600
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        self.t.addfile(ti, io.BytesIO(data))

    def symlink(self, name: str, target: str):
        if name in self.names:
            return
        self.names.add(name)
        ti = tarfile.TarInfo(name)
        ti.type, ti.linkname, ti.mode, ti.mtime = tarfile.SYMTYPE, target, 0o777, 1767225600
        self.t.addfile(ti)

    def tree(self, src: str, prefix: str):
        for d, dirs, files in os.walk(src):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(d, fn)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                exe = fn.endswith(".so") or ".so." in fn or fn == "ffmpeg"
                with open(full, "rb") as f:
                    self.file(f"{prefix}/{rel}", f.read(), 0o755 if exe else 0o644)

    def close(self):
        self.t.close()


def python_tarball(arch: str) -> str:
    """python-build-standalone's CPython for Linux (it includes tkinter); the stripped build if offered."""
    meta = os.path.join(bi.CACHE, f"pbs-linux-{arch}.json")
    if not os.path.isfile(meta):
        ver = re.escape("%d.%d" % sys.version_info[:2])
        req = urllib.request.Request("https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest",
                                     headers={"User-Agent": "khvcemu-build"})
        rel = json.load(urllib.request.urlopen(req))
        base = rf"^cpython-{ver}\.\d+\+\d+-{re.escape(ARCHES[arch]['triple'])}-install_only"
        hit = [a for a in rel["assets"] if re.match(base + r"_stripped\.tar\.gz$", a["name"])] or \
              [a for a in rel["assets"] if re.match(base + r"\.tar\.gz$", a["name"])]
        if not hit:
            sys.exit(f"No python-build-standalone {ver} build for Linux {arch} in release {rel['tag_name']}.")
        os.makedirs(bi.CACHE, exist_ok=True)
        json.dump({"name": hit[0]["name"], "url": hit[0]["browser_download_url"]}, open(meta, "w"))
    m = json.load(open(meta))
    return bi.download(m["url"], m["name"])


def ffmpeg_binary(arch: str) -> bytes:
    path = bi.download(ARCHES[arch]["ffmpeg"], f"ffmpeg-linux-{arch}.tar.xz")
    with tarfile.open(path, "r:xz") as tf:
        for m in tf:
            if m.isfile() and os.path.basename(m.name) == "ffmpeg":
                return tf.extractfile(m).read()
    sys.exit("No ffmpeg binary found in " + path)


def build(arch: str, game: str, out_dir: str, version: str):
    print(f"=== Linux {arch}")
    stage = os.path.join(bi.BUILD, "linux-" + arch)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    print("1/4 libraries (manylinux wheels)")
    site = os.path.join(stage, "site")
    bi.pip_install(site, [f"{t}_{arch}" for t in MANYLINUX])
    bi.trim_site(site)
    print("2/4 khvcemu and the game files")
    proj = os.path.join(stage, "khvcemu")
    bi.build_app(proj, game)
    print("3/4 Python, ffmpeg and the payload")
    tarball = python_tarball(arch)
    payload = os.path.join(stage, "payload.tar.gz")
    pl = Payload(payload, ARCHES[arch]["machine"])
    skip = re.compile(r"(^|/)(__pycache__|include|share)(/|$)|/lib/python[\d.]+/(test|idlelib/idle_test)(/|$)")
    pyver = "%d.%d" % sys.version_info[:2]
    with tarfile.open(tarball) as tf:
        for m in tf:
            if skip.search(m.name) or m.isdir():
                continue
            if m.issym():
                pl.symlink(m.name, m.linkname)
            elif m.isfile() or m.islnk():
                pl.file(m.name, tf.extractfile(m).read(), m.mode & 0o777 or 0o644)
    pl.tree(site, f"python/lib/python{pyver}/site-packages")
    pl.tree(proj, "khvcemu")
    pl.file("khvcemu/bin/ffmpeg", ffmpeg_binary(arch), 0o755)
    pl.file("launch.sh", LAUNCH_SH.encode(), 0o755)
    pl.file("uninstall.sh", UNINSTALL_SH.encode(), 0o755)
    pl.file(".khvcemu-install", f"{version}\n".encode())
    pl.close()
    if pl.wrong:
        print("\nWRONG-CPU FILES (the build is not usable):")
        for n, c in pl.wrong[:20]:
            print("  ", n, c)
        sys.exit(1)
    print(f"checked {pl.elf} compiled files: all are {arch}")
    print("4/4 self-extracting installer")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"KH-ReCast-Linux-{arch}.run")
    head = INSTALLER_HEAD.replace("__ARCH__", arch).replace("__VERSION__", version).replace("\r\n", "\n")
    with open(out, "wb") as f:
        f.write(head.encode("utf-8"))
        with open(payload, "rb") as p:
            shutil.copyfileobj(p, f, 1 << 20)
    print(f"\nBuilt {out}  ({os.path.getsize(out) / 1e6:.0f} MB)")


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
