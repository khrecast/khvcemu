#!/bin/sh
# Builds the two libraries of Chaquopy's x86_64 packages that are aligned to 4 KB pages (a 16 KB-page device cannot load them)
# again with the official Linux NDK r28c, 16 KB aligned, inside a throwaway Debian container. Run it through
# android/tools/build_x86_64_wheels.py, which downloads and checks the inputs, runs this script and packs the results as wheels:
#
#   OpenBLAS 0.3.33 (for numpy): Chaquopy's own current recipe (chaquopy-openblas build.sh): no Fortran, so LAPACK is built from
#     C and libgfortran is no longer needed; single-threaded with locking, NUM_THREADS=8, TARGET=NEHALEM (the x86_64 ABI's
#     instruction set). Chaquopy's index still has only 0.2.20 (with libgfortran 4.9), both 4 KB aligned for x86_64.
#   libjpeg-turbo 1.5.3 (for Pillow): the same version and options as Chaquopy's chaquopy-libjpeg (no TurboJPEG, no SIMD,
#     SONAME libjpeg_chaquopy.so).
#
#   /cache/android-ndk-r28c-linux.zip, /cache/OpenBLAS-0.3.33.tar.gz, /cache/libjpeg-turbo-1.5.3.tar.gz   (checked by SHA-256)
#   /out/openblas/{lib,include,LICENSE}, /out/libjpeg/{lib,include,LICENSE.md}                           (the results)
#
# API level 24 (Android 7, the app's minSdk); LOAD segments 16 KB aligned (NDK r28's default, and asked for explicitly).
set -eu

NDK_ZIP=/cache/android-ndk-r28c-linux.zip
NDK_SHA256=dfb20d396df28ca02a8c708314b814a4d961dc9074f9a161932746f815aa552f
NDK_REVISION=28.2.13676358
OB_TGZ=/cache/OpenBLAS-0.3.33.tar.gz
OB_SHA256=6761af1d9f5d353ab4f0b7497be2643313b36c8f31caec0144bfef198e71e6ab
JPEG_TGZ=/cache/libjpeg-turbo-1.5.3.tar.gz
JPEG_SHA256=b24890e2bb46e12e72a79f7e965f409f4e16466d00e1dd15d93d73ee6b592523
API=24

export DEBIAN_FRONTEND=noninteractive
# make and a host C compiler (OpenBLAS builds its getarch tool for the build machine), unzip for the NDK; the output is shown
# only when apt-get fails
{ apt-get update && apt-get install -y --no-install-recommends make gcc libc6-dev unzip ca-certificates; } >/tmp/apt.log 2>&1 \
    || { tail -n 40 /tmp/apt.log; echo "apt-get failed"; exit 1; }

echo "$NDK_SHA256  $NDK_ZIP" | sha256sum -c -
echo "$OB_SHA256  $OB_TGZ" | sha256sum -c -
echo "$JPEG_SHA256  $JPEG_TGZ" | sha256sum -c -

mkdir -p /work
unzip -q "$NDK_ZIP" -d /work
NDK=/work/android-ndk-r28c
grep -q "^Pkg.Revision = $NDK_REVISION\$" "$NDK/source.properties" || { echo "NDK is not $NDK_REVISION"; exit 1; }
BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
CC_X86="$BIN/x86_64-linux-android$API-clang"
echo "== NDK $NDK_REVISION, $("$CC_X86" --version | head -n 1)"
LDF="-Wl,-z,max-page-size=16384"

report() {
    echo "   $1: size $(stat -c %s "$1") bytes, sha256 $(sha256sum "$1" | cut -d ' ' -f 1)"
    echo "   LOAD alignment: $("$BIN/llvm-readelf" -lW "$1" | awk '$1 == "LOAD" { printf "%s ", $NF }')"
    "$BIN/llvm-readelf" -dW "$1" | grep -E "NEEDED|SONAME|RUNPATH|RPATH" | sed 's/^/  /'
}

echo "== OpenBLAS 0.3.33 for x86_64 (API $API)"
tar xzf "$OB_TGZ" -C /work
cd /work/OpenBLAS-0.3.33
# CROSS=1: do not run OpenBLAS's tests (they are Android programs and cannot run in this container)
make -j"$(nproc)" CC="$CC_X86" HOSTCC=gcc AR="$BIN/llvm-ar" RANLIB="$BIN/llvm-ranlib" LDFLAGS="$LDF" \
    CROSS=1 NOFORTRAN=1 USE_THREAD=0 USE_LOCKING=1 NUM_THREADS=8 TARGET=NEHALEM >/work/openblas.build.log 2>&1 \
    || { tail -n 60 /work/openblas.build.log; exit 1; }
make CC="$CC_X86" HOSTCC=gcc CROSS=1 NOFORTRAN=1 USE_THREAD=0 USE_LOCKING=1 NUM_THREADS=8 TARGET=NEHALEM \
    PREFIX=/work/openblas-install install >/work/openblas.install.log 2>&1 || { tail -n 40 /work/openblas.install.log; exit 1; }
grep -E "^ (OS|Architecture|BINARY|C compiler|Library Name|Supporting multiple|Single threaded|Use C LAPACK)" \
    /work/openblas.build.log | head -n 12 || true
mkdir -p /out/openblas/lib
rm -rf /out/openblas/include
cp -r /work/openblas-install/include /out/openblas/include
REAL=$(find /work/openblas-install/lib -maxdepth 1 -name 'libopenblas*.so' -type f | head -n 1)
"$BIN/llvm-strip" --strip-unneeded -o /out/openblas/lib/libopenblas.so "$REAL"
cp LICENSE /out/openblas/LICENSE
report /out/openblas/lib/libopenblas.so

echo "== libjpeg-turbo 1.5.3 for x86_64 (API $API)"
cd /work
tar xzf "$JPEG_TGZ" -C /work
cd /work/libjpeg-turbo-1.5.3
# Chaquopy's soname.patch: the SONAME libjpeg_chaquopy.so, so it cannot clash with a system copy (Pillow links to that name)
sed -i "s/^  soname_spec='\$libname\$release\$shared_ext'\$/  soname_spec='\${libname}_chaquopy\$shared_ext'/" configure
[ "$(grep -c "soname_spec='\${libname}_chaquopy\$shared_ext'" configure)" = 1 ] || { echo "SONAME edit failed"; exit 1; }
CC="$CC_X86" AR="$BIN/llvm-ar" RANLIB="$BIN/llvm-ranlib" STRIP="$BIN/llvm-strip" LDFLAGS="$LDF" \
    ./configure --host=x86_64-linux-android --without-turbojpeg --without-simd --prefix=/work/jpeg-install \
    >/work/jpeg.configure.log 2>&1 || { tail -n 40 /work/jpeg.configure.log; exit 1; }
make -j"$(nproc)" >/work/jpeg.build.log 2>&1 || { tail -n 40 /work/jpeg.build.log; exit 1; }
make install >/work/jpeg.install.log 2>&1 || { tail -n 40 /work/jpeg.install.log; exit 1; }
LIBDIR=$(ls -d /work/jpeg-install/lib*/ | head -n 1)
mkdir -p /out/libjpeg/lib
rm -rf /out/libjpeg/include
cp -r /work/jpeg-install/include /out/libjpeg/include
"$BIN/llvm-strip" --strip-unneeded -o /out/libjpeg/lib/libjpeg_chaquopy.so "$LIBDIR/libjpeg.so"
cp LICENSE.md /out/libjpeg/LICENSE.md
report /out/libjpeg/lib/libjpeg_chaquopy.so
echo "== done"
