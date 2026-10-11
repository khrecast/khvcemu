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

    def __init__(self, native_lib_dir, game_dir, data_dir, start_world="", speed_off="", frame_lock=True, music="",
                 leaderboard="", font_size=11, music_files="", hires_text=False, live_softkeys=True):
        _prepare_unicorn(native_lib_dir)
        _install_decoder()
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
        from khvcemu import music_settings, swerve_patch
        off = {x.strip() for x in str(speed_off).split(",") if x.strip()}        # the Options screen's speed switches
        patches = [n for n in swerve_patch.NAMES if n not in off]
        self.emu = Emulator(game_dir, data_dir, realtime=True, audio=True, audio_mixer=self.mixer, log=self._log,
                             speed_patches=patches, music=music_settings.parse(music, strict=False),
                             music_files=_music_files(music_files),   # the player's recordings that replace tunes (Sound screen)
                             frame_locked_clock=bool(frame_lock))     # steady 25 fps when the phone keeps up (Emulator.__init__)
        if start_world:                # "Start at a world": the world's starting save replaces the game save (a backup is kept)
            from khvcemu import chapters
            try:
                chapters.install_save(self.emu, start_world)
            except (SystemExit, OSError) as e:
                self._log("start at %s failed: %s" % (start_world, e))
        self.sharp = bool(hires_text)              # the picture is sent without its low-res text (the app draws it sharp)
        # the core remembers each string drawn on screen (Display.build_overlay) for sharp text and for the softkey names
        self.emu.hires_text = self.sharp or bool(live_softkeys)
        self.items_json = "[]"                     # those strings for the Java side, taken together with each picture
        self.emu.font_size = max(8, min(16, int(font_size)))          # the game's own text size (Options)
        self.emu.leaderboard_url = str(leaderboard or "").strip()     # "": scores stay on the phone (the player's choice)
        self.stop_flag = False
        self.session = 0               # set by start_game
        self.want_paused = False
        self.pause_for_menu = False    # held for the app's own menu, not because the app left the screen
        self.leave_pending = False     # the app left while the menu already held the game: autosave once
        self.paused_at = None          # monotonic time the loop paused the game clock, else None
        self.error = ""
        self.taps = collections.deque()      # (x, y) taps on the game's picture, in game pixels, from the Java side
        self.key_script = []                 # [due (monotonic), "down" or "up", avk]: key presses a tap asked for
        # khvcemu's own "Wonderland is lost media" pages, shown when Continue is pressed on the Wonderland splash (as the
        # desktop frontend does): the game is held while they are up, and its Continue press is passed on after the last
        self.lm_pages = []                   # the pages still to show (565 frames), the first is on screen
        self.lm_start = self.lm_next = False  # asked for by a key press (from any thread), done on the core thread
        self.lm_serial = 0                   # changes whenever the picture shown changes (the Java side polls it)
        self.lm_t0 = 0.0
        self.lm_ended = 0.0                  # when the last page was turned (see _press)
        self.soft1_down = 0.0
        self.lm_paused = 0.0                 # seconds of the pages' time the app spent paused (already kept out of the clock)
        from khvcemu.savestate import StateSlots
        self.slots = StateSlots(self.emu)    # slots 1-9 and three rotating autosaves, in <data dir>/states (the desktop's files)
        self.requests = collections.deque()  # ("save" or "load", slot name) asked for by the menu, run on the core thread
        self.messages = collections.deque(maxlen=4)      # what the last save or load said, for the app to show once
        self.played = False                  # a key was pressed since the last save/load: idle time never rotates autosaves
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
            if os.path.exists(os.path.join(os.path.dirname(self.game_dir), "lm_test_flag")):
                emu.wonderland_splash_up = True                    # diagnostics: act as if the Wonderland splash were up
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
                        if not self.pause_for_menu:
                            self._autosave_on_leaving()            # Android may end the app without telling it
                        self.paused_at = time.monotonic()
                        self.mixer.paused = True                   # sound is held too
                        self._log("paused (the app is not in the foreground); game clock %d ms" % emu.clock_ms())
                    else:                                          # the clock continues where it stopped
                        held = time.monotonic() - self.paused_at
                        emu._t0 += held
                        if self.lm_pages:
                            self.lm_paused += held                  # (the pages' own hold must not count it again)
                        self.paused_at = None
                        self.mixer.paused = False
                        self._log("resumed after %.1f s; game clock %d ms" % (held, emu.clock_ms()))
                if self.paused_at is not None:
                    if self.leave_pending:
                        self.leave_pending = False
                        self._autosave_on_leaving()
                    self.taps.clear()
                    self.key_script.clear()
                    time.sleep(0.02)
                    continue
                self._handle_taps()
                if self._lost_media():                             # the Wonderland pages are up: the game waits
                    self._handle_requests()                        # (a save or load from the menu does not)
                    time.sleep(0.02)
                    continue
                self._handle_states()
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
                if emu.applet_ptr and not emu.exit_requested and self.played and self.slots.autosave_on_quit:
                    self.slots.autosave()                      # leaving mid-game: keep one more, as the desktop does
                emu.stop()
                emu.playtime.save()
            except Exception:
                pass


    def _state_action(self, fn, loading=False):
        """Save, load or autosave between guest calls (as khvcemu/frontend.py does); the clock is held still while the
        file is written so the game does not skip ahead (not after a load: that sets the clock itself)."""
        emu = self.emu
        t = time.monotonic()
        try:
            msg = fn()
        except Exception as e:                                    # a failed save or load must never end the game
            msg = "Failed: %s" % e
            if fn == self.slots.autosave:
                self.slots.last_auto_ms = emu.clock_ms()          # try again in a while, not on every pass
        failed = msg.startswith("Failed") or "empty" in msg
        if (not loading or failed) and self.paused_at is None:   # (a load that worked sets the clock itself; a pause
            took = time.monotonic() - t                          # already accounts for the time it lasted)
            emu._t0 += took
            if self.lm_pages:
                self.lm_paused += took                           # (and the pages' own hold must not count it again)
        if not msg.startswith(("Failed", "Slot 0")) and "empty" not in msg:
            self.played = False
        self._log("state: " + msg)
        if not (fn == self.slots.autosave and msg == "Autosaved"):
            self.messages.append(msg)
        return msg

    def _handle_requests(self):
        """The menu's save and load requests (also while the Wonderland pages are up: a load puts the game somewhere else,
        so the pages end)."""
        from khvcemu.savestate import StateSlots
        slots = self.slots
        while self.requests:
            op, name = self.requests.popleft()
            try:
                slot = StateSlots.parse(name)
            except ValueError as e:
                self.messages.append(str(e))
                continue
            if op == "save" and not (isinstance(slot, int) and 1 <= slot <= 9):
                self.messages.append("Only slots 1 to 9 can be saved to")
                continue
            msg = self._state_action(lambda: slots.save(slot) if op == "save" else slots.load(slot), loading=(op == "load"))
            worked = not (msg.startswith("Failed") or "empty" in msg)
            if op == "load" and worked and self.lm_pages:             # (a load that failed changes nothing: the pages stay)
                self.lm_pages = []
                self.lm_serial += 1

    def _handle_states(self):
        """The menu's requests, then the timed autosaves (every few minutes of play, and a few seconds after a loading
        screen), with the same rules as the desktop."""
        emu, slots = self.emu, self.slots
        self._handle_requests()
        if slots.autosave_due():
            if self.played:
                self._state_action(slots.autosave)
            else:
                slots.last_auto_ms = emu.clock_ms()               # idle: check again next period
        if slots.area_save_due():                                  # a new area has finished loading
            emu.last_loading_ms = None
            if self.played and slots.area_save_allowed():
                self._state_action(slots.autosave)

    def _autosave_on_leaving(self):
        """The app is going to the background: one autosave if something was played (not within 30 s of the last one)."""
        slots, emu = self.slots, self.emu
        if (self.played and slots.autosave_enabled and emu.applet_ptr
                and (slots.last_autosave_ms is None or emu.clock_ms() - slots.last_autosave_ms >= 30000)):
            self._state_action(slots.autosave)

    def _handle_taps(self):
        """On the core thread, so what the game has drawn is not changing underneath: turn each tap on the picture into
        the keys the tapped button stands for (khvcemu/tapmap.py), and press them a little apart."""
        from khvcemu import tapmap
        emu = self.emu
        if self.lm_pages and self.taps:                      # a tap anywhere turns the Wonderland page
            self.taps.clear()
            self.lm_next = True
        while self.taps:
            x, y = self.taps.popleft()
            display = emu.display
            if emu.last_frame is not None:
                display.build_overlay(emu.last_frame)        # keeps only the strings still on screen
            items = display.__dict__.get("text_items", [])
            keys = tapmap.resolve_tap(x, y, items, emu.last_frame)
            self._log("tap (%d, %d) -> %s" % (x, y, keys or "nothing"))
            if keys:
                self.played = True
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
                self._press(step[2], step[1] == "down", scripted=True)

    def _press(self, avk, down, scripted=False):
        """A key goes to the game, except around the Wonderland splash: while the pages are up Soft 1 or Action turns the
        page and nothing reaches the game; on the splash itself Soft 1 starts the pages instead of continuing."""
        emu = self.emu
        if down and not scripted and avk == self.AVK["SOFT1"]:
            self.soft1_down = time.monotonic()                   # when the player's finger last went down on Soft 1
        if self.lm_pages:
            if down and avk in (self.AVK["SOFT1"], self.AVK["SELECT"]):
                self.lm_next = True
            return
        if emu.wonderland_splash_up and avk == self.AVK["SOFT1"]:
            if down:
                self.lm_start = True
            return
        if (not down and not scripted and avk == self.AVK["SOFT1"] and self.lm_ended
                and self.soft1_down < self.lm_ended and time.monotonic() - self.lm_ended < 0.3):
            return                                           # the finger that turned the last page: the game's Continue is
        (emu.key_down if down else emu.key_up)(avk)          # released by the script, so it is held long enough to be seen

    def _lost_media(self):
        """Starts, advances and ends the Wonderland pages (on the core thread). True while a page is on screen."""
        emu = self.emu
        if self.lm_start and not self.lm_pages:
            self.lm_start = False                            # (cleared where it is read: a press that lands later is kept)
            for avk in sorted(emu.keys_held):
                emu.key_up(avk)
            try:
                from khvcemu import lostmedia
                self.lm_pages = lostmedia.build_screens_pil()
            except Exception as e:                           # no pages: the game just continues
                self._log("the Wonderland pages are unavailable: %s" % e)
                emu.wonderland_splash_up = False
                self._press(self.AVK["SOFT1"], True)
                self.key_script.append([time.monotonic() + 0.15, "up", self.AVK["SOFT1"]])
                return False
            self.lm_t0, self.lm_paused = time.monotonic(), 0.0
            self.lm_serial += 1
            self._log("the Wonderland pages are up")
        if not self.lm_pages:
            self.lm_start = False                            # a stray press while no pages are up
            self.lm_next = False
            return False
        if self.lm_next:
            self.lm_next = False
            self.lm_pages.pop(0)
            self.lm_serial += 1
            if not self.lm_pages:                            # the game did not see the time the pages were up
                emu._t0 += (time.monotonic() - self.lm_t0) - self.lm_paused
                emu.wonderland_splash_up = False
                self._press(self.AVK["SOFT1"], True)         # now let the game have its Continue
                self.lm_ended = time.monotonic()
                self.key_script.append([self.lm_ended + 0.15, "up", self.AVK["SOFT1"]])
                self._log("the Wonderland pages are done")
        return bool(self.lm_pages)


