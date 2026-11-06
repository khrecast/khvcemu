"""Build Re:Cast's own small ffmpeg (LGPL 2.1 or later) for the six desktop installers.

    python -I tools/build_ffmpeg.py [--target windows-x64 ...] [--cache DIR] [--out DIR] [--test-dir DIR] [--keep]
                                    [--check-only]

The installers (tools/build_installer.py, build_mac.py, build_linux.py) take ffmpeg from build/ffmpeg/<target>/, which this
script fills: windows-x64, windows-x86, macos-arm64, macos-x86_64, linux-x86_64, linux-aarch64. Each is FFmpeg 9.0.2 with
only what Re:Cast uses (reading QCELP, WAV, FLAC, MP3, Ogg Vorbis, Opus, AAC/M4A, ALAC, AIFF, WMA and WavPack, writing
16-bit PCM), no GPL, version3 or nonfree parts and no external libraries, so the FFmpeg source tarball alone is its
complete source.

What it does:
  * downloads the FFmpeg 9.0.2 source from ffmpeg.org and zig 0.15.2 (the C cross compiler for all six targets) once into
    a cache folder outside the repository (default %LOCALAPPDATA%\\khrecast-ffmpeg\\cache, or --cache) and checks both by
    SHA-256
  * starts Docker Desktop if it is neither running nor starting, runs tools/build_ffmpeg.sh in `debian:bookworm-slim`
    pinned by digest, and afterwards removes that image if this run pulled it and quits Docker Desktop only if this run
    started it (--keep leaves both). Starting Docker Desktop also starts the user's containers that have a restart policy;
    before quitting, they are stopped cleanly with `docker stop`, except "unless-stopped" ones (`docker stop` would keep
    those down the next time Docker starts), which stop with Docker. Then Docker Desktop is quit with `docker desktop
    stop`, or, on versions without that command, by force-stopping its processes. A Docker the user started (or that was
    already starting) is never stopped.
  * checks each binary (CPU and file format; Windows: only system DLLs; Linux: glibc 2.28 or older symbols and only the C
    library; macOS: minimum version, only libSystem, and on arm64 a valid ad-hoc code signature; no GPL, version3 or
    nonfree in its configure line) and prints its size, SHA-256 and configure line, read from the binary itself
  * smoke test (the build fails if it does not pass): a WAV tone, made-up QCELP packets in the QCP container that
    khvcemu/pmd.py writes, and tests/fixtures/tone.m4a are decoded with Re:Cast's exact command lines by the Windows
    builds here (on Windows) and the Linux builds in the container (aarch64 under qemu-user), and each result is checked
    for length and level; the macOS builds cannot be run
  * writes build/ffmpeg/BUILDINFO.txt (sources, tools, hashes, configure lines) and build/ffmpeg/LICENSE.txt (the LGPL 2.1)
  * --check-only: builds nothing, only checks the binaries already there and rewrites BUILDINFO.txt
  * --test-dir DIR: also decodes every file in DIR/in with the two Linux builds (aarch64 under qemu-user) into
    DIR/<target>/ with Re:Cast's command lines (a .qcp file the way pmd.py pipes it in), for comparing with other builds

Needs Docker Desktop (or a running docker), internet access the first time, and Python 3.10 or newer with numpy (the
smoke test uses khvcemu/pmd.py).
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

FFMPEG_VERSION = "9.0.2"
FFMPEG_TAR = "ffmpeg-9.0.2.tar.xz"
FFMPEG_URL = "https://ffmpeg.org/releases/" + FFMPEG_TAR
FFMPEG_SHA256 = "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
ZIG_TAR = "zig-x86_64-linux-0.15.2.tar.xz"
ZIG_URL = "https://ziglang.org/download/0.15.2/" + ZIG_TAR
ZIG_SHA256 = "02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239"   # as listed in ziglang.org/download/index.json
# Debian 12 slim, the same image index tools/build_unicorn_docker.py pins (one digest for every host platform)
IMAGE = "debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3"
CONTAINER = "khrecast-ffmpeg-build"
DOCKER_DESKTOP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve().parent / "build_ffmpeg.sh"
OUT = ROOT / "build" / "ffmpeg"

# target -> (file name, format, CPU): PE machine, Mach-O CPU type or ELF machine
TARGETS = {
    "windows-x64": ("ffmpeg.exe", "pe", 0x8664),
    "windows-x86": ("ffmpeg.exe", "pe", 0x14C),
    "macos-arm64": ("ffmpeg", "macho", 0x0100000C),
    "macos-x86_64": ("ffmpeg", "macho", 0x01000007),
    "linux-x86_64": ("ffmpeg", "elf", 0x3E),
    "linux-aarch64": ("ffmpeg", "elf", 0xB7),
}
MACOS_MIN = {"macos-arm64": "11.0", "macos-x86_64": "10.15"}      # the same as tools/build_mac.py
GLIBC_MAX = (2, 28)                                               # the Linux installers' stated minimum
LINUX_LIBS = re.compile(r"^(libc|libm|libpthread|libdl|librt|ld-linux[-\w]*)\.so\.\d+$")
WINDOWS_DLLS = {"kernel32.dll", "user32.dll", "advapi32.dll", "bcrypt.dll", "shell32.dll", "psapi.dll", "ole32.dll",
                "ws2_32.dll", "ntdll.dll", "msvcrt.dll", "ucrtbase.dll", "shlwapi.dll", "secur32.dll"}


def default_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "khrecast-ffmpeg" / "cache"


def ffmpeg_path(target: str, out: Path = OUT) -> Path:
    """Where the installers look for a target's ffmpeg."""
    return out / target / TARGETS[target][0]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path, digest: str):
    if dest.exists() and sha256(dest) == digest:
        print("cached:", dest)
        return
    print("downloading", url)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    got = sha256(part)
    if got != digest:
        part.unlink()
        sys.exit("%s: wrong SHA-256 %s, not used" % (url, got))
    part.replace(dest)


