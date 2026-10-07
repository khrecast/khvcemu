"""The Sound tab's music settings: parsing, what each slider does to the synth, and the
launcher tab itself (no game files needed; nothing is played out loud)."""
import os
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu import music_settings as ms  # noqa: E402
from khvcemu import midi_synth  # noqa: E402

R = midi_synth.RATE


def _vlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def one_note(program, note, ticks=240, channel=1, vel=110):
    """A one-note MIDI file (480 ticks = half a second)."""
    on, off, pc = 0x90 | channel, 0x80 | channel, 0xC0 | channel
    trk = (bytes([0, pc, program, 0, on, note, vel]) + _vlq(ticks) + bytes([off, note, 0])
           + bytes([0, 0xFF, 0x2F, 0]))
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(trk)) + trk


def render(mid, **settings):
    return midi_synth.render_midi(mid, settings).astype(float) / 32768


def peak(a, t0=0.0, t1=None):
    seg = a[int(t0 * R):None if t1 is None else int(t1 * R)]
    return float(np.abs(seg).max()) if len(seg) else 0.0


class SettingsTextTests(unittest.TestCase):
    def test_defaults_are_all_one_and_cover_every_slider(self):
        self.assertEqual(set(ms.DEFAULTS), {s.key for s in ms.VOLUMES + ms.CHARACTER})
        self.assertTrue(all(v == 1.0 for v in ms.DEFAULTS.values()))
        for s in ms.VOLUMES + ms.CHARACTER:
            self.assertLessEqual(s.low, 1.0)
            self.assertGreaterEqual(s.high, 1.0)

    def test_every_voice_model_has_a_volume_slider(self):
        kinds = {midi_synth._timbre(p) for p in range(128)}
        self.assertEqual(kinds - set(ms.GROUP_OF_KIND), set())
        self.assertTrue(set(ms.GROUP_OF_KIND.values()) <= set(ms.ALL))

    def test_parse_and_text_round_trip(self):
        got = ms.parse(" piano = 0.8; Bass-Cut=1.5 ,master=1")
        self.assertEqual(got, {"piano": 0.8, "bass_cut": 1.5})           # defaults are left out
        self.assertEqual(ms.to_text(got), "bass_cut=1.5,piano=0.8")
        self.assertEqual(ms.parse(ms.to_text(got)), got)
        self.assertEqual(ms.to_text({}), "")
        self.assertEqual(ms.parse(""), {})

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            ms.parse("loudness=2")
        with self.assertRaises(ValueError):
            ms.parse("piano=loud")
        with self.assertRaises(ValueError):
            ms.parse("piano")
        self.assertEqual(ms.parse("piano=99")["piano"], 2.0, "clamped to the slider")
        self.assertEqual(ms.clean({"piano": float("nan"), "x": 3, "drums": "0.5"})["drums"], 0.5)
        self.assertEqual(ms.clean({"piano": float("nan")})["piano"], 1.0)

    def test_saved_settings_skip_what_they_do_not_know(self):
        self.assertEqual(ms.parse("piano=0.5,bogus=3,drums=x", strict=False), {"piano": 0.5})

    def test_the_command_line_takes_it(self):
        from khvcemu.__main__ import main
        with self.assertRaises(SystemExit):
            main([".", "--music", "nonsense=1"])


class SynthSettingsTests(unittest.TestCase):
    def test_default_settings_are_the_sound_as_tuned(self):
        mid = one_note(0, 60)
        a = midi_synth.render_midi(mid)
        self.assertTrue(np.array_equal(a, midi_synth.render_midi(mid, {})))
        self.assertTrue(np.array_equal(a, midi_synth.render_midi(mid, dict(ms.DEFAULTS))))

    def test_volume_sliders(self):
        piano = one_note(0, 60)
        self.assertEqual(peak(render(piano, piano=0)), 0.0)
        self.assertAlmostEqual(peak(render(piano, master=0.5)), peak(render(piano)) / 2, places=3)
        self.assertAlmostEqual(peak(render(piano, strings=0)), peak(render(piano)), places=6,
                               msg="another group's slider leaves the piano alone")
        drum = one_note(0, 38, channel=9)
        self.assertGreater(peak(render(drum)), 0.01)
        self.assertEqual(peak(render(drum, drums=0)), 0.0)

    def test_character_sliders(self):
        piano = one_note(0, 60, ticks=120)
        f0 = 440.0 * 2 ** ((60 - 69) / 12)

        def tick(a):          # energy above the third harmonic in the first 20 ms
            seg = a[: int(0.02 * R)]
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 4096)) ** 2
            return float(spec[np.fft.rfftfreq(4096, 1 / R) > 3.5 * f0].sum())
        self.assertLess(tick(render(piano, hammer=0)), 0.5 * tick(render(piano)))
        self.assertGreater(peak(render(piano, piano_tail=3), 0.6), 1.4 * peak(render(piano), 0.6),
                           "a longer tail still rings after the key is let go")
        horn = one_note(61, 55, ticks=58)
        self.assertGreater(peak(render(horn, horn_length=4), 0.3), 4 * peak(render(horn), 0.3))
        low = one_note(0, 52)
        self.assertGreater(peak(render(low, bass_cut=0)), 1.3 * peak(render(low)))
        high = one_note(0, 95)
        self.assertGreater(peak(render(high, high_soft=0)), 1.5 * peak(render(high)))