_game = None


_start_lock = threading.Lock()
_sessions = 0                       # counts the games started; a screen stops only the game it started


def _music_files(text):
    """The Sound screen's recordings as JSON {tune file: {"path": ..., "gain": ...}} -> the dict the core takes (only files that
    exist; a damaged text means none)."""
    import json
    try:
        got = json.loads(text) if text else {}
    except ValueError:
        return {}
    out = {}
    for name, v in (got.items() if isinstance(got, dict) else ()):
        if isinstance(v, dict) and os.path.isfile(str(v.get("path", ""))):
            out[str(name).lower()] = {"path": str(v["path"]), "gain": float(v.get("gain", 1.0))}
    return out


def start_game(native_lib_dir, game_dir, data_dir, start_world="", speed_off="", frame_lock=True, music="",
               leaderboard="", font_size=11, music_files="", hires_text=False, live_softkeys=True):
    """Start the game thread (once). Returns the session number of the game that is running. start_world: seed the
    game save from that world's starting save first (chapters.install_save), so Load Game continues from there."""
    global _game, _sessions
    with _start_lock:
        if _game is not None and _game.stop_flag:                   # told to stop (Back, then reopened quickly):
            _game.thread.join(5)                                    # let it finish saving before a new one starts
            if _game.thread.is_alive() and start_world:
                print("[core] the earlier game is still closing; the starting save may be overwritten", flush=True)
        if _game is None or _game.stop_flag or not _game.thread.is_alive():   # not started, stopping or ended: start afresh
            os.makedirs(data_dir, exist_ok=True)
            game = _Game(native_lib_dir, game_dir, data_dir, start_world, speed_off, frame_lock, music, leaderboard,
                         font_size, music_files, hires_text, live_softkeys)
            _sessions += 1
            game.session = _sessions
            game.thread.start()
            _game = game
        else:
            print("[core] a game is already running: the new start settings (world %r, speed off %r, frame lock %s) were not "
                  "applied" % (start_world, speed_off, frame_lock), flush=True)
        return _game.session


