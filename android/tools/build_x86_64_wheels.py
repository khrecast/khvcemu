"""Builds 16 KB page aligned x86_64 replacements for the Chaquopy packages whose x86_64 libraries are 4 KB aligned, and packs them
as wheels into android/wheels/ (gitignored), next to the FreeType ones:

    chaquopy_openblas-0.2.20+openblas0.3.33-100-py3-none-android_24_x86_64.whl   numpy's BLAS and LAPACK: OpenBLAS 0.3.33
    chaquopy_libgfortran-4.9+none-100-py3-none-android_24_x86_64.whl            empty: that OpenBLAS needs no Fortran runtime
    chaquopy_libjpeg-1.5.3-100-py3-none-android_24_x86_64.whl                   Pillow's JPEG library, the same version as Chaquopy's

Why: Chaquopy's x86_64 chaquopy-openblas 0.2.20, chaquopy-libgfortran 4.9 and chaquopy-libjpeg 1.5.3 are aligned to 4 KB pages,
so an x86_64 device with 16 KB pages (the ps16k emulator image) cannot load them. Their arm64-v8a builds are 16 KB aligned and
stay as they are (the phone keeps exactly what it was tested with).

Why the odd version numbers: Chaquopy resolves the requirements for the first ABI (arm64-v8a) and then installs exactly the same
`name==version` list, with --no-deps, for x86_64 (chaquopy/pip_install.py). So the x86_64 wheels must match arm64's versions:
chaquopy-openblas==0.2.20 and chaquopy-libgfortran==4.9. OpenBLAS 0.2.20 cannot be rebuilt without a Fortran compiler (its
LAPACK is Fortran; the NDK has none), so the library is OpenBLAS 0.3.33 built by Chaquopy's current recipe (NOFORTRAN, LAPACK
from C; Chaquopy has not published it yet), labeled with the local version "0.2.20+openblas0.3.33": `==0.2.20` matches it
(PEP 440 ignores local labels) and pip prefers it over plain 0.2.20. It needs no libgfortran, so the libgfortran wheel is an
empty "4.9+none" that satisfies the pin and keeps the unused 4 KB library out of the APK. The libjpeg wheel has the same version
and wins by its android_24 tag and build number 100, as the FreeType wheels do. numpy's 57 OpenBLAS imports and Pillow's 21
versioned libjpeg imports were checked against these libraries (android/NOTES.md).

The build runs android/tools/build_x86_64_libs_android.sh in a throwaway Linux container with the Linux NDK r28c, as
build_unicorn_docker.py does for Unicorn (same cache folder, Docker Desktop started and quit, the image removed afterwards):

    python -I android/tools/build_x86_64_wheels.py [--keep]

Any Python 3.10 or newer runs it.
"""
import argparse
import base64
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_unicorn_docker import default_cache, fetch, fetch_ndk, fetch_source, run_in_container  # noqa: E402
from check_page_alignment import alignments  # noqa: E402

OB_URL = "https://github.com/OpenMathLib/OpenBLAS/archive/v0.3.33.tar.gz"
OB_SHA256 = "6761af1d9f5d353ab4f0b7497be2643313b36c8f31caec0144bfef198e71e6ab"
OB_COMMIT = "62bcfb0dc9f1cfa685fc04135c50e2780c303137"           # tag v0.3.33
JPEG_URLS = ["https://downloads.sourceforge.net/project/libjpeg-turbo/1.5.3/libjpeg-turbo-1.5.3.tar.gz",
             "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/1.5.3/libjpeg-turbo-1.5.3.tar.gz"]
JPEG_SHA256 = "b24890e2bb46e12e72a79f7e965f409f4e16466d00e1dd15d93d73ee6b592523"   # the same from both
BUILD_TAG = "100"
TAG = "py3-none-android_24_x86_64"
SYSTEM_LIBS = {"libc.so", "libm.so", "libdl.so"}

HERE = Path(__file__).resolve().parent
ANDROID_DIR = HERE.parent
WORK = ANDROID_DIR / "build" / "x86_64-libs"
OUT = ANDROID_DIR / "wheels"

PACKAGES = [
    # (wheel name, wheel version, folder in WORK, library and its SONAME, license file, summary)
    ("chaquopy_openblas", "0.2.20+openblas0.3.33", "openblas", "libopenblas.so", "LICENSE",
     "OpenBLAS 0.3.33 (NOFORTRAN), labeled to satisfy chaquopy-openblas==0.2.20"),
    ("chaquopy_libgfortran", "4.9+none", None, None, None,
     "Empty: the OpenBLAS above needs no Fortran runtime; satisfies chaquopy-libgfortran==4.9"),
    ("chaquopy_libjpeg", "1.5.3", "libjpeg", "libjpeg_chaquopy.so", "LICENSE.md", ""),
]