class AudioEngineTests(unittest.TestCase):
    def test_the_engine_renders_with_its_settings_and_caches_them_apart(self):
        from khvcemu.audio import AudioEngine

        class E:
            def log(self, s):
                pass
            logv = log

            def clock_ms(self):
                return 0
        mid = one_note(0, 60)
        plain = AudioEngine(E(), enabled=False).decode(mid, "a.mid")
        quiet = AudioEngine(E(), enabled=False, music={"master": 0.5}).decode(mid, "a.mid")
        self.assertAlmostEqual(np.abs(quiet).max() / np.abs(plain).max(), 0.5, places=2)
        eng = AudioEngine(E(), enabled=False)
        a = eng.decode(mid, "a.mid")
        eng.music = ms.clean({"piano": 0.5})
        self.assertLess(np.abs(eng.decode(mid, "a.mid")).max(), 0.8 * np.abs(a).max(),
                        "a changed setting is not served from the cache")


class SoundFontTests(unittest.TestCase):
    def test_with_a_soundfont_only_the_music_volume_applies(self):
        from khvcemu.audio import AudioEngine

        class E:
            def log(self, s):
                pass
            logv = log
        tone = (np.sin(np.arange(R) / R * 2 * np.pi * 440) * 10000).astype(np.int16)
        eng = AudioEngine(E(), enabled=False, music={"master": 0.5, "piano": 0})
        eng.fluidsynth = "fluidsynth"                       # pretend it is installed
        eng._fluidsynth = lambda data: tone
        out = eng.decode(one_note(0, 60), "a.mid")
        self.assertAlmostEqual(np.abs(out).max() / np.abs(tone).max(), 0.5, places=2,
                               msg="the volume applies, the piano slider (synth only) does not")


class PreviewTests(unittest.TestCase):
    def test_a_tune_renders_for_the_sound_device(self):
        from khvcemu.music_preview import MusicPreview
        p = MusicPreview()
        p.rate, p.channels = 44100, 2                       # a stereo device at twice the rate
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.mid")
            with open(path, "wb") as f:
                f.write(one_note(0, 60))
            raw = p.render_tune(path, {})
        mono = midi_synth.render_midi(one_note(0, 60))
        self.assertAlmostEqual(len(raw) / (len(mono) * 2 * 2 * 2), 1.0, places=2)

    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "needs ffmpeg")
    def test_a_recording_is_decoded_for_the_sound_device(self):
        import wave
        from khvcemu.music_preview import MusicPreview
        p = MusicPreview()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rec.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(R)
                w.writeframes(midi_synth.render_midi(one_note(0, 60)).tobytes())
            raw = p.decode_recording(path)
            self.assertGreater(len(raw), R)                  # about a second of 16-bit sound
            self.assertIs(p.decode_recording(path), raw, "decoded once")


class LauncherCommandTests(unittest.TestCase):
    def test_music_goes_on_the_command_line_only_when_changed(self):
        from khvcemu.launcher import build_command
        self.assertNotIn("--music", build_command("d", {"music": ""}))
        cmd = build_command("d", {"music": "piano=0.8"})
        self.assertEqual(cmd[cmd.index("--music") + 1], "piano=0.8")

    def test_tunes_are_found_in_any_letter_case(self):
        from khvcemu.music_preview import tune_path
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "mod", "11839"))
            open(os.path.join(d, "mod", "11839", "Island.MID"), "wb").close()
            self.assertTrue(tune_path(d, "island.mid").endswith("Island.MID"))
            self.assertIsNone(tune_path(d, "castle.mid"))
            self.assertIsNone(tune_path("", "island.mid"))