def _decode_with_android(path):
    """audio.FILE_DECODER on the phone: the app's own decoder (Android's codecs) makes a mono 22,050 Hz copy of the recording
    next to it (kept until the recording changes), which is read back as samples."""
    import numpy as np
    from java import jclass
    pcm_path = str(jclass("com.khrecast.recast.RecordingDecoder").decodedPath(path))
    return np.fromfile(pcm_path, dtype="<i2")


def _install_decoder():
    from khvcemu import audio
    audio.FILE_DECODER = _decode_with_android


def match_gain(game_dir, tune, music_text, pcm_path):
    """The volume (0.05 to 4) that makes a recording (a decoded copy: mono 16-bit at 22,050 Hz) as loud as the built-in
    version of the tune with these settings; the launcher's Match level."""
    from khvcemu.music_preview import MusicPreview
    ours = bytes(render_tune(game_dir, tune, music_text))
    with open(pcm_path, "rb") as f:
        theirs = f.read()
    return float(MusicPreview.match_gain(ours, theirs))


def render_tune(game_dir, tune, music_text):
    """One of the game's tunes (a file name from music_preview.TUNES) made with the given music settings text, as mono
    16-bit samples at midi_synth.RATE (22050 Hz), for the Sound screen to play. The game's own state is not touched, but a game
    running in the same process shares the interpreter, so it may run slower while this works."""
    from khvcemu import music_preview, music_settings
    from khvcemu.audio import device_bytes
    from khvcemu.midi_synth import RATE, render_midi
    path = music_preview.tune_path(game_dir, tune)
    if not path:
        raise FileNotFoundError("the game has no tune %s" % tune)
    with open(path, "rb") as f:
        pcm = render_midi(f.read(), music_settings.parse(music_text or "", strict=False))
    return device_bytes(pcm, RATE, 1)