# ---- Docker (the same approach as android/tools/build_unicorn_docker.py) ----

def docker(*args, check=True, capture=False, **kw):
    return subprocess.run(["docker", *args], check=check, capture_output=capture, text=capture, **kw)


def docker_ready() -> bool:
    try:
        return docker("info", check=False, capture=True, timeout=60).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def desktop_process_running() -> bool:
    """Whether Docker Desktop's own program is running (it may still be starting up)."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/NH"], capture_output=True, text=True)
    except OSError:                                                # not Windows
        return False
    return "Docker Desktop.exe" in r.stdout


def start_docker() -> bool:
    """Waits for Docker; starts Docker Desktop first unless it is already running or starting. True if this started it."""
    if desktop_process_running():
        print("Docker Desktop is already starting: waiting for it (it will be left running)")
        started = False
    elif DOCKER_DESKTOP.exists():
        print("starting Docker Desktop")
        subprocess.Popen([str(DOCKER_DESKTOP)])
        started = True
    else:
        sys.exit("Docker is not running and Docker Desktop was not found at %s: start Docker first" % DOCKER_DESKTOP)
    for _ in range(90):
        time.sleep(4)
        if docker_ready():
            print("Docker is ready")
            return started
    sys.exit("Docker did not become ready in 6 minutes")


def stop_docker():
    """Quits the Docker Desktop this script started. Starting it also starts the user's containers that have a restart
    policy; those are stopped cleanly first (`docker stop`, 30 s each), except "unless-stopped" ones, which `docker stop`
    would keep down the next time Docker starts. Then `docker desktop stop` where this Docker has it, else every process
    started from the Docker folder is force-stopped and its WSL distributions shut down."""
    ids = docker("ps", "-q", check=False, capture=True).stdout.split()
    lines = docker("inspect", "--format", "{{.Id}} {{.Name}} {{.HostConfig.RestartPolicy.Name}}", *ids,
                   check=False, capture=True).stdout.splitlines() if ids else []
    stop, keep = [], []
    for line in lines:
        cid, name, policy = (line.split() + [""])[:3]
        if name.lstrip("/") != CONTAINER:
            (keep if policy == "unless-stopped" else stop).append((cid, name.lstrip("/")))
    if stop:
        print("stopping the containers Docker Desktop started:", ", ".join(n for _, n in stop))
        docker("stop", "-t", "30", *[c for c, _ in stop], check=False)
    if keep:      # `docker stop` would keep an unless-stopped container down the next time Docker starts
        print("left running until Docker quits, so they start with Docker next time:", ", ".join(n for _, n in keep))
    print("quitting Docker Desktop")
    if docker("desktop", "stop", check=False, capture=True).returncode == 0:
        return
    folder = str(DOCKER_DESKTOP.parent.parent)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith('%s\\') } | Stop-Process -Force" % folder],
                   capture_output=True)
    for distro in ("docker-desktop", "docker-desktop-data"):
        subprocess.run(["wsl", "--terminate", distro], capture_output=True)


def run_container(targets, cache: Path, out: Path, test_dir, keep: bool) -> str:
    """Builds in the container; returns the image's repo digest."""
    if shutil.which("docker") is None:
        sys.exit("No docker command: install Docker Desktop (or run tools/build_ffmpeg.sh in a Debian 12 container)")
    scripts = cache / "scripts"                                    # the working copy may have CRLF line ends
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / SCRIPT.name).write_bytes(SCRIPT.read_bytes().replace(b"\r\n", b"\n"))
    out.mkdir(parents=True, exist_ok=True)
    started = False
    if not docker_ready():
        started = start_docker()
    had_image = docker("image", "inspect", IMAGE, check=False, capture=True).returncode == 0
    failed, digest = None, ""
    mounts = ["-v", "%s:/cache:ro" % cache.resolve(), "-v", "%s:/out" % out.resolve(),
              "-v", "%s:/smoke" % (out / "smoke").resolve()]
    if test_dir:
        mounts += ["-v", "%s:/selftest" % Path(test_dir).resolve()]
    try:
        docker("pull", IMAGE)
        digest = docker("image", "inspect", "--format", "{{index .RepoDigests 0}}", IMAGE, capture=True).stdout.strip()
        print("image", digest)
        docker("run", "--rm", "--name", CONTAINER, *mounts, IMAGE,
               "sh", "/cache/scripts/" + SCRIPT.name, FFMPEG_TAR, ZIG_TAR, *targets, stdin=subprocess.DEVNULL)
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
    return digest