class FakePreview:
    """Stands in for music_preview.MusicPreview: nothing is played out loud. Renders wait
    for `gate` when it is set, to test what happens while one is in progress."""

    def __init__(self):
        self.played, self.renders, self.gate = [], [], None

    def open(self):
        pass

    def render_tune(self, path, settings):
        if self.gate is not None:
            self.gate.wait(5)
        self.renders.append((os.path.basename(path), dict(settings)))
        return b"ours:" + os.path.basename(path).encode()

    def decode_recording(self, path):
        return b"recording"

    def play(self, raw):
        self.played.append(raw)

    def stop(self):
        self.played.append(None)

    def close(self):
        pass


class SoundTabTests(unittest.TestCase):
    def test_the_tab_saves_its_sliders_and_plays_what_they_say(self):
        import tkinter as tk
        from khvcemu import launcher as L
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "mif"))
            os.makedirs(os.path.join(d, "mod", "11839"))
            with open(os.path.join(d, "mod", "11839", "training.mid"), "wb") as f:
                f.write(one_note(0, 60))
            saved = []
            old = (L.load_config, L.save_config)
            L.load_config = lambda: {"dump": d, "music": "piano=0.5,bogus=3"}
            L.save_config = lambda c: saved.append(dict(c))
            try:
                try:
                    root = tk.Tk()
                except tk.TclError:
                    self.skipTest("no display for Tk")
                root.withdraw()
                try:
                    app = L.Launcher(root)
                    self.assertEqual(set(app.music_vars), set(ms.ALL), "a slider for every setting")
                    self.assertAlmostEqual(app.music_vars["piano"].get(), 0.5, msg="the saved value is loaded")
                    self.assertEqual(app.music_labels["piano"].cget("text"), "50%")
                    app.preview = FakePreview()
                    app.play_ours()
                    end = time.time() + 5
                    while app.playing is None and time.time() < end:
                        root.update()
                        time.sleep(0.02)
                    self.assertEqual(app.playing, "ours")
                    self.assertEqual(app.preview.renders[-1][1]["piano"], 0.5)
                    app.music_vars["bass_cut"].set(1.52)
                    app.music_changed()               # let go of a slider while it plays
                    end = time.time() + 5
                    while len(app.preview.renders) < 2 and time.time() < end:
                        root.update()
                        time.sleep(0.02)
                    self.assertAlmostEqual(app.preview.renders[-1][1]["bass_cut"], 1.5, msg="snapped to 5% steps")
                    self.assertEqual(saved[-1]["music"], "bass_cut=1.5,piano=0.5")
                    self.assertIn("--music", L.build_command(d, app.opts()))
                    app.reset_music("piano")
                    self.assertEqual(app.opts()["music"], "bass_cut=1.5")
                    app.reset_music()
                    self.assertEqual(app.opts()["music"], "")
                    self.assertNotIn("--music", L.build_command(d, app.opts()))
                    app.stop_music()
                    self.assertIsNone(app.playing)
                    self.assertLessEqual(app.tab_frames["sound"].winfo_reqheight(), 310,
                                         "the Sound tab keeps the launcher about 630 px tall")
                finally:
                    root.destroy()
            finally:
                L.load_config, L.save_config = old

    def make_app(self, d, cfg):
        import tkinter as tk
        from khvcemu import launcher as L
        old = (L.load_config, L.save_config)
        L.load_config = lambda: dict(cfg, dump=d)
        L.save_config = lambda c: None
        self.addCleanup(setattr, L, "load_config", old[0])
        self.addCleanup(setattr, L, "save_config", old[1])
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display for Tk")
        root.withdraw()

        def destroy():
            try:
                root.destroy()
            except tk.TclError:
                pass                      # the test closed the launcher itself
        self.addCleanup(destroy)
        return root, L.Launcher(root)

    @staticmethod
    def game_folder(d):
        os.makedirs(os.path.join(d, "mif"), exist_ok=True)
        os.makedirs(os.path.join(d, "mod", "11839"), exist_ok=True)
        for name in ("training.mid", "island.mid"):
            with open(os.path.join(d, "mod", "11839", name), "wb") as f:
                f.write(one_note(0, 60))

    def pump(self, root, until, secs=5):
        end = time.time() + secs
        while not until() and time.time() < end:
            root.update()
            time.sleep(0.02)

    def test_switching_tune_while_one_is_being_prepared_plays_the_new_one(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            root, app = self.make_app(d, {})
            app.preview = FakePreview()
            app.preview.gate = threading.Event()
            app.play_ours()                                   # the title tune, still rendering
            root.update()
            self.assertEqual(app.pending, "ours")
            app.tune.set("Swashbuckler's Island")             # switched before it was ready
            root.update()
            app.music_vars["piano"].set(0.3)
            app.music_changed()                               # and a slider let go, too
            app.preview.gate.set()
            self.pump(root, lambda: app.playing == "ours" and not app.pending
                      and app._music_timer is None and len(app.preview.renders) >= 3)
            played = [p for p in app.preview.played if p]
            self.assertEqual(played[-1], b"ours:island.mid", "the old tune never takes over")
            self.assertNotIn(b"ours:training.mid", played)
            self.assertAlmostEqual(app.preview.renders[-1][1]["piano"], 0.3)
            app.close()

    def test_the_soundfont_lives_in_the_advanced_window_and_grays_out_the_synth(self):
        import tkinter as tk
        from khvcemu import launcher as L
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            sf = os.path.join(d, "a.sf2")
            open(sf, "wb").close()
            real = L.fluidsynth_found
            self.addCleanup(setattr, L, "fluidsynth_found", real)
            root, app = self.make_app(d, {})
            synth_only = [k for k in ms.ALL if k != "master"]
            grayed = lambda: [k for k in ms.ALL if "disabled" in app.music_scales[k].state()]   # noqa: E731
            self.assertEqual(grayed(), [], "the built-in synth: every slider works")
            L.fluidsynth_found = lambda: False
            app.open_advanced()
            self.assertIsNotNone(app.adv_win)
            self.assertEqual(str(app.sf_entry.cget("state")), "disabled", "nothing to type into without fluidsynth")
            self.assertIn("not found", app.adv_status.cget("text"))
            app.soundfont.set(sf)
            self.assertIn("fluidsynth is not installed", app.music_note.cget("text"))
            self.assertEqual(grayed(), [], "without fluidsynth the synth still plays, so nothing is grayed")
            L.fluidsynth_found = lambda: True
            app.show_music_note()
            self.assertEqual(str(app.sf_entry.cget("state")), "normal")
            self.assertIn("In use", app.adv_status.cget("text"))
            self.assertIn("only Music volume applies", app.music_note.cget("text"))
            self.assertEqual(sorted(grayed()), sorted(synth_only), "a SoundFont: only Music volume is left")
            self.assertEqual(str(app.mix_box.cget("state")), "disabled", "and the mixes do nothing")
            self.assertEqual(str(app.del_btn.cget("state")), "disabled")
            self.assertNotIn("disabled", app.music_scales["master"].state(), "Music volume always applies")
            app.music_vars["master"].set(0.8)
            app.music_changed()                                # letting go of Music volume...
            self.assertEqual(str(app.music_labels["piano"].cget("foreground")), L.DIM, "...keeps the others gray")
            app.music_vars["piano"].set(0.5)
            app.reset_music("piano")                           # a double-click on a grayed-out value
            self.assertAlmostEqual(app.music_vars["piano"].get(), 0.5, msg="does nothing")
            app.open_advanced()                                # opening it again just brings it forward
            self.assertEqual(len([w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]), 1)
            app.soundfont.set(os.path.join(d, "missing.sf2"))
            self.assertIn("not found", app.music_note.cget("text"))
            self.assertEqual(grayed(), [])
            app.soundfont.set(sf)
            app.sf_clear.invoke()                              # the Clear button
            self.assertEqual(app.soundfont.get(), "")
            self.assertIn("as tuned", app.music_note.cget("text"))
            self.assertEqual(str(app.mix_box.cget("state")), "readonly")
            app.close_advanced()
            self.assertIsNone(app.adv_win)
            app.open_advanced()
            app.adv_win.destroy()                              # gone some other way
            app.soundfont.set(sf)                              # must not touch the dead window
            self.assertIsNone(app.adv_win)
            app.close()

    def test_a_recording_in_the_game_grays_out_the_synth_for_that_tune(self):
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            rec = os.path.join(d, "title.flac")
            open(rec, "wb").close()
            root, app = self.make_app(d, {"music_refs": {"training.mid": {"path": rec, "in_game": True}}})
            grayed = lambda: [k for k in ms.ALL if "disabled" in app.music_scales[k].state()]   # noqa: E731
            self.assertEqual(sorted(grayed()), sorted(k for k in ms.ALL if k != "master"))
            self.assertEqual(str(app.fav_btn.cget("state")), "disabled")
            self.assertEqual(str(app.in_game_check.cget("state")), "normal", "the recording's own controls stay")
            app.tune.set("Swashbuckler's Island")             # another tune, no recording: all back
            root.update()
            self.assertEqual(grayed(), [])
            app.tune.set("Title menu and Obstacle Course")
            root.update()
            app.rec_in_game.set(False)
            app.rec_in_game_changed()
            self.assertEqual(grayed(), [])
            os.remove(rec)
            app.rec_in_game.set(True)
            app.rec_in_game_changed()                          # ticked, but the file is gone: the MIDI plays
            self.assertEqual(grayed(), [])
            self.assertIn("missing", app.music_note.cget("text"))
            from khvcemu import launcher as L
            real = L.fluidsynth_found
            self.addCleanup(setattr, L, "fluidsynth_found", real)
            L.fluidsynth_found = lambda: True
            sf = os.path.join(d, "a.sf2")
            open(sf, "wb").close()
            app.soundfont.set(sf)                              # missing recording + a SoundFont
            self.assertIn("the SoundFont plays", app.music_note.cget("text"))
            self.assertEqual(sorted(grayed()), sorted(k for k in ms.ALL if k != "master"))
            app.close()

    def test_restore_default_settings_puts_the_options_back(self):
        from khvcemu import launcher as L
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            saved = []
            root, app = self.make_app(d, {"scale": "4", "font_size": 14, "mute": True, "hires_text": True,
                                          "filter": "sharp", "soundfont": "x.sf2", "autosave": False,
                                          "pause_on_focus_loss": False, "screenshots": "D:/shots",
                                          "share_scores": False, "leaderboard_url": "https://typo.example",
                                          "music": "piano=0.5", "speed_patches_off": ["matinv"]})
            L.save_config = lambda c: saved.append(dict(c))
            self.assertEqual(app.scale.get(), "4")
            self.assertEqual(app.opts()["speed_patches_off"], ["matinv"])
            self.assertEqual(app.leaderboard.get(), "https://typo.example")
            asked = []
            real = L.messagebox.askyesno
            self.addCleanup(setattr, L.messagebox, "askyesno", real)
            L.messagebox.askyesno = lambda *a, **k: asked.append(a) or False
            app.restore_defaults()                            # "No": nothing changes
            self.assertEqual(app.scale.get(), "4")
            self.assertEqual(len(asked), 1)
            self.assertIn("saves", asked[0][1].lower())
            L.messagebox.askyesno = lambda *a, **k: True
            app.restore_defaults()
            opts = app.opts()
            self.assertEqual((app.scale.get(), app.font_size.get(), app.mute.get(), app.hires.get()),
                             ("Auto", "11", False, False))
            self.assertEqual((opts["filter"], opts["share_scores"]), ("nearest", True))
            self.assertIs(opts["autosave"], False, "the Saves tab's autosave settings are not the button's to change")
            self.assertEqual((opts["pause_on_focus_loss"], opts["screenshots"]), (True, ""))
            self.assertEqual(opts["speed_patches_off"], [], "the 3D speed-ups are back on")
            self.assertEqual(opts["soundfont"], "x.sf2", "the Sound tab's SoundFont is left alone")
            self.assertEqual(app.leaderboard.get(), L.LEADERBOARD_URL)
            self.assertEqual(opts["leaderboard"], L.LEADERBOARD_URL)
            self.assertEqual(saved[-1]["leaderboard_url"], "", "the default server is not pinned in the config")
            self.assertEqual(opts["music"], "piano=0.5", "the music sliders are reset by the As tuned mix instead")
            self.assertEqual(app.cfg["dump"], d, "the game folder is kept")
            self.assertEqual(str(app.share_entry.cget("state")), "normal")
            for key, want in L.OPTION_DEFAULTS.items():
                self.assertIn(key, ("scale", "font_size", "mute", "hires_text", "filter",
                                    "autosave", "pause_on_focus_loss", "screenshots", "dark_screen", "ask_before_quit", "share_scores",
                                    "leaderboard_url", "speed_patches_off", "autosave_minutes", "autosave_on_quit",
                                    "autosave_on_loading", "ask_before_deleting_screenshot"))
            app.close()

    def test_tab_names_are_drawn_in_the_menu_font_and_fall_back_to_text(self):
        from khvcemu import launcher as L
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            root, app = self.make_app(d, {})
            for key, frame in app.tab_frames.items():
                image = app.tabs.tab(frame, "image")
                self.assertTrue(image, f"{key} has its picture")
                self.assertEqual(str(app.tabs.tab(frame, "compound")), "image")
                self.assertTrue(app.tabs.tab(frame, "text"), "the text stays underneath")
            # the Setup tab's picture follows whether something needs fixing (refresh decides)
            old_which, old_missing = L.shutil.which, L.missing_packages
            self.addCleanup(setattr, L.shutil, "which", old_which)
            self.addCleanup(setattr, L, "missing_packages", old_missing)
            L.shutil.which = lambda name: "C:/tools/" + name       # ffmpeg is there
            L.missing_packages = lambda: []
            app.refresh()
            self.assertFalse(app.setup_needed)
            fine = str(app.tabs.tab(app.tab_frames["setup"], "image"))
            L.missing_packages = lambda: ["numpy"]                 # something to fix
            app.refresh()
            self.assertTrue(app.setup_needed)
            self.assertNotEqual(str(app.tabs.tab(app.tab_frames["setup"], "image")), fine, "Setup (!)")
            self.assertEqual(app.tabs.tab(app.tab_frames["setup"], "text"), "Setup (!)")
            app.close()
            old = L.TAB_LABELS_DIR
            L.TAB_LABELS_DIR = os.path.join(d, "no-such-folder")
            self.addCleanup(setattr, L, "TAB_LABELS_DIR", old)
            root2, app2 = self.make_app(d, {})
            frame = app2.tab_frames["sound"]
            self.assertFalse(app2.tabs.tab(frame, "image"), "no pictures: plain text")
            self.assertEqual(app2.tabs.tab(frame, "text"), "Sound")
            app2.close()

    def test_setup_says_whether_the_wonderland_theme_is_there(self):
        from khvcemu import launcher as L
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            old_which, old_missing = L.shutil.which, L.missing_packages
            self.addCleanup(setattr, L.shutil, "which", old_which)
            self.addCleanup(setattr, L, "missing_packages", old_missing)
            L.shutil.which = lambda name: "C:/tools/" + name
            L.missing_packages = lambda: []
            root, app = self.make_app(d, {})
            text = app.req_label.cget("text")
            self.assertIn("Wonderland theme: not found (optional", text)
            self.assertFalse(app.setup_needed, "optional: it never puts (!) on Setup")
            os.makedirs(os.path.join(d, "wonderland"))
            open(os.path.join(d, "wonderland", "Wonderland.FLAC"), "wb").close()
            app.refresh()
            self.assertIn("Wonderland theme: OK", app.req_label.cget("text"))
            self.assertIn("Wonderland.FLAC", app.req_label.cget("text"))
            open(os.path.join(d, "wonderland.mid"), "wb").close()   # in the game folder itself, and a MIDI
            app.refresh()
            self.assertIn("Wonderland theme: OK (wonderland.mid)", app.req_label.cget("text"),
                          "the game prefers a MIDI, as it would play it")
            app.close()

    def test_a_hand_edited_config_does_not_break_the_tab(self):
        with tempfile.TemporaryDirectory() as d:
            self.game_folder(d)
            root, app = self.make_app(d, {"music_refs": ["not", "a", "dict"], "music": 7,
                                          "music_tune": None})
            self.assertEqual(str(app.rec_btn.cget("state")), "disabled")
            self.assertEqual(app.rec_name, "")
            app.play_recording()                              # nothing chosen: a message, no crash
            self.assertIn("choose it again", app.status.cget("text"))
            self.assertIsNone(app.preview)
            app.close()                                       # never played: nothing to close


if __name__ == "__main__":
    unittest.main()