def stop(session=0):
    """Ask the game thread to end (the game screen is closing for good). With a session number, only that game is
    stopped: a late call from a screen that is already gone cannot end the game that replaced it."""
    if _game is not None and (not session or session == getattr(_game, "session", 0)):
        _game.stop_flag = True


def frame_count():
    """How many frames the game has drawn so far (cheap: the Java side polls this)."""
    return 0 if _game is None else _game.emu.frames + _game.lm_serial * 1000003      # (a page turn changes it too)


def frame_bytes():
    """The latest 176x220 picture as little-endian RGB565 bytes (what Android's RGB_565 bitmap takes), or empty."""
    if _game is None or _game.emu.last_frame is None:
        return b""
    import numpy as np
    pages = list(_game.lm_pages)                        # a copy: the core thread changes the list
    overlay = None if pages else getattr(_game.emu, "overlay", None)   # (picture without its low-res text, the strings), or None
    _game.items_json = _items_json(list(overlay[1])) if overlay else "[]"      # (a copy: the core thread changes the list)
    base = pages[0] if pages else (overlay[0] if overlay and _game.sharp else _game.emu.last_frame)
    return np.ascontiguousarray(base, dtype="<u2").tobytes()


def _items_json(items):
    """The strings the core drew on the screen, for the app to draw sharp at the screen's own size:
    [{t: text, f: font id, x, y: where it starts, w, h: the size it took, c: RGB565 color, b: [x0, y0, x1, y1] the part that shows}]."""
    import json
    return json.dumps([{"t": it["text"], "f": int(it["font_id"]), "x": int(it["x"]), "y": int(it["y"]),
                        "w": int(it["size"][0]), "h": int(it["size"][1]), "c": int(it["fg"]),
                        "b": [int(v) for v in it["box"]]} for it in items], separators=(",", ":"))


