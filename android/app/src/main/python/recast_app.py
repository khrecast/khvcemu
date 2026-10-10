"""Python side of the Android spike app: runs the headless core inside Chaquopy.

The Java activity calls run_benchmark(...) on a background thread and shows what it returns. The benchmark
is android/spike/bench_headless.py (staged next to this file by the Gradle task stagePython): it boots the
unmodified khvcemu core on a virtual clock and prints one JSON line per measurement.
"""
import contextlib
import importlib
import io
import os
import sys


class _Tee(io.StringIO):
    """A StringIO that also forwards every write to another stream (Chaquopy sends sys.stdout to logcat)."""

    def __init__(self, other):
        super().__init__()
        self.other = other

    def write(self, text):
        try:
            self.other.write(text)
        except Exception:
            pass
        return super().write(text)

    def flush(self):
        try:
            self.other.flush()
        except Exception:
            pass


def _prepare_unicorn(native_lib_dir):
    """Let the (unmodified) Unicorn Python binding find libunicorn.so.

    It looks in $LIBUNICORN_PATH first, but it also asks importlib.resources for its own package folder and wraps
    the answer in pathlib.Path, which fails on Chaquopy's AssetPath. Answer that one question with a real folder."""
    import importlib.resources
    import pathlib
    os.environ["LIBUNICORN_PATH"] = native_lib_dir        # where the app's libunicorn.so was installed
    original = importlib.resources.files

    def files(package):
        if str(getattr(package, "__name__", package)) == "unicorn":
            return pathlib.Path(native_lib_dir)
        return original(package)

    importlib.resources.files = files


def run_benchmark(mode, native_lib_dir, game_dir):
    """Run bench_headless.py <mode> (boot, world or audio); returns everything it printed."""
    _prepare_unicorn(native_lib_dir)
    # if the run stalls for 40 s, write where every Python thread is waiting into files/stall_<mode>.txt (read it with
    # adb run-as; an empty file means no stall). Cancelled and closed when the run ends.
    import faulthandler
    stall = open(os.path.join(os.path.dirname(game_dir), "stall_%s.txt" % mode), "w")
    faulthandler.dump_traceback_later(40, repeat=False, file=stall)
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    out = _Tee(sys.__stdout__)                              # keep the text for the screen and also send it to logcat as it comes
    old_argv = sys.argv
    sys.argv = ["bench_headless.py", "--root", game_dir, "--code", game_dir, mode]
    sys.modules.pop("bench_headless", None)               # the script runs when imported, so import it afresh
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                importlib.import_module("bench_headless")
            except SystemExit:
                pass
            except BaseException as exc:                  # show the failure in the app instead of crashing it
                import traceback
                traceback.print_exc()
                print("FAILED:", repr(exc))
    finally:
        sys.argv = old_argv
        faulthandler.cancel_dump_traceback_later()
        stall.close()
    return out.getvalue()
