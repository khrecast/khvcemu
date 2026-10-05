"""Sound tab mixes and recordings: ready-made mixes, saved mixes and favorites, the comparison
recording's volume, and playing a recording in the game instead of the game's MIDI (no game
files needed; nothing is played out loud)."""
import os
import struct
import sys
import tempfile
import time
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu import midi_synth  # noqa: E402
from khvcemu import music_settings as ms  # noqa: E402

R = midi_synth.RATE


def _vlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def tune(ticks=480 * 4):
    """A small MIDI tune: one piano note held for `ticks` (480 = half a second)."""
    trk = bytes([0, 0xC1, 0, 0, 0x91, 60, 100]) + _vlq(ticks) + bytes([0x81, 60, 0, 0, 0xFF, 0x2F, 0])
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(trk)) + trk


def write_wav(path, seconds, level=0.25, freq=330.0):
    t = np.arange(int(seconds * R)) / R
    a = (np.sin(2 * np.pi * freq * t) * level * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(R)
        w.writeframes(a.tobytes())


class PresetTests(unittest.TestCase):
    def test_presets_are_valid_and_as_tuned_is_the_default(self):
        self.assertEqual(list(ms.PRESETS)[0], "As tuned")
        self.assertEqual(ms.preset("As tuned"), ms.DEFAULTS)
        self.assertGreaterEqual(len(ms.PRESETS), 5)
        for name, values in ms.PRESETS.items():
            self.assertTrue(set(values) <= set(ms.ALL), name)
            full = ms.preset(name)
            for k, v in values.items():
                self.assertEqual(full[k], v, f"{name}: {k} is inside its slider's range")
        self.assertGreater(ms.preset("More bass")["bass"], 1)
        self.assertLess(ms.preset("Quiet background")["master"], 1)

    def test_music_file_options(self):
        got = ms.parse_music_files(["Training.MID=C:/my music/title, take 2.flac", "island.mid=x.wav"],
                                   ["training.mid=0.8"])
        self.assertEqual(got, {"training.mid": {"path": "C:/my music/title, take 2.flac", "gain": 0.8},
                               "island.mid": {"path": "x.wav", "gain": 1.0}})
        for bad_files, bad_vols in ((["noequals"], []), (["=x.flac"], []), (["a.mid="], []),
                                    (["a.mid=x"], ["b.mid=1"]), (["a.mid=x"], ["a.mid=loud"]), (["a.mid=x"], ["a.mid=9"])):
            with self.assertRaises(ValueError):
                ms.parse_music_files(bad_files, bad_vols)


class EngineOverrideTests(unittest.TestCase):
    """AudioEngine plays the player's recording instead of a tune, fitted to the MIDI's length."""

    class E:
        def log(self, s):
            self.logs.append(s)
        logv = log

        def __init__(self):
            self.logs = []

    def setUp(self):
        import shutil
        if not shutil.which("ffmpeg"):
            self.skipTest("needs ffmpeg")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mid = tune()

    def engine(self, path, gain=1.0, music=None):
        from khvcemu.audio import AudioEngine
        return AudioEngine(self.E(), enabled=False, music=music,
                           music_files={"title.mid": {"path": path, "gain": gain}})

    def test_a_longer_recording_is_cut_to_the_midi_length_with_a_fade(self):
        rec = os.path.join(self.tmp.name, "long.wav")
        write_wav(rec, 9.0)
        want = len(midi_synth.render_midi(self.mid))
        pcm = self.engine(rec).decode(self.mid, "title.mid")
        self.assertEqual(len(pcm), want, "exactly as long as the game's own tune")
        self.assertGreater(np.abs(pcm[: R]).max(), 7000, "it is the recording")
        self.assertLess(abs(int(pcm[-1])), 300, "the cut is faded, not a click")

    def test_a_looping_tune_is_cut_where_its_music_ends_not_after_its_overlap_tail(self):
        loop = tune(480 * 16)                                # 8 s: a loop, not a jingle
        total = midi_synth.parse_midi(loop)[1]
        self.assertGreater(len(midi_synth.render_midi(loop)), int(total * R), "the synth keeps a tail")
        rec = os.path.join(self.tmp.name, "loop.wav")
        write_wav(rec, 12.0)                                 # keeps playing: the next loop begins
        pcm = self.engine(rec).decode(loop, "title.mid")
        self.assertEqual(len(pcm), int(total * R))
        self.assertLess(abs(int(pcm[-1])), 300)

    def test_a_shorter_recording_is_padded_with_silence(self):
        rec = os.path.join(self.tmp.name, "short.wav")
        write_wav(rec, 0.5)
        pcm = self.engine(rec).decode(self.mid, "title.mid")
        self.assertEqual(len(pcm), len(midi_synth.render_midi(self.mid)))
        self.assertEqual(np.abs(pcm[int(0.7 * R):]).max(), 0)

    def test_volume_and_music_volume_apply(self):
        rec = os.path.join(self.tmp.name, "a.wav")
        write_wav(rec, 3.0)
        full = self.engine(rec).decode(self.mid, "title.mid")
        half = self.engine(rec, gain=0.5).decode(self.mid, "title.mid")
        quarter = self.engine(rec, gain=0.5, music={"master": 0.5}).decode(self.mid, "title.mid")
        peak = lambda a: float(np.abs(a[: R]).max())     # noqa: E731
        self.assertAlmostEqual(peak(half) / peak(full), 0.5, places=2)
        self.assertAlmostEqual(peak(quarter) / peak(full), 0.25, places=2)

    def test_only_the_named_tune_is_replaced(self):
        rec = os.path.join(self.tmp.name, "a.wav")
        write_wav(rec, 3.0)
        eng = self.engine(rec)
        self.assertTrue(np.array_equal(eng.decode(self.mid, "other.mid"), midi_synth.render_midi(self.mid)))
        self.assertFalse(np.array_equal(eng.decode(self.mid, "fs:/~/Title.MID"), midi_synth.render_midi(self.mid)),
                         "the game's file name, any case, with or without its path")

    def test_a_changed_recording_is_not_served_from_the_cache(self):
        rec = os.path.join(self.tmp.name, "a.wav")
        write_wav(rec, 3.0, level=0.25)
        eng = self.engine(rec)
        first = eng.decode(self.mid, "title.mid")
        write_wav(rec, 3.5, level=0.1)                       # another size, so not only the time changes
        self.assertLess(np.abs(eng.decode(self.mid, "title.mid")).max(), 0.6 * np.abs(first).max())

    def test_a_missing_or_broken_recording_falls_back_to_the_midi(self):
        eng = self.engine(os.path.join(self.tmp.name, "missing.flac"))
        self.assertTrue(np.array_equal(eng.decode(self.mid, "title.mid"), midi_synth.render_midi(self.mid)))
        self.assertTrue(any("could not use" in m for m in eng.emu.logs))
        broken = os.path.join(self.tmp.name, "broken.flac")
        with open(broken, "wb") as f:
            f.write(b"not audio at all")
        eng = self.engine(broken)
        self.assertTrue(np.array_equal(eng.decode(self.mid, "title.mid"), midi_synth.render_midi(self.mid)))


class EngineOverrideMoreTests(EngineOverrideTests):
    """The gaps the code review found."""

    def test_the_length_does_not_depend_on_the_sliders(self):
        rec = os.path.join(self.tmp.name, "a.wav")
        write_wav(rec, 9.0)
        want = len(midi_synth.render_midi(self.mid))
        for music in ({"piano": 0.0}, {"piano_tail": 0.25}, {"master": 0.5}):
            self.assertEqual(len(self.engine(rec, music=music).decode(self.mid, "title.mid")), want, music)

    def test_stereo_and_other_rates_are_mixed_down_to_the_games_format(self):
        rec = os.path.join(self.tmp.name, "stereo44.wav")
        t = np.arange(44100 * 3) / 44100
        left = (np.sin(2 * np.pi * 330 * t) * 8000).astype(np.int16)
        with wave.open(rec, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(np.column_stack([left, left]).tobytes())
        pcm = self.engine(rec).decode(self.mid, "title.mid")
        self.assertEqual(len(pcm), len(midi_synth.render_midi(self.mid)))
        self.assertAlmostEqual(float(np.abs(pcm[: R]).max()), 8000, delta=200, msg="same level, now mono at 22.05 kHz")

    def test_an_m4a_is_read_from_its_file(self):
        import shutil
        import subprocess
        src = os.path.join(self.tmp.name, "src.wav")
        write_wav(src, 3.0)
        m4a = os.path.join(self.tmp.name, "song.m4a")
        r = subprocess.run([shutil.which("ffmpeg"), "-v", "quiet", "-y", "-i", src, "-c:a", "aac", m4a],
                           capture_output=True)
        if r.returncode or not os.path.isfile(m4a):
            self.skipTest("this ffmpeg cannot make an .m4a")
        pcm = self.engine(m4a).decode(self.mid, "title.mid")
        self.assertGreater(np.abs(pcm[: R]).max(), 5000, "the recording, not the MIDI")

    def test_a_broken_file_is_tried_again_once_it_is_replaced(self):
        rec = os.path.join(self.tmp.name, "late.wav")
        with open(rec, "wb") as f:
            f.write(b"not yet")
        eng = self.engine(rec)
        self.assertTrue(np.array_equal(eng.decode(self.mid, "title.mid"), midi_synth.render_midi(self.mid)))
        time.sleep(0.02)
        write_wav(rec, 3.0)
        self.assertGreater(np.abs(eng.decode(self.mid, "title.mid")[: R]).max(), 7000)

    def test_the_midi_is_rendered_once_for_its_length(self):
        from unittest import mock
        rec = os.path.join(self.tmp.name, "a.wav")
        write_wav(rec, 3.0)
        eng = self.engine(rec)
        real = midi_synth.render_midi
        with mock.patch.object(midi_synth, "render_midi", side_effect=real) as render:
            eng.decode(self.mid, "title.mid")
            eng.music_files["title.mid"]["gain"] = 0.5          # another sound, same MIDI
            eng.decode(self.mid, "title.mid")
        self.assertEqual(render.call_count, 1)

    def test_a_recording_wins_over_a_soundfont(self):
        rec = os.path.join(self.tmp.name, "a.wav")
        write_wav(rec, 3.0)
        eng = self.engine(rec)
        eng.fluidsynth = "fluidsynth"                       # pretend one is in use
        eng._fluidsynth = lambda data: self.fail("the SoundFont should not be used for a replaced tune")
        self.assertGreater(np.abs(eng.decode(self.mid, "title.mid")[: R]).max(), 7000)


class CommandLineTests(unittest.TestCase):
    def test_bad_music_file_options_stop_with_a_message(self):
        from khvcemu.__main__ import main
        for argv in ([".", "--music-file", "nope"], [".", "--music-file-volume", "a.mid=1"],
                     [".", "--music-file", "a.mid=x.flac", "--music-file-volume", "a.mid=10"]):
            with self.assertRaises(SystemExit, msg=argv):
                main(argv)


class PreviewGainTests(unittest.TestCase):
    def test_gain_and_level_matching(self):
        from khvcemu.music_preview import MusicPreview
        loud = (np.sin(np.arange(R) / R * 2 * np.pi * 440) * 20000).astype(np.int16).tobytes()
        quiet = (np.sin(np.arange(3 * R) / R * 2 * np.pi * 440) * 5000).astype(np.int16).tobytes()
        self.assertIs(MusicPreview.with_gain(quiet, 1.0), quiet)
        self.assertAlmostEqual(MusicPreview.match_gain(loud, quiet), 4.0, places=2)
        self.assertAlmostEqual(MusicPreview.match_gain(quiet, loud), 0.25, places=2)
        louder = np.frombuffer(MusicPreview.with_gain(quiet, 2.0), np.int16)
        self.assertAlmostEqual(int(np.abs(louder).max()), 10000, delta=5)
        clipped = np.frombuffer(MusicPreview.with_gain(loud, 4.0), np.int16)
        self.assertEqual(int(clipped.max()), 32767, "clipped, not wrapped around")
        self.assertEqual(MusicPreview.match_gain(loud, b"\0\0" * 100), 1.0, "silence: leave it alone")
        soft = (np.sin(np.arange(R) / R * 2 * np.pi * 440) * 2000).astype(np.int16).tobytes()    # RMS ~1400
        self.assertAlmostEqual(MusicPreview.match_gain(soft, soft), 3000.0 / 1414.2, places=2,
                               msg="a quiet tune is matched up to the floor, not to itself")


class PreviewCacheTests(unittest.TestCase):
    def test_an_edited_recording_is_decoded_again(self):
        import shutil
        if not shutil.which("ffmpeg"):
            self.skipTest("needs ffmpeg")
        from khvcemu.music_preview import MusicPreview
        with tempfile.TemporaryDirectory() as d:
            rec = os.path.join(d, "r.wav")
            write_wav(rec, 1.0)
            p = MusicPreview()
            first = p.decode_recording(rec)
            self.assertIs(p.decode_recording(rec), first, "decoded once while unchanged")
            write_wav(rec, 2.0)
            self.assertGreater(len(p.decode_recording(rec)), len(first) * 1.5)
            for i in range(5):
                other = os.path.join(d, f"o{i}.wav")
                write_wav(other, 0.2)
                p.decode_recording(other)
            self.assertLessEqual(len(p._recordings), 3, "only a few are kept in memory")


class FakePreview:
    def __init__(self):
        self.played, self.renders = [], []

    def open(self):
        pass

    def render_tune(self, path, settings):
        self.renders.append(dict(settings))
        return (np.ones(1000, np.int16) * 1000).tobytes()

    def decode_recording(self, path):
        return (np.ones(3000, np.int16) * 250).tobytes()

    with_gain = staticmethod(__import__("khvcemu.music_preview", fromlist=["x"]).MusicPreview.with_gain)
    match_gain = staticmethod(__import__("khvcemu.music_preview", fromlist=["x"]).MusicPreview.match_gain)

    def play(self, raw):
        self.played.append(raw)

    def stop(self):
        self.played.append(None)

    def close(self):
        pass


class SoundTabMixTests(unittest.TestCase):
    def make_app(self, cfg):
        import tkinter as tk
        from khvcemu import launcher as L
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        os.makedirs(os.path.join(d, "mif"))
        os.makedirs(os.path.join(d, "mod", "11839"))
        for name in ("training.mid", "island.mid"):
            with open(os.path.join(d, "mod", "11839", name), "wb") as f:
                f.write(tune())
        self.saved = []
        old = (L.load_config, L.save_config)
        L.load_config = lambda: dict(cfg, dump=d)
        L.save_config = lambda c: self.saved.append(dict(c))
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
                pass
        self.addCleanup(destroy)
        self.L = L
        return root, L.Launcher(root)

    def pump(self, root, until, secs=5):
        end = time.time() + secs
        while not until() and time.time() < end:
            root.update()
            time.sleep(0.02)

    def test_picking_a_ready_made_mix_sets_the_sliders(self):
        root, app = self.make_app({})
        self.assertEqual(app.mix.get(), "As tuned")
        app.mix.set("More bass")
        app.mix_chosen()
        self.assertAlmostEqual(app.music_values()["bass"], 1.6)
        self.assertEqual(app.opts()["music"], ms.to_text(ms.preset("More bass")))
        self.assertEqual(str(app.del_btn.cget("state")), "disabled", "ready-made mixes cannot be deleted")
        app.music_vars["piano"].set(0.5)
        app.music_changed()                                   # moved a slider
        self.assertEqual(app.mix.get(), app.CUSTOM_MIX)
        app.mix.set("As tuned")
        app.mix_chosen()
        self.assertEqual(app.opts()["music"], "", "the As tuned mix puts every slider back")

    def test_favorites_saved_under_the_old_spelling_are_still_read(self):
        root, app = self.make_app({"music_profiles": {"big bass": "bass=1.5"}, "music_favourites": ["big bass"]})
        self.assertEqual(app.mix_favorites(), ["big bass"], "a launcher.json from an earlier build keeps its stars")
        app.mix.set("big bass")
        app.mix_chosen()                                       # the sliders take the mix, so it is the current one
        app.toggle_favorite()                                  # un-star it: the new key is written, the old one dropped
        self.assertEqual(app.cfg["music_favorites"], [])
        self.assertNotIn("music_favourites", app.cfg)
        app.close()

    def test_save_favorite_and_delete_your_own_mix(self):
        root, app = self.make_app({})
        L = self.L
        app.music_vars["piano"].set(0.6)
        app.music_vars["drums"].set(1.4)
        app.music_changed()
        real = (L.simpledialog.askstring, L.messagebox.askyesno, L.messagebox.showinfo)
        self.addCleanup(lambda: (setattr(L.simpledialog, "askstring", real[0]),
                                 setattr(L.messagebox, "askyesno", real[1]), setattr(L.messagebox, "showinfo", real[2])))
        L.messagebox.showinfo = lambda *a, **k: None
        L.simpledialog.askstring = lambda *a, **k: "big bass"
        L.messagebox.askyesno = lambda *a, **k: True
        app.save_mix()
        self.assertEqual(app.cfg["music_profiles"], {"big bass": "drums=1.4,piano=0.6"})
        self.assertEqual(app.mix.get(), "big bass")
        self.assertEqual(str(app.del_btn.cget("state")), "normal")
        app.toggle_favorite()
        self.assertEqual(app.cfg["music_favorites"], ["big bass"])
        self.assertEqual(app.mix_names()[0], "big bass", "favorites are listed first")
        self.assertEqual(app.mix.get(), "\u2605 big bass")
        app.mix.set("As tuned")
        app.mix_chosen()
        app.mix.set("\u2605 big bass")                        # switch back to it from the list
        app.mix_chosen()
        self.assertAlmostEqual(app.music_values()["piano"], 0.6)
        L.simpledialog.askstring = lambda *a, **k: "as TUNED"
        app.save_mix()                                        # a ready-made name is refused
        self.assertNotIn("as TUNED", app.cfg["music_profiles"])
        app.delete_mix()
        self.assertEqual(app.cfg["music_profiles"], {})
        self.assertEqual(app.cfg["music_favorites"], [])
        self.assertAlmostEqual(app.music_values()["piano"], 0.6, msg="deleting keeps the sliders")
        self.assertEqual(app.mix.get(), app.CUSTOM_MIX)
        app.close()

    def test_a_ready_made_mix_can_be_a_favorite(self):
        root, app = self.make_app({})
        app.mix.set("Big brass")
        app.mix_chosen()
        app.toggle_favorite()
        self.assertEqual(app.mix_names()[0], "Big brass")
        app.close()

    def test_hand_edited_mix_settings_do_not_break_it(self):
        root, app = self.make_app({"music_profiles": {"ok": "piano=0.5", 3: "x", "bad": 7},
                                   "music_favorites": "nope", "music_mix": ["?"]})
        self.assertIn("ok", app.mix_names())
        self.assertNotIn("bad", app.mix_names())
        app.close()

    def test_the_recording_volume_match_and_use_in_game(self):
        root, app = self.make_app({})
        rec = os.path.join(self.tmp.name, "my take.flac")
        open(rec, "wb").close()
        app.preview = FakePreview()
        app.music_refs()["training.mid"] = rec                # the old, plain-path form still works
        app.tune_changed()
        self.assertEqual(app.rec_entry("training.mid"), {"path": rec, "gain": 1.0, "in_game": False})
        self.assertEqual(str(app.match_btn.cget("state")), "normal")
        app.music_vars["master"].set(0.5)
        app.music_changed()
        app.match_level()
        self.pump(root, lambda: app.rec_entry("training.mid")["gain"] != 1.0)
        self.assertAlmostEqual(app.rec_entry("training.mid")["gain"], 4.0, msg="1000 vs 250: four times louder")
        self.assertEqual(app.preview.renders[-1]["master"], 1.0, "measured at Music volume 100%: the game adds it")
        app.music_vars["master"].set(1.0)
        app.music_changed()
        self.assertEqual(app.rec_gain_label.cget("text"), "400%")
        app.rec_gain.set(1.52)
        app.rec_gain_changed()
        self.assertAlmostEqual(app.rec_entry("training.mid")["gain"], 1.5)
        app.play_recording()
        self.pump(root, lambda: app.playing == "recording")
        self.assertEqual(np.frombuffer(app.preview.played[-1], np.int16)[0], 375, "played at its volume")
        self.assertEqual(str(app.rec_btn.cget("style")), "SmallOn.TButton", "the playing one is lit")
        self.assertEqual(str(app.ours_btn.cget("style")), "Small.TButton")
        app.stop_music()
        self.assertEqual(str(app.rec_btn.cget("style")), "Small.TButton")
        self.assertNotIn("--music-file", self.L.build_command(self.tmp.name, app.opts()))
        app.rec_in_game.set(True)
        app.rec_in_game_changed()
        self.assertIn("plays your recording", app.music_note.cget("text"))
        cmd = self.L.build_command(self.tmp.name, app.opts())
        self.assertEqual(cmd[cmd.index("--music-file") + 1], f"training.mid={rec}")
        self.assertEqual(cmd[cmd.index("--music-file-volume") + 1], "training.mid=1.5")
        os.remove(rec)
        self.assertNotIn("--music-file", self.L.build_command(self.tmp.name, app.opts()),
                         "a recording that is gone is not passed on")
        app.show_music_note()
        self.assertIn("missing", app.music_note.cget("text"), "and the note says so")
        app.close()

    def test_review_gaps_in_the_tab(self):
        root, app = self.make_app({"music_profiles": {"odd": "piano=0.52"},
                                   "music_favorites": ["odd", "odd"],
                                   "music_refs": {"training.mid": {"path": "a.flac", "gain": float("nan"),
                                                                   "in_game": "false"}}})
        L = self.L
        self.assertEqual(app.mix_names().count("odd"), 1, "a favorite listed twice shows once")
        app.mix.set("★ odd")
        app.mix_chosen()
        self.assertEqual(app.mix.get(), "★ odd", "a value off the 5% grid still counts as that mix")
        e = app.rec_entry("training.mid")
        self.assertEqual((e["gain"], e["in_game"]), (1.0, False), "NaN and the text 'false' are not trusted")
        # a double-click reset keeps the Mix box honest
        app.mix.set("More bass")
        app.mix_chosen()
        app.reset_music("bass")
        self.assertEqual(app.mix.get(), app.CUSTOM_MIX)
        # a name starting with the favorite star is refused
        real = (L.simpledialog.askstring, L.messagebox.showinfo)
        self.addCleanup(lambda: (setattr(L.simpledialog, "askstring", real[0]), setattr(L.messagebox, "showinfo", real[1])))
        told = []
        L.messagebox.showinfo = lambda *a, **k: told.append(a)
        L.simpledialog.askstring = lambda *a, **k: "★ sneaky"
        app.save_mix()
        self.assertNotIn("★ sneaky", app.cfg["music_profiles"])
        self.assertTrue(told)
        # the in-game recordings are worked out when the game starts, not saved twice in the config
        app.remember()
        self.assertNotIn("music_files", app.cfg)
        app.close()

    def test_switching_tune_during_a_match_sets_the_right_tune(self):
        import threading
        root, app = self.make_app({})
        rec = os.path.join(self.tmp.name, "my take.flac")
        open(rec, "wb").close()
        gate = threading.Event()
        app.preview = FakePreview()
        slow = app.preview.decode_recording
        app.preview.decode_recording = lambda path: (gate.wait(5), slow(path))[1]
        app.music_refs()["training.mid"] = {"path": rec, "gain": 1.0}
        app.tune_changed()
        app.match_level()                                    # measuring the title tune...
        app.tune.set("Swashbuckler's Island")         # ...and the player moves on
        root.update()
        gate.set()
        self.pump(root, lambda: app.rec_entry("training.mid")["gain"] != 1.0)
        self.assertAlmostEqual(app.rec_entry("training.mid")["gain"], 4.0, msg="the title tune got its level")
        self.assertEqual(app.rec_entry("island.mid")["gain"], 1.0, "the Island's was not touched")
        self.assertEqual(app.rec_gain_label.cget("text"), "100%", "the slider shows the Island's")
        app.close()

    def test_a_match_does_not_overwrite_a_volume_set_meanwhile(self):
        import threading
        root, app = self.make_app({})
        rec = os.path.join(self.tmp.name, "take.flac")
        open(rec, "wb").close()
        gate = threading.Event()
        app.preview = FakePreview()
        slow = app.preview.decode_recording
        app.preview.decode_recording = lambda path: (gate.wait(5), slow(path))[1]
        app.music_refs()["training.mid"] = {"path": rec, "gain": 1.0}
        app.tune_changed()
        app.match_level()
        app.rec_gain.set(0.7)                                # the player sets it by hand meanwhile
        app.rec_gain_changed()
        gate.set()
        end = time.time() + 1.0
        while time.time() < end:
            root.update()
            time.sleep(0.02)
        self.assertAlmostEqual(app.rec_entry("training.mid")["gain"], 0.7, msg="their choice wins")
        app.close()

    def test_a_hand_edited_recording_entry_is_tolerated(self):
        root, app = self.make_app({"music_refs": {"training.mid": {"path": 5, "gain": "x"},
                                                  "island.mid": {"path": "a.flac", "gain": 99, "in_game": 1}}})
        self.assertEqual(app.rec_entry("training.mid")["path"], "")
        self.assertEqual(app.rec_entry("island.mid")["gain"], 4.0, "clamped")
        self.assertEqual(str(app.rec_btn.cget("state")), "disabled")
        app.close()


class WonderlandVolumeTests(unittest.TestCase):
    """The Wonderland theme on the Setup tab: a play button and a volume the game uses too."""

    make_app = SoundTabMixTests.make_app
    pump = SoundTabMixTests.pump

    def engine(self, volume):
        from khvcemu.audio import AudioEngine
        return AudioEngine(EngineOverrideTests.E(), enabled=False, wonderland_volume=volume)

    def test_the_game_applies_the_volume_only_to_the_wonderland_theme(self):
        mid = tune()
        full = self.engine(1.0).decode(mid, "wonderland.mid")
        half = self.engine(0.5).decode(mid, "fs:/~/Wonderland.MID")
        self.assertAlmostEqual(int(np.abs(half).max()) / int(np.abs(full).max()), 0.5, places=2)
        self.assertTrue(np.array_equal(self.engine(0.5).decode(mid, "island.mid"), self.engine(1.0).decode(mid, "island.mid")))
        self.assertEqual(int(np.abs(self.engine(0.0).decode(mid, "wonderland.mid")).max()), 0)
        loud = self.engine(2.0).decode(mid, "wonderland.mid")
        self.assertGreater(int(np.abs(loud).max()), int(np.abs(full).max()))
        self.assertLessEqual(int(np.abs(loud).max()), 32767)
        eng = self.engine(0.5)
        eng.decode(mid, "wonderland.mid")
        eng.wonderland_volume = 1.0
        self.assertGreater(int(np.abs(eng.decode(mid, "wonderland.mid")).max()), int(np.abs(half).max()),
                           "another volume is not served from the cache")

    def test_command_line(self):
        self.assertNotIn("--wonderland-volume", self.L_build({}))
        cmd = self.L_build({"wonderland_volume": 0.6})
        self.assertEqual(cmd[cmd.index("--wonderland-volume") + 1], "0.6")

    def L_build(self, opts):
        from khvcemu import launcher as L
        return L.build_command("game", opts)

    def test_the_setup_tab_plays_the_theme_at_the_slider_volume(self):
        root, app = self.make_app({"wonderland_volume": 0.5})
        app.preview = FakePreview()
        self.assertEqual(str(app.wl_btn.cget("state")), "disabled", "no theme file, nothing to play")
        self.assertAlmostEqual(app.wl_volume.get(), 0.5)
        self.assertEqual(app.wl_label.cget("text"), "50%")
        wl = os.path.join(self.tmp.name, "Wonderland.mid")
        with open(wl, "wb") as f:
            f.write(tune())
        app.refresh()
        self.assertEqual(str(app.wl_btn.cget("state")), "normal")
        app.toggle_wonderland()
        self.pump(root, lambda: app.playing == "wonderland")
        self.assertEqual(np.frombuffer(app.preview.played[-1], np.int16)[0], 500, "1000 at 50%")
        self.assertEqual(app.wl_btn.cget("text"), "Stop")
        self.assertEqual(str(app.wl_btn.cget("style")), "SmallOn.TButton")
        app.wl_volume.set(1.0)
        app.wonderland_volume_changed()
        self.pump(root, lambda: np.frombuffer(app.preview.played[-1] or b"\0\0", np.int16)[0] == 1000)
        self.assertEqual(np.frombuffer(app.preview.played[-1], np.int16)[0], 1000, "re-played at the new volume")
        self.assertEqual(app.opts()["wonderland_volume"], 1.0)
        app.wl_volume.set(0.7)
        cmd = self.L.build_command(self.tmp.name, app.opts())
        self.assertEqual(cmd[cmd.index("--wonderland-volume") + 1], "0.7")
        app.toggle_wonderland()
        self.assertEqual(app.wl_btn.cget("text"), "Play")
        self.assertIsNone(app.playing)
        os.remove(wl)
        app.refresh()
        self.assertEqual(str(app.wl_btn.cget("state")), "disabled")
        app.close()


class FocusPauseOptionTests(unittest.TestCase):
    """Options tab: "Pause when the window loses focus"."""
    make_app = SoundTabMixTests.make_app

    def test_the_option_reaches_the_command_line_and_restore_defaults(self):
        root, app = self.make_app({})
        self.assertTrue(app.focus_pause.get(), "on by default")
        self.assertNotIn("--no-focus-pause", self.L.build_command(self.tmp.name, app.opts()))
        app.focus_pause.set(False)
        self.assertIn("--no-focus-pause", self.L.build_command(self.tmp.name, app.opts()))
        app.remember()
        self.assertIs(self.saved[-1]["pause_on_focus_loss"], False, "remembered")
        app.restore_defaults(ask=False)
        self.assertTrue(app.focus_pause.get())
        app.close()
        root2, app2 = self.make_app({"pause_on_focus_loss": False})
        self.assertFalse(app2.focus_pause.get(), "a saved choice is used")
        app2.close()

    def test_the_quit_question_option(self):
        root, app = self.make_app({})
        self.assertTrue(app.ask_quit.get(), "asks by default")
        self.assertNotIn("--no-quit-prompt", self.L.build_command(self.tmp.name, app.opts()))
        app.ask_quit.set(False)
        self.assertIn("--no-quit-prompt", self.L.build_command(self.tmp.name, app.opts()))
        app.restore_defaults(ask=False)
        self.assertTrue(app.ask_quit.get())
        # the game's "D = quit and don't ask again" writes launcher.json: the open launcher follows it
        self.L.load_config = lambda: {"ask_before_quit": False}
        app.check_states()
        self.assertFalse(app.ask_quit.get())
        self.assertIs(app.cfg["ask_before_quit"], False)
        app.close()
        root2, app2 = self.make_app({"ask_before_quit": False})
        self.assertFalse(app2.ask_quit.get(), "a saved choice is used")
        app2.close()

    def test_the_game_can_write_one_launcher_option_and_keeps_the_rest(self):
        import json
        from khvcemu.paths import set_launcher_option
        home = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, home, True)
        cfg = os.path.join(home, ".khvcemu", "launcher.json")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"scale": "2", "dump": "D:/game"}, f)
        self.assertTrue(set_launcher_option("ask_before_quit", False, home=home))
        with open(cfg, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"scale": "2", "dump": "D:/game", "ask_before_quit": False})
        os.remove(cfg)
        self.assertTrue(set_launcher_option("ask_before_quit", False, home=home), "even with no file yet")
        from khvcemu.paths import get_launcher_option
        self.assertIs(get_launcher_option("ask_before_quit", True, home=home), False, "and it reads back")
        self.assertEqual(get_launcher_option("nothing", 7, home=home), 7)
        self.assertEqual(get_launcher_option("x", "d", home=tempfile.mkdtemp()), "d", "no file: the default")

    def test_the_dark_screen_option(self):
        root, app = self.make_app({})
        self.assertFalse(app.dark.get(), "off by default")
        self.assertNotIn("--dark-screen", self.L.build_command(self.tmp.name, app.opts()))
        app.dark.set(True)
        self.assertIn("--dark-screen", self.L.build_command(self.tmp.name, app.opts()))
        app.remember()
        self.assertIs(self.saved[-1]["dark_screen"], True)
        app.restore_defaults(ask=False)
        self.assertFalse(app.dark.get())
        app.close()
        root2, app2 = self.make_app({"dark_screen": True})
        self.assertTrue(app2.dark.get(), "a saved choice is used")
        app2.close()

    def test_the_screenshot_folder_option(self):
        from khvcemu.paths import default_screenshot_dir
        root, app = self.make_app({})
        self.assertEqual(app.screenshots.get(), "")
        self.assertNotIn("--screenshots", self.L.build_command(self.tmp.name, app.opts()), "empty: the default folder")
        app.screenshots.set("  D:/My Pictures/kh  ")
        cmd = self.L.build_command(self.tmp.name, app.opts())
        self.assertEqual(cmd[cmd.index("--screenshots") + 1], "D:/My Pictures/kh")
        app.remember()
        self.assertEqual(self.saved[-1]["screenshots"], "D:/My Pictures/kh")
        app.restore_defaults(ask=False)
        self.assertEqual(app.screenshots.get(), "")
        app.close()
        home = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, home, True)
        self.assertEqual(default_screenshot_dir(home), os.getcwd(), "no Pictures folder: where it always went")
        os.makedirs(os.path.join(home, "Pictures"))
        self.assertEqual(default_screenshot_dir(home), os.path.join(home, "Pictures", "khvcemu"))


if __name__ == "__main__":
    unittest.main()