def frame_text():
    """The strings that go with the picture frame_bytes() last returned ("[]" when sharp text is off)."""
    return "[]" if _game is None else _game.items_json


def key(name, down):
    """A touch control was pressed or released: name is a phone key from khvcemu.keys.AVK (UP, SELECT, STAR, 0...)."""
    if _game is None or _game.paused_at is not None or _game.want_paused or not _game.thread.is_alive():
        return
    avk = _game.AVK.get(name)
    if avk is None:
        return
    if down:
        _game.played = True
    _game._press(avk, down)


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


def check_online(url):
    """Options' "Test the connection": fetches the leaderboard's top list (a read-only request, nothing is posted) and says
    in a sentence whether it worked."""
    import urllib.request
    base = str(url).strip().rstrip("/")
    try:
        req = urllib.request.Request(base + "/top", headers={"User-Agent": "khvcemu"})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read(200000)
        return "Connected to %s: it answered with %d bytes." % (base, len(body))
    except Exception as e:                                       # any failure is shown to the player in words
        return "Could not reach %s: %s" % (base, e)


def configure(autosave, minutes, on_loading, on_quit):
    """The Options screen's autosave switches (khvcemu's StateSlots fields): safe to call from the Java thread."""
    if _game is not None:
        slots = _game.slots
        slots.autosave_enabled = bool(autosave)
        slots.autosave_every_ms = int(max(0, min(int(minutes), 24 * 60)) * 60_000)
        slots.autosave_on_loading = bool(on_loading)
        slots.autosave_on_quit = bool(on_quit)


def request_state(op, name):
    """Save ("save") or load ("load") a slot ("1".."9", "auto", "auto2", "auto3") on the core thread. The result comes
    back through take_message()."""
    if _game is not None and op in ("save", "load"):
        _game.requests.append((op, str(name)))


def take_message():
    """What the last save or load said (once), or an empty string."""
    if _game is not None and _game.messages:
        return _game.messages.popleft()
    return ""


def pause(menu=False):
    """Hold the game. menu=True: only because the app's own menu is up (no autosave then); else the app is leaving."""
    if _game is not None:
        if _game.want_paused and _game.pause_for_menu and not menu:
            _game.leave_pending = True                 # the menu was up and now the app really leaves
        _game.pause_for_menu = bool(menu)
        _game.want_paused = True


def resume():
    if _game is not None:
        _game.leave_pending = False                    # the app is back before the core noticed it had left
        _game.pause_for_menu = False
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
