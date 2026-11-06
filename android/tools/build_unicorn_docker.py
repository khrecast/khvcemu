"""Builds libunicorn.so for Android (arm64-v8a and x86_64) in a throwaway Linux container, with the official Linux NDK r28c.

The Windows NDK cannot build Unicorn (its CMake runs QEMU's configure shell script; see android/NOTES.md, chunk 3), so this
runs android/tools/build_unicorn_android.sh in a Debian container under Docker Desktop:

    python -I android/tools/build_unicorn_docker.py [--abi arm64-v8a --abi x86_64] [--install x86_64] [--keep]

What it does:
  * downloads NDK r28c for Linux (about 722 MB) and the Unicorn 2.1.4 source archive (GitHub tag 2.1.4) once into a cache
    folder outside the repository (default %LOCALAPPDATA%\\khrecast-android\\cache, or --cache), and checks both by SHA-256
    (and the NDK by the SHA-1 Google publishes, the archive by the tag's commit id)
  * starts Docker Desktop if it is neither running nor starting (Windows), runs the build in `debian:bookworm-slim` pinned
    by digest, and afterwards removes that image if this run pulled it and, only if this run started Docker Desktop, quits
    it again (--keep leaves both as they are). Starting it also starts the user's containers that have a restart policy;
    those (except "unless-stopped" ones, which stop with Docker) are stopped cleanly with `docker stop` before Docker
    Desktop is quit (`docker desktop stop`, or on 4.19, which has no clean quit command, by force-stopping its processes).
    A Docker Desktop that was already running or starting is never stopped.
  * writes <out>/<abi>/libunicorn.so (default C:\\Android\\libs\\docker, or $ANDROID_ROOT\\libs\\docker, or --out) and prints
    each library's size, SHA-256 and LOAD alignment; it fails if a library is not 16 KB aligned or is the wrong machine
  * --install <abi> also copies that ABI's library to <root>\\libs\\<abi>\\libunicorn.so, where android/fetch_unicorn.ps1
    takes it from (an existing different file is kept beside it as libunicorn.so.<hash>.bak)

Nothing it makes goes into git (Unicorn is GPLv2 and built, not vendored). Any Python 3.10 or newer runs it.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_page_alignment import alignments  # noqa: E402

NDK_URL = "https://dl.google.com/android/repository/android-ndk-r28c-linux.zip"
NDK_SIZE = 722261334
NDK_SHA1 = "a7b54a5de87fecd125a17d54f73c446199e72a64"           # from Google's SDK repository (repository2-3.xml), ndk;28.2.13676358
NDK_SHA256 = "dfb20d396df28ca02a8c708314b814a4d961dc9074f9a161932746f815aa552f"
UC_URL = "https://github.com/unicorn-engine/unicorn/archive/refs/tags/2.1.4.tar.gz"
UC_SHA256 = "ea8863f095a0136388694e5a6063afd9bb7650e30243dd6251af59c5ce5601f4"   # the same as Homebrew's unicorn 2.1.4 formula
UC_COMMIT = "8028ec436f2d9376525352dd38ed9ed6b9f6be10"          # tag 2.1.4 (git rev-parse 2.1.4^{commit})
# Debian 12 slim, pinned to the image index used for the 2026-11-03 builds (the same digest on every host platform)
IMAGE = "debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3"
ABIS = {"arm64-v8a": 183, "x86_64": 62}                          # ELF e_machine: EM_AARCH64, EM_X86_64
DOCKER_DESKTOP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "build_unicorn_android.sh"


def default_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "khrecast-android" / "cache"


def android_root() -> Path:
    return Path(os.environ.get("ANDROID_ROOT") or (r"C:\Android" if os.name == "nt" else os.path.expanduser("~/Android")))


def file_hash(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path, checks: dict):
    """Downloads url to dest unless a file with the right hashes is already there."""
    def ok():
        return dest.exists() and all(file_hash(dest, a) == v for a, v in checks.items())
    if ok():
        print("cached:", dest)
        return
    print("downloading", url)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    part.replace(dest)
    if not ok():
        sys.exit("%s: wrong checksum, not used (%s)" % (dest, ", ".join("%s %s" % (a, file_hash(dest, a)) for a in checks)))


def docker(*args, check=True, capture=False, **kw):
    return subprocess.run(["docker", *args], check=check, capture_output=capture, text=capture, **kw)


def docker_ready() -> bool:
    try:
        return docker("info", check=False, capture=True, timeout=60).returncode == 0
    except subprocess.TimeoutExpired:                            # a starting engine can hang `docker info`
        return False


def desktop_process_running() -> bool:
    """Whether Docker Desktop's own program is running (it may still be starting up)."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/NH"], capture_output=True, text=True)
    except OSError:                                              # not Windows
        return False
    return "Docker Desktop.exe" in r.stdout


