#!/bin/sh
# Builds libunicorn.so (the ARM emulation library the Re:Cast app loads) for Android with the official Linux NDK, inside a
# throwaway Debian container. Run it through android/tools/build_unicorn_docker.py, which downloads and checks the inputs,
# puts an LF copy of this script into the cache folder and runs it in the container:
#
#   /cache/android-ndk-r28c-linux.zip   NDK r28c (28.2.13676358), checked by SHA-256 below
#   /cache/unicorn-2.1.4.tar.gz         Unicorn 2.1.4 source (GitHub tag archive), checked by SHA-256 below
#   /out/<abi>/libunicorn.so            the result, one per ABI
#
# Options as in android/build_unicorn_termux.sh: ARM guest only (-DUNICORN_ARCH=arm), Release, no tests, LOAD segments aligned
# to 16 KB (-Wl,-z,max-page-size=16384). API level 24 (Android 7, the app's minSdk plan). The library is stripped of symbols it
# does not need to export. Usage inside the container: sh build_unicorn_android.sh <abi> [<abi> ...]   (arm64-v8a, x86_64)
set -eu

NDK_ZIP=/cache/android-ndk-r28c-linux.zip
NDK_SHA256=dfb20d396df28ca02a8c708314b814a4d961dc9074f9a161932746f815aa552f
NDK_REVISION=28.2.13676358
UC_TGZ=/cache/unicorn-2.1.4.tar.gz
UC_SHA256=ea8863f095a0136388694e5a6063afd9bb7650e30243dd6251af59c5ce5601f4
API=24

if [ "$#" -eq 0 ]; then set -- arm64-v8a x86_64; fi

export DEBIAN_FRONTEND=noninteractive
# QEMU's configure needs strings (binutils) and pkg-config; the output is shown only when apt-get fails
{ apt-get update && apt-get install -y --no-install-recommends cmake ninja-build make unzip binutils pkg-config ca-certificates; } \
    >/tmp/apt.log 2>&1 || { tail -n 40 /tmp/apt.log; echo "apt-get failed"; exit 1; }
echo "== host tools: $(cmake --version | head -n 1), ninja $(ninja --version)"

echo "$NDK_SHA256  $NDK_ZIP" | sha256sum -c -
echo "$UC_SHA256  $UC_TGZ" | sha256sum -c -

mkdir -p /work
unzip -q "$NDK_ZIP" -d /work
NDK=/work/android-ndk-r28c
grep -q "^Pkg.Revision = $NDK_REVISION\$" "$NDK/source.properties" || { echo "NDK is not $NDK_REVISION"; cat "$NDK/source.properties"; exit 1; }
BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
echo "== NDK $NDK_REVISION, $("$BIN/clang" --version | head -n 1)"

tar xzf "$UC_TGZ" -C /work
SRC=/work/unicorn-2.1.4
[ -f "$SRC/CMakeLists.txt" ] || { echo "no Unicorn source in $UC_TGZ"; exit 1; }

for ABI in "$@"; do
    case "$ABI" in
        arm64-v8a|x86_64) ;;
        *) echo "unknown ABI $ABI (arm64-v8a or x86_64)"; exit 1 ;;
    esac
    echo "== Unicorn 2.1.4 for $ABI (API $API)"
    B="/work/build-$ABI"
    cmake -S "$SRC" -B "$B" -G Ninja \
        -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" -DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON \
        -DCMAKE_BUILD_TYPE=Release -DUNICORN_ARCH=arm -DUNICORN_BUILD_TESTS=OFF \
        -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384" >"$B.configure.log" 2>&1 \
        || { tail -n 60 "$B.configure.log"; exit 1; }
    # Unicorn's CMake runs QEMU's configure script and does not stop when that fails: check its result here
    if [ ! -s "$B/config-host.h" ] || ! grep -q CONFIG_ "$B/config-host.h"; then
        echo "QEMU's configure failed:"; tail -n 40 "$B.configure.log"; tail -n 40 "$B/config.log" 2>/dev/null; exit 1
    fi
    cmake --build "$B" -j"$(nproc)" >"$B.build.log" 2>&1 || { tail -n 60 "$B.build.log"; exit 1; }
    mkdir -p "/out/$ABI"
    "$BIN/llvm-strip" --strip-unneeded -o "/out/$ABI/libunicorn.so" "$B/libunicorn.so"
    LIB="/out/$ABI/libunicorn.so"
    echo "   size $(stat -c %s "$LIB") bytes"
    echo "   sha256 $(sha256sum "$LIB" | cut -d ' ' -f 1)"
    echo "   LOAD alignment: $("$BIN/llvm-readelf" -lW "$LIB" | awk '$1 == "LOAD" { printf "%s ", $NF }')"
    "$BIN/llvm-readelf" -dW "$LIB" | grep -E "NEEDED|SONAME|RUNPATH|RPATH" | sed 's/^/  /'
done
echo "== done"