# ---- checks on the finished binaries (plain Python, no tools needed) ----

def pe_info(data: bytes) -> dict:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[:2] != b"MZ" or data[pe:pe + 4] != b"PE\0\0":
        return {}
    machine, nsec = struct.unpack_from("<HH", data, pe + 4)
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dirs = opt + (112 if magic == 0x20B else 96)
    sections = [struct.unpack_from("<IIII", data, opt + opt_size + 40 * i + 8) for i in range(nsec)]

    def off(rva):
        for vsize, va, rawsize, raw in sections:
            if va <= rva < va + max(vsize, rawsize):
                return rva - va + raw
        raise ValueError("RVA %#x outside the sections" % rva)

    def cstr(o):
        return data[o:data.index(b"\0", o)].decode("ascii")

    dlls = []
    for index, size in ((1, 20), (13, 32)):                       # imports, delay-load imports
        rva = struct.unpack_from("<I", data, dirs + 8 * index)[0]
        if not rva:
            continue
        o = off(rva)
        while any(data[o:o + size]):
            name_rva = struct.unpack_from("<I", data, o + (12 if index == 1 else 4))[0]
            dlls.append(cstr(off(name_rva)))
            o += size
    return {"format": "PE32+" if magic == 0x20B else "PE32", "cpu": machine, "dlls": dlls}