def start_docker() -> bool:
    """Waits for Docker; starts Docker Desktop first unless it is already running or starting. True if this started it."""
    started = not desktop_process_running()
    if not started:
        print("Docker Desktop is already starting: waiting for it (it will be left running)")
    elif not DOCKER_DESKTOP.exists():
        sys.exit("Docker is not running and Docker Desktop was not found at %s: start Docker first" % DOCKER_DESKTOP)
    else:
        print("starting Docker Desktop")
        subprocess.Popen([str(DOCKER_DESKTOP)])
    for _ in range(90):
        time.sleep(4)
        if docker_ready():
            print("Docker is ready")
            return started
    sys.exit("Docker did not become ready in 6 minutes")


def stop_docker():
    """Quits Docker Desktop. Starting it also starts the user's containers that have a restart policy: those are stopped
    cleanly first (`docker stop`, 30 s each), except "unless-stopped" ones (`docker stop` would keep them down next time). Then `docker desktop stop` where this Docker has it, else (Docker Desktop 4.19)
    every process started from its folder is force-stopped and its WSL distributions shut down. run_in_container calls it
    only when it started Docker Desktop itself."""
    ids = docker("ps", "-q", check=False, capture=True).stdout.split()
    lines = docker("inspect", "--format", "{{.Id}} {{.Name}} {{.HostConfig.RestartPolicy.Name}}", *ids,
                   check=False, capture=True).stdout.splitlines() if ids else []
    stop, keep = [], []
    for line in lines:
        cid, name, policy = (line.split() + [""])[:3]
        if name.lstrip("/") != "khrecast-android-build":
            (keep if policy == "unless-stopped" else stop).append((cid, name.lstrip("/")))
    if stop:
        print("stopping the containers Docker Desktop started:", ", ".join(n for _, n in stop))
        docker("stop", "-t", "30", *[c for c, _ in stop], check=False)
    if keep:      # `docker stop` would keep an unless-stopped container down the next time Docker starts
        print("left running until Docker quits, so they start with Docker next time:", ", ".join(n for _, n in keep))
    print("quitting Docker Desktop")
    if docker("desktop", "stop", check=False, capture=True).returncode == 0:
        return
    folder = str(DOCKER_DESKTOP.parent.parent)                   # every process started from C:\Program Files\Docker
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith('%s\\') } | Stop-Process -Force" % folder],
                   capture_output=True)
    for distro in ("docker-desktop", "docker-desktop-data"):
        subprocess.run(["wsl", "--terminate", distro], capture_output=True)


def fetch_source(url: str, dest: Path, sha256: str, commit: str, name: str):
    """A GitHub tag archive, checked by SHA-256 and by the commit id GitHub writes into it."""
    fetch(url, dest, {"sha256": sha256})
    with tarfile.open(dest) as tf:
        if tf.pax_headers.get("comment") != commit:
            sys.exit("%s: not the archive of commit %s" % (dest, commit))
    print("%s source: sha256 %s, commit %s" % (name, sha256, commit))


def fetch_ndk(cache: Path):
    ndk = cache / "android-ndk-r28c-linux.zip"
    fetch(NDK_URL, ndk, {"sha1": NDK_SHA1, "sha256": NDK_SHA256})
    if ndk.stat().st_size != NDK_SIZE:
        sys.exit("%s: unexpected size" % ndk)
    print("NDK r28c: sha256 %s" % NDK_SHA256)


