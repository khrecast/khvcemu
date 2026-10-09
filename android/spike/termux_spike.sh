#!/data/data/com.termux/files/usr/bin/sh
# Spike 0: the Re:Cast core's speed on this phone, in Termux. UNTESTED so far (written on a PC without a
# phone): if a step fails, send the last 20 lines of the output.
#
#   cd ~/recast_spike && sh android/spike/termux_spike.sh [boot|world|audio|all]
#
# It installs a few Termux packages, builds Unicorn (ARM only) from source with the phone's own compiler,
# then runs android/spike/bench_headless.py exactly as on the desktop. Results go to ~/spike_results.txt.
set -e
WHAT="${1:-all}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"        # the recast_spike folder
OUT="$HOME/spike_results.txt"

echo "== 1/4 packages (python, numpy, a compiler, cmake, git)"
# If Termux asks about mirrors or a config file, answer the defaults (or run termux-change-repo first).
pkg update -y
pkg install -y python python-numpy clang cmake make git

echo "== 2/4 Unicorn (ARM only), built from source"
cd "$HOME"
# If this step was interrupted earlier, delete ~/unicorn (rm -rf ~/unicorn) and run the script again.
if [ ! -d unicorn ]; then
  git clone --depth 1 --branch 2.1.4 https://github.com/unicorn-engine/unicorn.git
fi
if [ ! -f unicorn/build/libunicorn.so ]; then
  cmake -S unicorn -B unicorn/build -DCMAKE_BUILD_TYPE=Release -DUNICORN_ARCH=arm -DUNICORN_BUILD_TESTS=OFF
  # a few minutes; the phone gets warm. If it runs out of memory, use -j2.
  cmake --build unicorn/build -j"$(nproc)"
fi
# The Python binding is pure Python over ctypes: use it from the source tree, no pip build (its sdist fails on Termux).
export PYTHONPATH="$HOME/unicorn/bindings/python"
export LIBUNICORN_PATH="$HOME/unicorn/build"
python -c "import unicorn; print('unicorn', unicorn.__version__)"

echo "== 3/4 about this phone"
{
  echo "== phone: $(getprop ro.product.manufacturer) $(getprop ro.product.model), Android $(getprop ro.build.version.release), SoC $(getprop ro.soc.model) $(getprop ro.board.platform)"
  echo "== cores: $(nproc), page size $(python -c 'import os; print(os.sysconf("SC_PAGESIZE"))'), python $(python -V 2>&1)"
  echo "== $(grep MemTotal /proc/meminfo), unicorn source: $(git -C "$HOME/unicorn" describe --tags 2>/dev/null || git -C "$HOME/unicorn" log -1 --oneline)"
  echo "== battery/thermal: keep the phone cool, on charge or above 50 percent, screen on, other apps closed"
  date
} | tee "$OUT"

echo "== 4/4 benchmark ($WHAT)"
run() {
  echo "-- $1" | tee -a "$OUT"
  python "$HERE/android/spike/bench_headless.py" --root "$HERE/game" --code "$HERE" "$@" 2>&1 | tee -a "$OUT"
}
export SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=dummy
case "$WHAT" in
  all) run boot; run world; run audio ;;
  *)   run "$WHAT" ;;
esac
echo "Done. Results are in $OUT (send it back: cat $OUT)."
