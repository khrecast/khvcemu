"""Python side of the Android app: runs the unmodified khvcemu core inside Chaquopy.

Two uses:
* run_benchmark(...): the spike benchmark (android/spike/bench_headless.py, staged next to this file by the Gradle
  task stagePython), used by BenchActivity.
* start_game(...) and the small calls after it: the real game in real time on a Python thread (a reduced version of the
  desktop front end's loop: no autosave, no Wonderland pages, no quit prompt). The Java side polls
  frame_count()/frame_bytes() to draw the picture, sends key(name, down) for touches, and pulls sound with
  audio_read(frames) (the core mixes into a khvcemu.pcmmixer.PcmMixer; an Android AudioTrack plays what it returns).
"""
import collections
import contextlib
import importlib
import io
import os
import sys
import threading
import time


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


# ---------------------------------------------------------------------------------------------- the benchmark
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


# ---------------------------------------------------------------------------------------------- the game
AUDIO_RATE = 22050          # the core's own rate (khvcemu.midi_synth.RATE): mono, Android resamples it


class _Game:
    """The core running in real time on its own thread. The Java side only calls the small functions below."""

    def __init__(self, native_lib_dir, game_dir, data_dir):
        _prepare_unicorn(native_lib_dir)
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        from khvcemu.keys import AVK
        from khvcemu.pcmmixer import PcmMixer
        from khvcemu.runtime import Emulator
        self.AVK = AVK
        self.game_dir = game_dir
        self.mixer = PcmMixer(AUDIO_RATE, 1)
        self.audio_blocks = 0
        self.last_frames = 0
        self.last_status_at = time.monotonic()
        self.audio_peak = 0
        self.emu = Emulator(game_dir, data_dir, realtime=True, audio=True, audio_mixer=self.mixer, log=self._log,
                             frame_locked_clock=True)      # 25 fps when the phone keeps up (see Emulator.__init__)
        self.stop_flag = False
        self.want_paused = False
        self.paused_at = None          # monotonic time the loop paused the game clock, else None
        self.error = ""
        self.taps = collections.deque()      # (x, y) taps on the game's picture, in game pixels, from the Java side
        self.key_script = []                 # [due (monotonic), "down" or "up", avk]: key presses a tap asked for
        self.thread = threading.Thread(target=self._run, name="recast-core", daemon=True)

    @staticmethod
    def _log(line):
        print("[core]", line, flush=True)

    def _run(self):
        emu = self.emu
        prof = None
        t_begin = time.monotonic()
        # diagnostics: a file called profile_flag in the app's files folder makes the core thread profile itself
        # from 20 s to 35 s after the start and print the busiest functions to logcat (tag python.stdout)
        profile_wanted = os.path.exists(os.path.join(os.path.dirname(self.game_dir), "profile_flag"))
        try:
            emu.start()
            while not self.stop_flag:
                if profile_wanted:
                    age = time.monotonic() - t_begin
                    if prof is None and 20 <= age < 35:
                        import cProfile
                        prof = cProfile.Profile()
                        prof.enable()
                    elif prof is not None and age >= 35:
                        prof.disable()
                        import pstats
                        out = io.StringIO()
                        pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(28)
                        print("[profile]", out.getvalue(), flush=True)
                        prof, profile_wanted = None, False
                if emu.exit_requested:                             # the game asked to quit (as the desktop loop ends)
                    self._log("the game asked to exit")
                    break
                if self.want_paused != (self.paused_at is not None):
                    if self.want_paused:                           # hold the game clock still, let go of every key
                        for avk in sorted(emu.keys_held):
                            emu.key_up(avk)
                        self.paused_at = time.monotonic()
                        self.mixer.paused = True                   # sound is held too
                        self._log("paused (the app is not in the foreground); game clock %d ms" % emu.clock_ms())
                    else:                                          # the clock continues where it stopped
                        held = time.monotonic() - self.paused_at
                        emu._t0 += held
                        self.paused_at = None
                        self.mixer.paused = False
                        self._log("resumed after %.1f s; game clock %d ms" % (held, emu.clock_ms()))
                if self.paused_at is not None:
                    self.taps.clear()
                    self.key_script.clear()
                    time.sleep(0.02)
                    continue
                self._handle_taps()
                emu.run_due()
                due = emu.next_due()
                wait = 0.002 if due is None else (due - emu.clock_ms()) / 1000
                if wait > 0.001:
                    time.sleep(min(wait, 0.005))
        except BaseException as exc:                               # show it in the app instead of dying silently
            import traceback
            traceback.print_exc()
            self.error = repr(exc)
        finally:
            try:
                emu.stop()
                emu.playtime.save()
            except Exception:
                pass


    def _handle_taps(self):
        """On the core thread, so what the game has drawn is not changing underneath: turn each tap on the picture into
        the keys the tapped button stands for (khvcemu/tapmap.py), and press them a little apart."""
        from khvcemu import tapmap
        emu = self.emu
        while self.taps:
            x, y = self.taps.popleft()
            display = emu.display
            if emu.last_frame is not None:
                display.build_overlay(emu.last_frame)        # keeps only the strings still on screen
            items = display.__dict__.get("text_items", [])
            keys = tapmap.resolve_tap(x, y, items, emu.last_frame)
            self._log("tap (%d, %d) -> %s" % (x, y, keys or "nothing"))
            due = time.monotonic()
            for k in keys:
                avk = self.AVK[k]
                self.key_script.append([due, "down", avk])
                self.key_script.append([due + 0.08, "up", avk])
                due += 0.16
        if self.key_script:
            now = time.monotonic()
            pressed = set()                              # a key's release waits for the next pass, so the game sees it held
            for step in [s for s in self.key_script if s[0] <= now]:
                if step[1] == "up" and step[2] in pressed:
                    continue
                self.key_script.remove(step)
                if step[1] == "down":
                    pressed.add(step[2])
                (emu.key_down if step[1] == "down" else emu.key_up)(step[2])


