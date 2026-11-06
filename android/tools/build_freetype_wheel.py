"""Builds FreeType 2.9.1 for Android with the NDK (16 KB page aligned) and packs it as a chaquopy-freetype wheel.

Pillow (the game's text, khvcemu/hostgfx.py) needs Chaquopy's chaquopy-freetype 2.9.1, the only build on its package index,
and that libfreetype.so is aligned to 4 KB pages: a phone with 16 KB pages refuses to load it. This script rebuilds the same
version the way Chaquopy's recipe does (zlib from the system, no PNG, no HarfBuzz, no bzip2; SONAME libfreetype.so) with
NDK r28 (16 KB alignment by default, and asked for explicitly) and writes wheels into android/wheels/ (gitignored):

    chaquopy_freetype-2.9.1-100-py3-none-android_24_<abi>.whl

The app build points pip at that folder (`--find-links` in android/app/build.gradle.kts). The android_24 platform tag and the
build number 100 make pip pick these over Chaquopy's (android_21, build 2). The Gradle build stops with a message when a wheel
for one of the app's ABIs is missing.

    . .\\android\\env.ps1                                 (sets ANDROID_HOME and ANDROID_NDK_HOME for this shell)
    python android/tools/build_freetype_wheel.py [abi ...]   (default: arm64-v8a x86_64)

Any Python 3.10 or newer runs it. The source tarball is downloaded once into android/build/freetype/ and checked by SHA-256.
"""
import base64
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_page_alignment import alignments  # noqa: E402

VERSION = "2.9.1"
BUILD_TAG = "100"
API = 24
URLS = [
    "https://download.savannah.gnu.org/releases/freetype/freetype-%s.tar.gz" % VERSION,
    "https://downloads.sourceforge.net/project/freetype/freetype2/%s/freetype-%s.tar.gz" % (VERSION, VERSION),
]
SHA256 = "ec391504e55498adceb30baceebd147a6e963f636eb617424bcfc47a169898ce"
NDK_VERSION = "28.2.13676358"
CMAKE_VERSION = "3.31.6"
DEFAULT_ABIS = ["arm64-v8a", "x86_64"]

ANDROID_DIR = Path(__file__).resolve().parent.parent
WORK = ANDROID_DIR / "build" / "freetype"
OUT = ANDROID_DIR / "wheels"


def tools():
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    ndk = os.environ.get("ANDROID_NDK_HOME") or (sdk and os.path.join(sdk, "ndk", NDK_VERSION))
    if not sdk or not ndk or not os.path.isdir(ndk):
        sys.exit("Set ANDROID_HOME (and ANDROID_NDK_HOME) first: . .\\android\\env.ps1")
    exe = ".exe" if os.name == "nt" else ""
    cmake_bin = Path(sdk) / "cmake" / CMAKE_VERSION / "bin"
    host = "windows-x86_64" if os.name == "nt" else ("darwin-x86_64" if sys.platform == "darwin" else "linux-x86_64")
    llvm_bin = Path(ndk) / "toolchains" / "llvm" / "prebuilt" / host / "bin"
    t = {
        "ndk": Path(ndk),
        "cmake": cmake_bin / ("cmake" + exe),
        "ninja": cmake_bin / ("ninja" + exe),
        "strip": llvm_bin / ("llvm-strip" + exe),
        "readelf": llvm_bin / ("llvm-readelf" + exe),
    }
    for k, p in t.items():
        if not p.exists():
            sys.exit("Not found: %s (%s)" % (p, k))
    return t


def fetch_source() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    tgz = WORK / ("freetype-%s.tar.gz" % VERSION)
    if not tgz.exists() or hashlib.sha256(tgz.read_bytes()).hexdigest() != SHA256:
        for url in URLS:
            try:
                print("downloading", url)
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = r.read()
            except OSError as e:
                print("  failed:", e)
                continue
            if hashlib.sha256(data).hexdigest() == SHA256:
                tgz.write_bytes(data)
                break
            print("  wrong SHA-256, skipped")
        else:
            sys.exit("Could not download FreeType %s with the expected SHA-256" % VERSION)
    src = WORK / ("freetype-%s" % VERSION)
    if src.exists():
        shutil.rmtree(src)
    with tarfile.open(tgz) as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(WORK, filter="data")
        else:
            for m in tf.getmembers():
                if m.name.startswith(("/", "..")) or ".." in Path(m.name).parts or m.issym() or m.islnk():
                    sys.exit("Unexpected tar member: " + m.name)
            tf.extractall(WORK)
    return src