def elf_info(data: bytes) -> dict:
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        return {}
    machine = struct.unpack_from("<H", data, 0x12)[0]
    phoff, shoff = struct.unpack_from("<QQ", data, 0x20)
    phnum, shnum = struct.unpack_from("<H", data, 0x38)[0], struct.unpack_from("<H", data, 0x3C)[0]
    interp = ""
    for i in range(phnum):
        p_type, _, p_offset, _, _, p_filesz = struct.unpack_from("<IIQQQQ", data, phoff + 56 * i)
        if p_type == 3:
            interp = data[p_offset:p_offset + p_filesz].rstrip(b"\0").decode()
    shdrs = [struct.unpack_from("<IIQQQQII", data, shoff + 64 * i) for i in range(shnum)]

    def strtab(index, o):
        base = shdrs[index][4]
        return data[base + o:data.index(b"\0", base + o)].decode()

    needed, versions = [], set()
    for _, sh_type, _, _, offset, size, link, info in shdrs:
        if sh_type == 6:                                           # SHT_DYNAMIC
            for o in range(offset, offset + size, 16):
                tag, val = struct.unpack_from("<qQ", data, o)
                if tag == 1:
                    needed.append(strtab(link, val))
        elif sh_type == 0x6FFFFFFE:                                # SHT_GNU_verneed
            o = offset
            for _ in range(info):
                _, cnt, _, aux, nxt = struct.unpack_from("<HHIII", data, o)
                a = o + aux
                for _ in range(cnt):
                    _, _, _, name, anext = struct.unpack_from("<IHHII", data, a)
                    versions.add(strtab(link, name))
                    a += anext
                o += nxt
    glibc = sorted(tuple(int(x) for x in v[6:].split(".")) for v in versions if v.startswith("GLIBC_2"))
    return {"format": "ELF64", "cpu": machine, "interp": interp, "needed": needed,
            "glibc": ".".join(map(str, glibc[-1])) if glibc else "", "glibc_max": glibc[-1] if glibc else ()}


def macho_info(data: bytes) -> dict:
    if data[:4] != b"\xcf\xfa\xed\xfe":
        return {}
    cpu, _, _, ncmds = struct.unpack_from("<iIII", data, 4)
    o, info = 32, {"format": "Mach-O 64", "cpu": cpu & 0xFFFFFFFF, "dylibs": [], "minos": "", "signature": "none"}
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, o)
        if cmd in (0xC, 0x80000018):                               # LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB
            name = struct.unpack_from("<I", data, o + 8)[0]
            info["dylibs"].append(data[o + name:data.index(b"\0", o + name)].decode())
        elif cmd in (0x32, 0x24):                                  # LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX
            v = struct.unpack_from("<I", data, o + (12 if cmd == 0x32 else 8))[0]
            info["minos"] = "%d.%d" % (v >> 16, (v >> 8) & 0xFF) + (".%d" % (v & 0xFF) if v & 0xFF else "")
        elif cmd == 0x1D:                                          # LC_CODE_SIGNATURE
            info["signature"] = check_signature(data, *struct.unpack_from("<II", data, o + 8))
        o += size
    return info


def check_signature(data: bytes, dataoff: int, datasize: int) -> str:
    """Checks the code signature's CodeDirectory page hashes against the file: 'valid ad-hoc' or what is wrong."""
    blob = data[dataoff:dataoff + datasize]
    magic, _, count = struct.unpack_from(">III", blob, 0)
    if magic != 0xFADE0CC0:
        return "bad superblob"
    for i in range(count):
        _, bo = struct.unpack_from(">II", blob, 12 + 8 * i)
        if struct.unpack_from(">I", blob, bo)[0] != 0xFADE0C02:
            continue
        (_, _, _, flags, hash_off, _, _, nslots, limit, hsize, htype, _, page) = struct.unpack_from(">IIIIIIIIIBBBB", blob, bo)
        if htype != 2 or hsize != 32:
            return "unexpected hash type %d" % htype
        ps = 1 << page
        for s in range(nslots):
            want = blob[bo + hash_off + 32 * s:bo + hash_off + 32 * (s + 1)]
            if hashlib.sha256(data[s * ps:min((s + 1) * ps, limit)]).digest() != want:
                return "page %d hash does not match" % s
        if limit != dataoff:
            return "code limit %d is not the signature offset %d" % (limit, dataoff)
        return "valid%s, %d pages" % (" ad-hoc" if flags & 2 else "", nslots)
    return "no CodeDirectory"


