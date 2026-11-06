"""Lists the native libraries in an APK (and inside Chaquopy's packed .imy archives) whose ELF LOAD segments are aligned to
less than 16 KB. Android 15 and later phones with 16 KB memory pages need 16 KB alignment.

    python android/tools/check_page_alignment.py android/app/build/outputs/apk/release/app-release-unsigned.apk
"""
import io
import struct
import sys
import zipfile


def alignments(data: bytes):
    """The alignment of each LOAD segment of a 64-bit ELF file, or None when it is not one."""
    if data[:4] != b"\x7fELF" or data[4] != 2:
        return None
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    out = []
    for i in range(phnum):
        off = phoff + i * phentsize
        if struct.unpack_from("<I", data, off)[0] == 1:                      # PT_LOAD
            out.append(struct.unpack_from("<Q", data, off + 0x30)[0])
    return out


def scan(zf: zipfile.ZipFile, prefix: str, report: list):
    for info in zf.infolist():
        name = info.filename
        if name.endswith((".so",)) or ".so." in name:
            al = alignments(zf.read(info))
            if al is not None:
                report.append((prefix + name, min(al) if al else 0))
        elif name.endswith(".imy"):
            try:
                scan(zipfile.ZipFile(io.BytesIO(zf.read(info))), prefix + name + "!", report)
            except zipfile.BadZipFile:
                pass


if __name__ == "__main__":
    report: list = []
    scan(zipfile.ZipFile(sys.argv[1]), "", report)
    low = [(n, a) for n, a in report if a < 16384]
    print("%d native libraries, %d below 16 KB alignment" % (len(report), len(low)))
    for name, a in low:
        print("  %6d  %s" % (a, name))
    sys.exit(1 if low else 0)