def run_in_container(script: Path, args, cache: Path, out: Path, keep: bool):
    """Runs a build script (from android/tools) in a throwaway Debian container with the cache at /cache (read-only) and out
    at /out. Starts Docker Desktop if needed; afterwards removes the image if it was pulled here and quits Docker Desktop if
    it was started here, unless keep. Exits on a failed build."""
    if shutil.which("docker") is None:
        sys.exit("No docker command: install Docker Desktop (or run %s on a Linux host)" % script.name)
    scripts = cache / "scripts"                                # the working copy may have CRLF line ends: run an LF copy
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / script.name).write_bytes(script.read_bytes().replace(b"\r\n", b"\n"))
    out.mkdir(parents=True, exist_ok=True)
    started = False
    if not docker_ready():
        started = start_docker()
    had_image = docker("image", "inspect", IMAGE, check=False, capture=True).returncode == 0
    failed = None
    try:
        docker("pull", IMAGE)
        digest = docker("image", "inspect", "--format", "{{index .RepoDigests 0}}", IMAGE, capture=True).stdout.strip()
        print("image", digest)
        docker("run", "--rm", "--name", "khrecast-android-build",
               "-v", "%s:/cache:ro" % cache.resolve(), "-v", "%s:/out" % out.resolve(),
               IMAGE, "sh", "/cache/scripts/" + script.name, *args, stdin=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        failed = "the build failed (exit status %d, see above)" % e.returncode
    finally:
        if not keep:
            if not had_image:
                docker("image", "rm", IMAGE, check=False)
            if started:
                stop_docker()
    if failed:
        sys.exit(failed)


def check_output(abi: str, lib: Path):
    if not lib.exists():
        sys.exit("No %s" % lib)
    data = lib.read_bytes()
    al = alignments(data)
    machine = int.from_bytes(data[0x12:0x14], "little") if al is not None else None
    print("%s: %s, %d bytes, sha256 %s, LOAD alignment %s" % (abi, lib, len(data), hashlib.sha256(data).hexdigest(), al))
    if machine != ABIS[abi]:
        sys.exit("%s: ELF machine %s, expected %d" % (lib, machine, ABIS[abi]))
    if not al or min(al) < 16384:
        sys.exit("%s: not 16 KB aligned" % lib)


def install(abi: str, lib: Path):
    dest = android_root() / "libs" / abi / "libunicorn.so"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and file_hash(dest, "sha256") != file_hash(lib, "sha256"):
        bak = dest.with_name("libunicorn.so.%s.bak" % file_hash(dest, "sha256")[:8])
        shutil.copy2(dest, bak)
        print("kept the previous library as", bak)
    shutil.copy2(lib, dest)
    print("installed", dest, "(now run .\\android\\fetch_unicorn.ps1)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--abi", action="append", choices=sorted(ABIS), help="default: arm64-v8a and x86_64")
    ap.add_argument("--cache", type=Path, default=default_cache())
    ap.add_argument("--out", type=Path, default=android_root() / "libs" / "docker")
    ap.add_argument("--install", action="append", choices=sorted(ABIS), default=[],
                    help="copy this ABI's library to <root>\\libs\\<abi>\\ for fetch_unicorn.ps1")
    ap.add_argument("--keep", action="store_true", help="leave Docker running and the image in place")
    a = ap.parse_args()
    abis = a.abi or sorted(ABIS)
    for abi in a.install:
        if abi not in abis:
            sys.exit("--install %s needs that ABI built" % abi)

    a.cache.mkdir(parents=True, exist_ok=True)
    fetch_source(UC_URL, a.cache / "unicorn-2.1.4.tar.gz", UC_SHA256, UC_COMMIT, "Unicorn 2.1.4")
    fetch_ndk(a.cache)
    run_in_container(SCRIPT, abis, a.cache, a.out, a.keep)
    for abi in abis:
        check_output(abi, a.out / abi / "libunicorn.so")
    for abi in a.install:
        install(abi, a.out / abi / "libunicorn.so")


if __name__ == "__main__":
    main()