_game = None


_start_lock = threading.Lock()


def start_game(native_lib_dir, game_dir, data_dir):
    """Start the game thread (once)."""
    global _game
    with _start_lock:
        if _game is not None and _game.stop_flag:                   # told to stop (Back, then reopened quickly):
            _game.thread.join(5)                                    # let it finish saving before a new one starts
        if _game is None or _game.stop_flag or not _game.thread.is_alive():   # not started, stopping or ended: start afresh
            os.makedirs(data_dir, exist_ok=True)
            game = _Game(native_lib_dir, game_dir, data_dir)
            game.thread.start()
            _game = game
    return True


def stop():
    """Ask the game thread to end (the app is closing for good)."""
    if _game is not None:
        _game.stop_flag = True


def frame_count():
    """How many frames the game has drawn so far (cheap: the Java side polls this)."""
    return 0 if _game is None else _game.emu.frames


def frame_bytes():
    """The latest 176x220 picture as little-endian RGB565 bytes (what Android's RGB_565 bitmap takes), or empty."""
    if _game is None or _game.emu.last_frame is None:
        return b""
    import numpy as np
    return np.ascontiguousarray(_game.emu.last_frame, dtype="<u2").tobytes()


def key(name, down):
    """A touch control was pressed or released: name is a phone key from khvcemu.keys.AVK (UP, SELECT, STAR, 0...)."""
    if _game is None or _game.paused_at is not None or _game.want_paused or not _game.thread.is_alive():
        return
    avk = _game.AVK.get(name)
    if avk is None:
        return
    if down:
        _game.emu.key_down(avk)
    else:
        _game.emu.key_up(avk)


def audio_read(frames):
    """The next `frames` mono 16-bit samples of the game's sound as bytes (silence when there is none)."""
    if _game is None:
        return bytes(frames * 2)
    block = _game.mixer.read(frames)
    # measurement (nobody can hear the sound from here): the loudest sample handed out, logged every ~5 s
    import numpy as np
    _game.audio_blocks += 1
    _game.audio_peak = max(_game.audio_peak, int(np.abs(np.frombuffer(block, "<i2")).max(initial=0)))
    if _game.audio_blocks % 100 == 0:
        print("[audio] %d blocks, loudest sample in the last 100: %d" % (_game.audio_blocks, _game.audio_peak), flush=True)
        _game.audio_peak = 0
    return block


def tap(x, y):
    """A tap on the game's picture (game pixels, 176 x 220): handled on the core thread (see _Game._handle_taps)."""
    if _game is not None and _game.paused_at is None and not _game.want_paused and _game.thread.is_alive():
        _game.taps.append((float(x), float(y)))


def pause():
    if _game is not None:
        _game.want_paused = True


def resume():
    if _game is not None:
        _game.want_paused = False


def status():
    """One line for the on-screen debug text."""
    if _game is None:
        return "game not started"
    emu = _game.emu
    state = "stopped" if not _game.thread.is_alive() else ("paused" if _game.want_paused else "running")
    now = time.monotonic()
    fps = (emu.frames - _game.last_frames) / max(0.001, now - _game.last_status_at)    # since the previous call
    _game.last_frames, _game.last_status_at = emu.frames, now
    return "%s  %.0f fps  frames %d  faults %d%s" % (state, fps, emu.frames, emu.faults,
                                                      ("  ERROR " + _game.error) if _game.error else "")