def dynamic_strings(data: bytes):
    """(SONAME, [NEEDED]) of a 64-bit little-endian ELF shared library."""
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    loads, dyn = [], None
    for i in range(phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", data, phoff + i * phentsize)
        if p_type == 1:                                           # PT_LOAD
            loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == 2:                                         # PT_DYNAMIC
            dyn = (p_offset, p_filesz)

    def offset(vaddr):
        for va, off, size in loads:
            if va <= vaddr < va + size:
                return off + vaddr - va
        raise ValueError("address not in a LOAD segment")

    entries = [struct.unpack_from("<qQ", data, dyn[0] + i) for i in range(0, dyn[1], 16)]
    strtab = offset(next(v for t, v in entries if t == 5))     # DT_STRTAB

    def name(v):
        return data[strtab + v:data.index(b"\0", strtab + v)].decode()
    soname = next((name(v) for t, v in entries if t == 14), None)      # DT_SONAME
    return soname, [name(v) for t, v in entries if t == 1]           # DT_NEEDED


def record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return "%s,sha256=%s,%d" % (name, digest, len(data))


def check_lib(path: Path) -> bytes:
    data = path.read_bytes()
    al = alignments(data)
    if not al or min(al) < 16384 or struct.unpack_from("<H", data, 0x12)[0] != 62:     # EM_X86_64
        sys.exit("%s: not a 16 KB aligned x86_64 library (alignment %s)" % (path, al))
    so, needed = dynamic_strings(data)
    if so != path.name or set(needed) - SYSTEM_LIBS:
        sys.exit("%s: SONAME %s, NEEDED %s" % (path, so, needed))
    print("%s: %d bytes, sha256 %s, alignment %d, NEEDED %s" % (path.name, len(data), hashlib.sha256(data).hexdigest(), min(al),
                                                             ", ".join(needed)))
    return data


def pack(wheel, version, folder, lib, license_name, summary):
    files = {}
    if folder:
        root = WORK / folder
        files["chaquopy/lib/" + lib] = check_lib(root / "lib" / lib)
        for p in sorted((root / "include").rglob("*")):
            if p.is_file():
                files["chaquopy/include/" + p.relative_to(root / "include").as_posix()] = p.read_bytes()
    distinfo = "%s-%s.dist-info" % (wheel, version)
    if license_name:
        files[distinfo + "/" + license_name] = (WORK / folder / license_name).read_bytes()
    files[distinfo + "/METADATA"] = ("Metadata-Version: 1.2\nName: %s\nVersion: %s\nSummary: %s\nDownload-URL: \n"
                                     % (wheel.replace("_", "-"), version, summary)).encode()
    files[distinfo + "/WHEEL"] = ("Wheel-Version: 1.0\nRoot-Is-Purelib: false\nGenerator: khrecast build_x86_64_wheels.py\n"
                                  "Build: %s\nTag: %s\n" % (BUILD_TAG, TAG)).encode()
    files[distinfo + "/RECORD"] = ("\n".join([record_line(n, d) for n, d in files.items()] + [distinfo + "/RECORD,,"])
                                   + "\n").encode()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("%s-*-%s-%s.whl" % (wheel, BUILD_TAG, TAG)):        # an earlier labeling of the same package
        old.unlink()
    whl = OUT / ("%s-%s-%s-%s.whl" % (wheel, version, BUILD_TAG, TAG))
    with zipfile.ZipFile(whl, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            info = zipfile.ZipInfo(n, date_time=(2018, 5, 2, 0, 0, 0))    # fixed dates: the same input gives the same wheel
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, d)
    print("  ->", whl, "(sha256 %s)" % hashlib.sha256(whl.read_bytes()).hexdigest())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=default_cache())
    ap.add_argument("--keep", action="store_true", help="leave Docker running and the image in place")
    ap.add_argument("--pack-only", action="store_true", help="only pack the wheels again from the last build in android/build")
    a = ap.parse_args()
    if not a.pack_only:
        a.cache.mkdir(parents=True, exist_ok=True)
        fetch_source(OB_URL, a.cache / "OpenBLAS-0.3.33.tar.gz", OB_SHA256, OB_COMMIT, "OpenBLAS 0.3.33")
        for url in JPEG_URLS:
            try:
                fetch(url, a.cache / "libjpeg-turbo-1.5.3.tar.gz", {"sha256": JPEG_SHA256})
                break
            except (OSError, SystemExit) as e:
                print("  failed:", e)
        else:
            sys.exit("Could not download libjpeg-turbo 1.5.3 with the expected SHA-256")
        fetch_ndk(a.cache)
        run_in_container(HERE / "build_x86_64_libs_android.sh", [], a.cache, WORK, a.keep)
    for p in PACKAGES:
        pack(*p)


if __name__ == "__main__":
    main()