def configure_line(data: bytes) -> str:
    i = data.find(b"--prefix=")
    if i < 0:
        return ""
    j = data.index(b"\0", i)
    return data[i:j].decode("ascii", "replace")


def check(target: str, path: Path) -> tuple[list, list]:
    """(lines describing the binary, problems)."""
    name, fmt, cpu = TARGETS[target]
    data = path.read_bytes()
    info = {"pe": pe_info, "elf": elf_info, "macho": macho_info}[fmt](data)
    lines, bad = [], []
    if not info:
        return lines, ["not a %s file" % fmt]
    if info["cpu"] != cpu:
        bad.append("CPU %#x, expected %#x" % (info["cpu"], cpu))
    lines.append("%s, CPU %#x" % (info["format"], info["cpu"]))
    if fmt == "pe":
        expected = "PE32+" if target == "windows-x64" else "PE32"
        if info["format"] != expected:
            bad.append("%s, expected %s" % (info["format"], expected))
        other = [d for d in info["dlls"] if d.lower() not in WINDOWS_DLLS and not d.lower().startswith("api-ms-win-")]
        lines.append("DLLs: " + ", ".join(info["dlls"]))
        if other:
            bad.append("non-system DLLs: " + ", ".join(other))
    elif fmt == "elf":
        lines.append("needs: %s; interpreter %s; newest glibc symbol GLIBC_%s"
                     % (", ".join(info["needed"]), info["interp"], info["glibc"]))
        if info["glibc_max"] > GLIBC_MAX:
            bad.append("needs glibc %s, more than %d.%d" % (info["glibc"], *GLIBC_MAX))
        other = [n for n in info["needed"] if not LINUX_LIBS.match(n)]
        if other:
            bad.append("other shared libraries: " + ", ".join(other))
    else:
        lines.append("dylibs: %s; minimum macOS %s; code signature: %s"
                     % (", ".join(info["dylibs"]), info["minos"], info["signature"]))
        if info["minos"] != MACOS_MIN[target]:
            bad.append("minimum macOS %s, expected %s" % (info["minos"], MACOS_MIN[target]))
        if [d for d in info["dylibs"] if not d.startswith("/usr/lib/libSystem")]:
            bad.append("other dylibs: " + ", ".join(info["dylibs"]))
        if target == "macos-arm64" and not info["signature"].startswith("valid"):
            bad.append("arm64 needs a valid code signature: " + info["signature"])
    conf = configure_line(data)
    if not conf:
        bad.append("no configure line found in the binary")
    for word in ("--enable-gpl", "--enable-version3", "--enable-nonfree"):
        if word in conf:
            bad.append("configured with " + word)
    if b"LGPL version 2.1 or later" not in data:
        bad.append("the binary does not say 'LGPL version 2.1 or later'")
    return lines, bad


# ---- smoke test: a few made-up inputs decoded with Re:Cast's exact command lines ----

SMOKE_SECONDS = {"tone.wav": 1.0, "noise.qcp": 1.0, "tone.m4a": 2.0}
RATE = 22050                                                       # khvcemu.midi_synth.RATE