def build(t, src: Path, abi: str) -> Path:
    bdir = WORK / ("build-" + abi)
    idir = WORK / ("install-" + abi)
    for d in (bdir, idir):
        if d.exists():
            shutil.rmtree(d)
    cfg = [
        str(t["cmake"]), "-S", str(src), "-B", str(bdir), "-G", "Ninja",
        "-DCMAKE_MAKE_PROGRAM=" + str(t["ninja"]),
        "-DCMAKE_TOOLCHAIN_FILE=" + str(t["ndk"] / "build" / "cmake" / "android.toolchain.cmake"),
        "-DANDROID_ABI=" + abi,
        "-DANDROID_PLATFORM=android-%d" % API,
        "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",
        "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_INSTALL_PREFIX=" + str(idir),
        "-DBUILD_SHARED_LIBS=ON",
        "-DCMAKE_PLATFORM_NO_VERSIONED_SONAME=ON",       # SONAME libfreetype.so, as Chaquopy's (Pillow's _imagingft.so needs that name)
        "-DFT_WITH_ZLIB=ON",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PNG=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_BZip2=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_HarfBuzz=TRUE",
    ]
    subprocess.run(cfg, check=True)
    subprocess.run([str(t["cmake"]), "--build", str(bdir)], check=True)
    subprocess.run([str(t["cmake"]), "--install", str(bdir)], check=True)
    lib = idir / "lib" / "libfreetype.so"
    if not lib.exists():
        sys.exit("No libfreetype.so in " + str(idir / "lib"))
    subprocess.run([str(t["strip"]), "--strip-unneeded", str(lib)], check=True)
    check_lib(t, lib)
    return idir


def check_lib(t, lib: Path):
    al = alignments(lib.read_bytes())
    if not al or min(al) < 16384:
        sys.exit("%s: LOAD alignment %s, not 16 KB" % (lib, al))
    dyn = subprocess.run([str(t["readelf"]), "-d", str(lib)], check=True, capture_output=True, text=True).stdout
    if "[libfreetype.so]" not in dyn.split("SONAME", 1)[-1].splitlines()[0]:
        sys.exit("%s: SONAME is not libfreetype.so\n%s" % (lib, dyn))
    needed = sorted(line.split("[", 1)[1].rstrip("]") for line in dyn.splitlines() if "(NEEDED)" in line)
    print("  %s: alignment %d, NEEDED %s" % (lib.name, min(al), ", ".join(needed)))
    extra = set(needed) - {"libc.so", "libm.so", "libdl.so", "libz.so"}
    if extra:
        sys.exit("%s: unexpected dependencies %s" % (lib, sorted(extra)))


def record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return "%s,sha256=%s,%d" % (name, digest, len(data))


def pack(src: Path, idir: Path, abi: str) -> Path:
    tag = "py3-none-android_%d_%s" % (API, abi.replace("-", "_"))
    distinfo = "chaquopy_freetype-%s.dist-info" % VERSION
    files = {"chaquopy/lib/libfreetype.so": (idir / "lib" / "libfreetype.so").read_bytes()}
    inc = idir / "include" / "freetype2"                   # Chaquopy's recipe moves include/freetype2/* up to include/
    for p in sorted(inc.rglob("*")):
        if p.is_file():
            files["chaquopy/include/" + p.relative_to(inc).as_posix()] = p.read_bytes()
    files[distinfo + "/METADATA"] = ("Metadata-Version: 1.2\nName: chaquopy-freetype\nVersion: %s\nSummary: \nDownload-URL: \n"
                                     % VERSION).encode()
    files[distinfo + "/WHEEL"] = ("Wheel-Version: 1.0\nRoot-Is-Purelib: false\nGenerator: khrecast build_freetype_wheel.py\n"
                                  "Build: %s\nTag: %s\n" % (BUILD_TAG, tag)).encode()
    files[distinfo + "/FTL.TXT"] = (src / "docs" / "FTL.TXT").read_bytes()
    record = [record_line(n, d) for n, d in files.items()] + [distinfo + "/RECORD,,"]
    files[distinfo + "/RECORD"] = ("\n".join(record) + "\n").encode()
    OUT.mkdir(parents=True, exist_ok=True)
    whl = OUT / ("chaquopy_freetype-%s-%s-%s.whl" % (VERSION, BUILD_TAG, tag))
    with zipfile.ZipFile(whl, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            info = zipfile.ZipInfo(n, date_time=(2018, 5, 2, 0, 0, 0))   # fixed dates: the same input gives the same wheel
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, d)
    print("  ->", whl, "(sha256 %s)" % hashlib.sha256(whl.read_bytes()).hexdigest())
    return whl


def main():
    abis = sys.argv[1:] or DEFAULT_ABIS
    for abi in abis:
        if abi not in DEFAULT_ABIS:                              # 64-bit only, like the app (and check_page_alignment.py)
            sys.exit("Unknown ABI: %s (one of %s)" % (abi, ", ".join(DEFAULT_ABIS)))
    t = tools()
    src = fetch_source()
    for abi in abis:
        print("== FreeType %s for %s (API %d)" % (VERSION, abi, API))
        pack(src, build(t, src, abi), abi)


if __name__ == "__main__":
    main()
