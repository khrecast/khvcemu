#!/data/data/com.termux/files/usr/bin/sh
# Builds libunicorn.so (the ARM emulation library the Re:Cast app loads) from Unicorn's own source, on an arm64 Android phone
# with Termux. The result is NOT committed: copy it to the PC (C:\Android\libs\arm64-v8a\libunicorn.so) and
# android/fetch_unicorn.ps1 puts it into the app.
#
#   sh android/build_unicorn_termux.sh        (from the repository folder, copied to the phone's Downloads)
#
# What it does, so the build can be repeated and checked:
#   * Unicorn 2.1.4 from github.com/unicorn-engine/unicorn, tag 2.1.4 (the tag is checked out afresh each time)
#   * ARM guest only (-DUNICORN_ARCH=arm), Release, no tests
#   * the linker is asked for 16 KB page alignment (-Wl,-z,max-page-size=16384), as the app needs for 16 KB phones
#   * it prints the file's size and SHA-256, and the alignment of its LOAD segments
# The published notes (android/NOTES.md, chunk 3) record the hash of the library the app was built with first. A rebuild
# with another Termux compiler is not byte-identical: compare behavior (the app's tests), not the hash. NOT RUN since it
# was written from the steps that were: the first run on a phone is the check.
set -e
cd "$HOME"
pkg upgrade -y
pkg install -y clang cmake make git python
rm -rf unicorn
git clone --depth 1 --branch 2.1.4 https://github.com/unicorn-engine/unicorn.git
git -C unicorn describe --tags
cmake -S unicorn -B unicorn/build -DCMAKE_BUILD_TYPE=Release -DUNICORN_ARCH=arm -DUNICORN_BUILD_TESTS=OFF \
      -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384"
cmake --build unicorn/build -j"$(nproc)"
LIB="$HOME/unicorn/build/libunicorn.so"
ls -l "$LIB"
sha256sum "$LIB"
python - "$LIB" <<'PY'
import struct, sys
d = open(sys.argv[1], "rb").read()
phoff = struct.unpack_from("<Q", d, 0x20)[0]
size, num = struct.unpack_from("<HH", d, 0x36)
al = [struct.unpack_from("<Q", d, phoff + i * size + 0x30)[0] for i in range(num) if struct.unpack_from("<I", d, phoff + i * size)[0] == 1]
print("LOAD segment alignment:", al, "-> OK for 16 KB pages" if al and min(al) >= 16384 else "-> TOO SMALL for 16 KB pages")
PY
mkdir -p "$HOME/storage/downloads" 2>/dev/null || true
cp "$LIB" "$HOME/storage/downloads/libunicorn.so" 2>/dev/null && echo "copied to Downloads/libunicorn.so" || echo "copy it from $LIB (run termux-setup-storage first for Downloads)"
