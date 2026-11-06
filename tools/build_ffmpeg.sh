#!/bin/sh
# Builds Re:Cast's small LGPL ffmpeg for the installers' six targets with zig as the cross compiler. Run by
# tools/build_ffmpeg.py inside a throwaway Debian container (not by hand):
#
#     sh /cache/scripts/build_ffmpeg.sh <ffmpeg tarball> <zig tarball> <target>...
#
# /cache (read-only) holds both tarballs, /out receives <target>/ffmpeg[.exe], LICENSE.txt and tools.txt. In /smoke and, if
# mounted, /selftest, every file in in/ is decoded by the two Linux builds (aarch64 under qemu-user) into <dir>/<target>/,
# with Re:Cast's own command lines (a .qcp file the way pmd.py pipes it in, anything else the way audio.py reads a file).
set -eu

FFMPEG_TAR="$1"; ZIG_TAR="$2"; shift 2

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# make for the build, xz for the tarballs, llvm-nm for configure's symbol check, qemu-user and the arm64 C library to run
# the aarch64 build here
apt-get install -y -qq --no-install-recommends make xz-utils llvm-14 qemu-user libc6-arm64-cross >/dev/null

mkdir -p /work/bin /work/src /work/zig /out
tar -xJf "/cache/$ZIG_TAR" -C /work/zig --strip-components=1
tar -xJf "/cache/$FFMPEG_TAR" -C /work/src --strip-components=1
ZIG=/work/zig/zig
export ZIG_GLOBAL_CACHE_DIR=/work/zig-cache ZIG_LOCAL_CACHE_DIR=/work/zig-cache SOURCE_DATE_EPOCH=0
printf '#!/bin/sh\nexec %s ar "$@"\n' "$ZIG" > /work/bin/ar
printf '#!/bin/sh\nexec %s ranlib "$@"\n' "$ZIG" > /work/bin/ranlib
printf '#!/bin/sh\nexec %s cc "$@"\n' "$ZIG" > /work/bin/host-cc
chmod +x /work/bin/*

{
    echo "zig $($ZIG version)"
    dpkg-query -W -f '${Package} ${Version}\n' make xz-utils llvm-14 qemu-user libc6-arm64-cross
} > /out/tools.txt
cp /work/src/COPYING.LGPLv2.1 /out/LICENSE.txt

# What Re:Cast reads (audio.py, music_preview.py, pmd.py): the game's QCELP sounds in a QCP file, WAV, and players'
# recordings in FLAC, MP3, Ogg Vorbis, Opus, AAC/M4A, ALAC, AIFF, WMA and WavPack; written out as 16-bit PCM to a pipe.
PROTOCOLS=file,pipe
DEMUXERS=aac,aiff,asf,flac,mov,mp3,ogg,qcp,wav,wv
DECODERS=qcelp,flac,mp3,mp3float,mp2,mp2float,vorbis,opus,aac,alac,wmav1,wmav2,wmapro,wmalossless,wavpack
DECODERS=$DECODERS,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_u8,pcm_s8
DECODERS=$DECODERS,pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_alaw,pcm_mulaw,adpcm_ima_wav,adpcm_ms
PARSERS=aac,flac,mpegaudio,opus,vorbis
FILTERS=abuffer,abuffersink,aformat,anull,aresample,atrim

build() {
    target="$1"
    case "$target" in
        windows-x64)   triple=x86_64-windows-gnu;      os=mingw32; arch=x86_64;  threads=w32threads; exe=ffmpeg.exe ;;
        windows-x86)   triple=x86-windows-gnu;         os=mingw32; arch=x86;     threads=w32threads; exe=ffmpeg.exe ;;
        macos-arm64)   triple=aarch64-macos.11.0;      os=darwin;  arch=aarch64; threads=pthreads;   exe=ffmpeg ;;
        macos-x86_64)  triple=x86_64-macos.10.15;      os=darwin;  arch=x86_64;  threads=pthreads;   exe=ffmpeg ;;
        linux-x86_64)  triple=x86_64-linux-gnu.2.28;   os=linux;   arch=x86_64;  threads=pthreads;   exe=ffmpeg ;;
        linux-aarch64) triple=aarch64-linux-gnu.2.28;  os=linux;   arch=aarch64; threads=pthreads;   exe=ffmpeg ;;
        *) echo "unknown target $target"; exit 2 ;;
    esac
    echo "=== $target ($triple)"
    # zig cc for the target. FFmpeg's configure adds two linker options to every program that zig's linker rejects, so
    # they are left out: -Wl,--pic-executable,-e,mainCRTStartup on Windows (zig already links a relocatable image that
    # starts at mainCRTStartup) and -Wl,-dynamic,-search_paths_first on macOS (zig's defaults).
    cat > "/work/bin/cc-$target" <<EOF
#!/bin/sh
for a do
    shift
    case "\$a" in
        -Wl,--pic-executable,-e,mainCRTStartup|-Wl,--pic-executable,-e,_mainCRTStartup|-Wl,-dynamic,-search_paths_first) ;;
        *) set -- "\$@" "\$a" ;;
    esac
done
exec $ZIG cc -target $triple "\$@"
EOF
    chmod +x "/work/bin/cc-$target"
    rm -rf "/work/build-$target"; mkdir -p "/work/build-$target"; cd "/work/build-$target"
    # LGPL only: no --enable-gpl, --enable-version3 or --enable-nonfree, and no external library (--disable-autodetect).
    # No assembly (plain C on every target: nothing extra to assemble, the same code everywhere; speed does not matter
    # for short sounds). Linked stripped by zig (-s), which also gives the macOS arm64 executable its ad-hoc signature;
    # FFmpeg's own strip step is off because stripping afterwards would break that signature.
    if ! /work/src/configure \
        --prefix=/work/inst-$target --enable-cross-compile --target-os=$os --arch=$arch \
        --cc=/work/bin/cc-$target --ld=/work/bin/cc-$target --host-cc=/work/bin/host-cc \
        --ar=/work/bin/ar --ranlib=/work/bin/ranlib --nm="llvm-nm-14 -g" --pkg-config=false \
        --extra-ldflags=-s \
        --disable-everything --disable-autodetect --disable-network --disable-doc --disable-ffplay \
        --disable-ffprobe --disable-avdevice --disable-swscale --disable-asm --disable-debug --disable-stripping \
        --enable-static --disable-shared --enable-$threads \
        --enable-protocol=$PROTOCOLS --enable-demuxer=$DEMUXERS --enable-decoder=$DECODERS \
        --enable-parser=$PARSERS --enable-filter=$FILTERS \
        --enable-muxer=pcm_s16le --enable-encoder=pcm_s16le > configure.out 2>&1; then
        tail -n 40 configure.out; tail -n 60 ffbuild/config.log; exit 1
    fi
    # configure finds sysctl() by linking alone, but zig's glibc and macOS headers have no <sys/sysctl.h> (glibc dropped
    # it in 2.32), which libavutil would then include. Without it, libavutil counts CPUs with sysconf() instead.
    if ! printf '#include <sys/sysctl.h>\n' | "/work/bin/cc-$target" -E -x c - > /dev/null 2>&1; then
        sed -i 's/^#define HAVE_SYSCTL 1$/#define HAVE_SYSCTL 0/; s/^#define HAVE_SYSCTLBYNAME 1$/#define HAVE_SYSCTLBYNAME 0/' config.h
        echo "no <sys/sysctl.h>: config.h has HAVE_SYSCTL 0 and HAVE_SYSCTLBYNAME 0"
    fi
    make -j"$(nproc)" "$exe" > make.out 2>&1 || { tail -n 60 make.out; exit 1; }
    mkdir -p "/out/$target"
    cp "$exe" "/out/$target/$exe"
    echo "built /out/$target/$exe"
}

decode_all() {
    # decode_all DIR TARGET COMMAND...: every file in DIR/in into DIR/TARGET/<name>.s16, with Re:Cast's command lines
    dir="$1"; target="$2"; shift 2
    [ -d "$dir/in" ] || return 0
    mkdir -p "$dir/$target"
    n=0
    for f in "$dir"/in/*; do
        name=$(basename "$f")
        case "$name" in
            *.qcp) "$@" -v error -f qcp -i pipe:0 -f s16le -ac 1 -ar 22050 pipe:1 < "$f" > "$dir/$target/$name.s16" ;;
            *)     "$@" -nostdin -v quiet -i "$f" -f s16le -ac 1 -ar 22050 pipe:1 > "$dir/$target/$name.s16" ;;
        esac || echo "$target: could not decode $name"
        n=$((n + 1))
    done
    echo "$target: decoded $n files into $dir/$target"
}

for t in "$@"; do
    build "$t"
done
# /smoke (always mounted by build_ffmpeg.py, which checks the results) and /selftest (only with --test-dir)
for t in "$@"; do
    case "$t" in
        linux-x86_64)  run="/out/$t/ffmpeg" ;;
        linux-aarch64) run="qemu-aarch64 -L /usr/aarch64-linux-gnu /out/$t/ffmpeg" ;;
        *) continue ;;
    esac
    $run -hide_banner -version | head -n 1
    for d in /smoke /selftest; do
        decode_all "$d" "$t" $run
    done
done
chmod -R a+rwX /out
for d in /smoke /selftest; do
    [ -d "$d" ] && chmod -R a+rwX "$d" || true
done