def make_smoke_inputs(folder: Path):
    """folder/in: a 1 s stereo WAV tone, 1 s of made-up QCELP packets in the QCP container khvcemu/pmd.py writes for the
    game's sounds, and the AAC .m4a of tests/fixtures. Nothing from the game."""
    import random
    import wave
    shutil.rmtree(folder / "in", ignore_errors=True)       # only the inputs: the container's decodes of targets not rebuilt this time stay
    (folder / "in").mkdir(parents=True)
    n = 44100
    frames = bytearray()
    for i in range(n):
        v = int(8000 * math.sin(2 * math.pi * 330 * i / 44100))
        frames += struct.pack("<hh", v, v)
    with wave.open(str(folder / "in" / "tone.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes(frames))
    sys.path.insert(0, str(ROOT))
    from khvcemu import pmd                                        # noqa: E402 (needs numpy, like Re:Cast)
    r = random.Random(1)
    packets = [bytes([4]) + bytes(r.randrange(256) for _ in range(34)) for _ in range(50)]   # 50 full-rate 20 ms packets
    (folder / "in" / "noise.qcp").write_bytes(pmd.qcp_container(packets))
    shutil.copyfile(ROOT / "tests" / "fixtures" / "tone.m4a", folder / "in" / "tone.m4a")


def smoke_problem(name: str, pcm: bytes) -> str:
    """'' if the decoded 16-bit mono PCM has about the right length and level, else what is wrong."""
    want = SMOKE_SECONDS[name] * RATE
    got = len(pcm) // 2
    if abs(got - want) > 0.05 * want:
        return "%s: %d samples, expected about %d" % (name, got, want)
    peak = max(abs(v) for (v,) in struct.iter_unpack("<h", pcm[:len(pcm) // 2 * 2]))
    if peak < 1000:
        return "%s: nearly silent (peak %d)" % (name, peak)
    return ""


def run_smoke(exe: Path, folder: Path) -> list:
    """Decodes the smoke inputs with exe on this computer, as audio.py and pmd.py call ffmpeg."""
    bad = []
    for name in SMOKE_SECONDS:
        path = folder / "in" / name
        if name.endswith(".qcp"):
            r = subprocess.run([str(exe), "-v", "error", "-f", "qcp", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                                "-ar", str(RATE), "pipe:1"], input=path.read_bytes(), capture_output=True, timeout=60)
        else:
            r = subprocess.run([str(exe), "-nostdin", "-v", "quiet", "-i", str(path), "-f", "s16le", "-ac", "1",
                                "-ar", str(RATE), "pipe:1"], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        problem = "%s: exit status %d" % (name, r.returncode) if r.returncode else smoke_problem(name, r.stdout)
        if problem:
            bad.append(problem)
    return bad


def smoke(target: str, out: Path, folder: Path):
    """(line for the report, problems) for one target: the Windows builds run here (on Windows), the Linux builds ran in
    the container; macOS cannot run here."""
    if target.startswith("windows") and os.name == "nt":
        bad = run_smoke(ffmpeg_path(target, out), folder)
    elif target.startswith("linux"):
        bad = []
        for name in SMOKE_SECONDS:
            s16 = folder / target / (name + ".s16")
            problem = smoke_problem(name, s16.read_bytes()) if s16.exists() else "%s: not decoded" % name
            if problem:
                bad.append(problem)
    else:
        return "smoke test: not run (cannot run here)", []
    return "smoke test (%s): %s" % (", ".join(SMOKE_SECONDS), "passed" if not bad else "FAILED"), bad


def windows_license(path: Path) -> str:
    """The first lines of `ffmpeg -L` (only on Windows, where the Windows builds run)."""
    r = subprocess.run([str(path), "-hide_banner", "-L"], capture_output=True, text=True, timeout=60)
    text = " ".join(r.stdout.split())
    if "GNU Lesser General Public License" not in text or "version 2.1 of the License, or (at your option)" not in text:
        sys.exit("%s -L does not name the LGPL 2.1 or later:\n%s" % (path, r.stdout[:600]))
    return "ffmpeg -L: GNU Lesser General Public License, version 2.1 or (at your option) any later version"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", action="append", choices=list(TARGETS), help="default: all six")
    ap.add_argument("--cache", type=Path, default=default_cache())
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--test-dir", type=Path, help="decode DIR/in/* with the Linux builds into DIR/<target>/")
    ap.add_argument("--keep", action="store_true", help="leave Docker running and the image in place")
    ap.add_argument("--check-only", action="store_true",
                    help="build nothing: check the binaries already in --out and rewrite BUILDINFO.txt")
    a = ap.parse_args()
    targets = a.target or list(TARGETS)

    if not a.check_only:
        a.cache.mkdir(parents=True, exist_ok=True)
        fetch(FFMPEG_URL, a.cache / FFMPEG_TAR, FFMPEG_SHA256)
        fetch(ZIG_URL, a.cache / ZIG_TAR, ZIG_SHA256)
        for t in targets:                                          # nothing stale is left if a target fails
            if ffmpeg_path(t, a.out).exists():
                ffmpeg_path(t, a.out).unlink()
        make_smoke_inputs(a.out / "smoke")
        digest = run_container(targets, a.cache, a.out, a.test_dir, a.keep)
        (a.out / "image.txt").write_text(digest + chr(10))
    elif not (a.out / "smoke" / "in").is_dir():
        make_smoke_inputs(a.out / "smoke")

    for t in targets:
        if not ffmpeg_path(t, a.out).exists():
            sys.exit("No %s" % ffmpeg_path(t, a.out))
    report, problems, confs = [], [], {}
    for t in [t for t in TARGETS if ffmpeg_path(t, a.out).exists()]:   # BUILDINFO lists every binary that is there
        path = ffmpeg_path(t, a.out)
        lines, bad = check(t, path)
        if t == "windows-x64" and os.name == "nt":
            lines.append(windows_license(path))
        line, smoke_bad = smoke(t, a.out, a.out / "smoke")
        lines.append(line)
        bad += smoke_bad
        size, digest_t = path.stat().st_size, sha256(path)
        confs[t] = configure_line(path.read_bytes())
        block = ["%s: %s" % (t, path.relative_to(a.out).as_posix()), "  size %d bytes, sha256 %s" % (size, digest_t)]
        block += ["  " + x for x in lines] + ["  configure: " + confs[t]]
        block += ["  PROBLEM: " + x for x in bad]
        print("\n".join(block))
        report += block + [""]
        problems += ["%s: %s" % (t, x) for x in bad]

    tools = (a.out / "tools.txt").read_text().strip() if (a.out / "tools.txt").exists() else ""
    image = (a.out / "image.txt").read_text().strip() if (a.out / "image.txt").exists() else ""
    head = [
        "FFmpeg %s for Kingdom Hearts Re:Cast, built by tools/build_ffmpeg.py" % FFMPEG_VERSION,
        "",
        "License: LGPL version 2.1 or later (no --enable-gpl, --enable-version3 or --enable-nonfree; no external",
        "libraries). The text is in LICENSE.txt. The complete source is the FFmpeg release tarball below, unmodified;",
        "the configure lines below rebuild it (as tools/build_ffmpeg.sh does: zig cc is the compiler, two linker options",
        "zig rejects are dropped, and where the target has no <sys/sysctl.h> config.h gets HAVE_SYSCTL 0 after configure).",
        "",
        "Source:   %s" % FFMPEG_URL,
        "          sha256 %s" % FFMPEG_SHA256,
        "Compiler: %s" % ZIG_URL,
        "          sha256 %s" % ZIG_SHA256,
        "Image:    %s" % (image or IMAGE),
        "Tools in the container: " + "; ".join(tools.splitlines()),
        "",
    ]
    (a.out / "BUILDINFO.txt").write_text("\n".join(head + report), encoding="utf-8", newline="\n")
    print("wrote", a.out / "BUILDINFO.txt")
    if problems:
        sys.exit("PROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
