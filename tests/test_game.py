"""End-to-end tests against the real game. They need the dump:

    KH_DUMP=/path/to/dump python -m unittest tests.test_game -v

(the folder that contains mif/ and mod/). Each test runs the game headless on a
virtual clock, so they take ~20-60 s of wall time each.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu import chapters, m3g  # noqa: E402
from khvcemu.keys import AVK  # noqa: E402
from khvcemu.runtime import Emulator  # noqa: E402

DUMP = os.environ.get("KH_DUMP")


class Recorder:
    def __init__(self):
        self.opened = []

    def on_file_opened(self, name, mode):
        self.opened.append(name.lower())


@unittest.skipUnless(DUMP and os.path.isdir(os.path.join(DUMP, "mif")), "set KH_DUMP to run")
class GameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="khvcemu_test_")
        self.logs = []
        self.emu = Emulator(DUMP, self.tmp, realtime=False, audio=False, log=self.logs.append)
        self.emu.audio.capture = []
        self.rec = Recorder()
        self.emu.hooks.append(self.rec)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_ms(self, ms, keys=(), holds=()):
        """keys: [(t, name)], holds: [(t0, t1, name)] relative to now."""
        emu = self.emu
        events = []
        for t, k in keys:
            events += [(t, "down", k), (t + 150, "up", k)]
        for a, b, k in holds:
            events += [(a, "down", k), (b, "up", k)]
        events.sort()
        t = 0
        while t < ms:
            while events and events[0][0] <= t:
                _, what, k = events.pop(0)
                (emu.key_down if what == "down" else emu.key_up)(AVK[k])
            emu.advance(10)
            emu.run_due()
            t += 10

    def _verbose(self):
        """Swap in an emulator that logs what the game draws, so a test can react to
        the screen instead of counting on how many pages the text takes."""
        self.emu = Emulator(DUMP, self.tmp, realtime=False, audio=False, verbose=True,
                            log=self.logs.append)
        self.emu.audio.capture = []
        self.emu.hooks.append(self.rec)

    def run_auto(self, ms, keys=(), holds=(), until=None, step=1500):
        """run_ms, but also press Continue whenever the game has been drawing it: the
        number of journal and splash pages depends on the text font. Needs _verbose().
        Stops early once until() is true. Returns the game ms that ran."""
        import re
        emu = self.emu
        events = []
        for t, k in keys:
            events += [(t, "down", k), (t + 150, "up", k)]
        for a, b, k in holds:
            events += [(a, "down", k), (b, "up", k)]
        events.sort()
        t, mark = 0, len(self.logs)
        while t < ms:
            while events and events[0][0] <= t:
                _, what, k = events.pop(0)
                (emu.key_down if what == "down" else emu.key_up)(AVK[k])
            emu.advance(10)
            emu.run_due()
            t += 10
            if t % step == 0:
                drawn = [m.group(1) for l in self.logs[mark:] if "DrawText" in l
                         for m in [re.search(r"'(.*)'", l)] if m]
                mark = len(self.logs)
                if "Continue" in drawn:
                    events += [(t, "down", "SOFT1"), (t + 150, "up", "SOFT1")]
                    events.sort()
                if until and until():
                    break
        return t

    def test_boots_to_title_menu(self):
        self.emu.start()
        self.run_ms(11000)
        self.assertGreater(self.emu.frames, 200)
        self.assertEqual(self.emu.faults, 0)
        lit = np.count_nonzero(self.emu.last_frame) / self.emu.last_frame.size
        self.assertGreater(lit, 0.2, "title screen should be drawn")
        self.assertIn("swerve.m3g", self.rec.opened)
        self.assertTrue(any("training.mid" in n for n, _ in self.emu.audio.capture), "title music")

    def _load_world(self, world):
        self._verbose()
        chapters.install_save(self.emu, world)
        self.emu.start()
        # Load Game, then page through the journal text and the world splash
        self.run_ms(14000, keys=[(11000, "DOWN"), (12000, "SELECT")])
        self.run_auto(60000, until=lambda: any(
            n.startswith(world + "_") for n in self.rec.opened))
        self.assertIn(f"{world}.m3g", self.rec.opened)
        after = self.rec.opened[self.rec.opened.index(f"{world}.m3g") + 1:]
        self.assertTrue(any(n.startswith(world + "_") for n in after),
                        f"{world} scene assets should load after Continue")
        self.assertEqual(self.emu.faults, 0)
        self.assertFalse(any("0x01005000" in l or "AEECLSID_WEB" in l for l in self.logs),
                         "an installed episode must not trigger a download")

    def test_load_each_world(self):
        saves = chapters.find_save_files(DUMP)
        if not saves:
            self.skipTest("no savegame(<world>).dat files in the dump")
        for world in sorted(saves):
            with self.subTest(world=world):
                if world != sorted(saves)[0]:
                    self.tearDown()
                    self.setUp()
                self._load_world(world)

    def test_world_end_continues_past_lost_wonderland(self):
        """Make training end at once with 'summary wonderland' (what the Island's
        last script says) and check the game moves on to Agrabah."""
        old = b"addUIText 0 -1 1 -1 training_language mytext3 0"

        def inject(d):
            d, _ = m3g.replace_text(d, old, b"summary wonderland".ljust(len(old), b" "))
            d, _ = m3g.replace_text(d, chapters.WONDERLAND_SUMMARY, chapters.AGRABAH_SUMMARY)
            return d

        self._verbose()
        self.emu.vfs_hooks.append(lambda v: v.patchers.__setitem__("training_part1.m3g", inject))
        self.emu.start()
        self.run_ms(12000, keys=[(11000, "SELECT")])                  # New Game
        # Continue through the training journal until the level loads
        self.run_auto(60000, until=lambda: "training.m3g" in self.rec.opened)
        # dismiss the first tutorial dialog, then walk and jump while walking (plays a
        # .pmd sound effect). The jump has to land at the right moment, so press Action
        # every 2.5 s; the patched script then ends the world, and Continue is pressed
        # through the Summary, journals and splashes as they come
        jumps = [(9000 + 2500 * i, "SELECT") for i in range(8)]
        self.run_auto(120000, keys=[(5000, "SELECT")] + jumps, holds=[(8000, 50000, "UP")],
                      until=lambda: "agrabah_intro.m3g" in self.rec.opened)
        save = open(os.path.join(self.tmp, "files", "savegame.dat"), "rb").read()
        self.assertEqual(chapters.save_world(save), "agrabah", "autosave should name Agrabah")
        self.assertIn("agrabah.m3g", self.rec.opened)
        self.assertTrue(any(n.startswith("agrabah_") for n in self.rec.opened))
        played = [n for n, _ in self.emu.audio.capture]
        self.assertTrue(any(n.endswith(".pmd") for n in played), f"sound effects played: {played}")
        self.assertTrue(any("agrabah.mid" in n for n in played), "Agrabah music")
        self.assertEqual(self.emu.faults, 0)

    def test_island_ending_shows_wonderland_then_agrabah(self):
        """The Island's real ending ('summary wonderland'): the game shows the
        Wonderland journal and splash from the dump, then the stand-in
        wonderland.m3g carries on to Agrabah. Keys are chosen by reading what
        the game draws (dialog -> Action, high-score prompt -> Yes the first time and
        No after that, else Continue). The first score is posted to the offline
        leaderboard and the Summary shows its rank."""
        import re
        saves = chapters.find_save_files(DUMP)
        if "island" not in saves:
            self.skipTest("no savegame(island).dat in the dump")
        self.emu = Emulator(DUMP, self.tmp, realtime=False, audio=False, verbose=True,
                            log=self.logs.append)
        self.emu.hooks.append(self.rec)
        # make the Island world load its ending scene straight away
        old = b"ifVar ENGINE_VER == 1\r\nplaySequence ME gems_collectable_seq\r\nelse\r\nsetCollectables GEMS 4\r\nendif"
        new = b"loadClipart ME island_exit 1 1\r\nbreak".ljust(len(old), b" ")
        self.emu.vfs_hooks.append(
            lambda v: v.patchers.__setitem__("island.m3g", lambda d: m3g.replace_text(d, old, new)[0]))
        chapters.install_save(self.emu, "island")
        self.emu.leaderboard_url = "http://example.invalid"       # share the score (the request is captured below)
        self.shared = []
        patcher = mock.patch("khvcemu.web.share_scores",
                             side_effect=lambda url, base, *a, **k: self.shared.append(url) or b"*r|ok|anon~|island~1")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.emu.start()
        self.run_ms(14000, keys=[(11000, "DOWN"), (12000, "SELECT")])
        posted = False
        ranked = False
        for _ in range(60):                      # up to 90 s of game time
            mark = len(self.logs)
            self.run_ms(1500)
            drawn = [m.group(1) for l in self.logs[mark:] if "DrawText" in l
                     for m in [re.search(r"'(.*)'", l)] if m]
            text = " ".join(drawn)
            ranked = ranked or "Rank" in drawn
            if "HIGH SCORE" in text:
                key = "SOFT2" if posted else "SOFT1"    # post the first score only
                posted = True
            elif "Press <Action>" in text:
                key = "SELECT"
            elif "Continue" in drawn:
                key = "SOFT1"
            else:
                key = None
            if key:
                self.run_ms(300, keys=[(0, key)])
            if "agrabah_intro.m3g" in self.rec.opened:
                break
        opened = self.rec.opened
        for name in ("ro_wonderland_jtext.m3g", "wonderland.m3g", "ro_agrabah_jtext.m3g", "agrabah_intro.m3g"):
            self.assertIn(name, opened)
        self.assertLess(opened.index("ro_wonderland_jtext.m3g"), opened.index("ro_agrabah_jtext.m3g"))
        self.assertTrue(any("ro_wonderland_splash.png" in l for l in self.logs), "Wonderland splash")
        save = open(os.path.join(self.tmp, "files", "savegame.dat"), "rb").read()
        self.assertEqual(chapters.save_world(save), "agrabah")
        rows = self.emu.leaderboard.db.execute("SELECT lid, uid FROM scores").fetchall()
        self.assertEqual(rows, [("island", "local")], "the posted score is in the leaderboard")
        self.assertTrue(ranked, "the Summary should show the rank the leaderboard returned")
        self.assertIn("island", self.emu.playtime.clears, "the play timer saw the Island and its Summary")
        self.assertGreater(self.emu.playtime.clears["island"], 0)
        with open(self.emu.playtime.csv_path(), encoding="utf-8") as f:
            self.assertIn(",island,", f.read(), "the posted score was logged with its time")
        st = self.emu.playtime.stats
        self.assertTrue({"munny", "exp", "level", "score"} <= set(st), f"read off the Summary screen: {st}")
        self.assertEqual(st["munny"] + 100 * st["exp"], st["score"], "the game's own rule, as drawn")
        sent = [u for u in self.shared if "rank.php" in u]
        self.assertEqual(len(sent), 1, "the Wonderland repeat is not sent a second time")
        self.assertIn(f"mn={st['munny']}", sent[0])
        self.assertIn(f"ex={st['exp']}", sent[0])
        self.assertIn(f"lv={st['level']}", sent[0])
        self.assertIn("pt=", sent[0])
        self.assertEqual(self.emu.faults, 0)

    def test_a_recording_can_replace_the_title_music(self):
        """--music-file: the title screen plays the player's own recording instead of the MIDI,
        cut where the MIDI's music ends so the game's timing is unchanged."""
        import wave
        from khvcemu import midi_synth
        if not shutil.which("ffmpeg"):
            self.skipTest("needs ffmpeg")
        rec = os.path.join(self.tmp, "title.wav")
        t = np.arange(int(40 * midi_synth.RATE)) / midi_synth.RATE        # longer than the 16 s loop
        with wave.open(rec, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(midi_synth.RATE)
            w.writeframes((np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16).tobytes())
        self.emu = Emulator(DUMP, self.tmp, realtime=False, audio=False, log=self.logs.append,
                            music_files={"training.mid": {"path": rec, "gain": 0.5}})
        self.emu.audio.capture = []
        self.emu.start()
        self.run_ms(12000)
        name, pcm = self.emu.audio.capture[0]
        self.assertIn("training.mid", name)
        with open(os.path.join(DUMP, "mod", "11839", "training.mid"), "rb") as f:
            synth = midi_synth.render_midi(f.read())
        with open(os.path.join(DUMP, "mod", "11839", "training.mid"), "rb") as f:
            total = midi_synth.parse_midi(f.read())[1]
        self.assertGreater(len(synth), int(total * midi_synth.RATE), "the synth keeps its overlap tail")
        self.assertEqual(len(pcm), int(total * midi_synth.RATE), "a loop is cut where its music ends")
        self.assertAlmostEqual(np.abs(pcm[: midi_synth.RATE]).max(), 4000, delta=40, msg="the recording, at volume 0.5")
        self.assertEqual(self.emu.faults, 0)

    def test_save_state_round_trip(self):
        """A state saved mid-level reproduces the game exactly, both in a fresh
        emulator and in the running one; music resumes; autosaves rotate."""
        from khvcemu.savestate import StateError, StateSlots
        saves = chapters.find_save_files(DUMP)
        if "agrabah" not in saves:
            self.skipTest("no savegame(agrabah).dat in the dump")
        self._load_world("agrabah")
        self.run_ms(15000, keys=[(t, "SELECT") for t in range(0, 15000, 2500)])
        path = os.path.join(self.tmp, "s.khs")
        self.emu.save_state(path)
        self.assertTrue(os.path.isfile(os.path.splitext(path)[0] + ".png"), "thumbnail")
        walk = dict(holds=[(500, 2500, "UP")])
        self.run_ms(4000, **walk)
        ref = self.emu.last_frame.copy()

        fresh = Emulator(DUMP, os.path.join(self.tmp, "fresh"), realtime=False, audio=False,
                         log=self.logs.append)
        fresh.load_state(path)
        main, self.emu = self.emu, fresh
        self.run_ms(4000, **walk)
        self.assertTrue(np.array_equal(fresh.last_frame, ref), "fresh emulator diverged")
        self.assertEqual(fresh.faults, 0)

        self.emu = main
        main.load_state(path)                 # in place, over a later state
        self.run_ms(4000, **walk)
        self.assertTrue(np.array_equal(main.last_frame, ref), "in-place load diverged")
        self.assertEqual(main.faults, 0)

        # music: on the Agrabah splash, a loaded state keeps the tune going
        splash = Emulator(DUMP, os.path.join(self.tmp, "splash"), realtime=False, audio=False,
                          log=self.logs.append)
        chapters.install_save(splash, "agrabah")
        splash.start()
        self.emu = splash
        self.run_ms(14000, keys=[(11000, "DOWN"), (12000, "SELECT")])
        music = [o for o in splash.objects.values() if getattr(o, "voice", None) is not None
                 and o.name == "agrabah.mid"]
        self.assertTrue(music, "agrabah.mid should be playing on the splash")
        splash.save_state(path)
        splash.load_state(path)
        music = [o for o in splash.objects.values() if getattr(o, "voice", None) is not None
                 and o.name == "agrabah.mid"]
        self.assertTrue(music, "music should resume after loading")

        # autosaves: newest is auto1, three kept
        slots = StateSlots(main, os.path.join(self.tmp, "states"))
        for _ in range(4):
            slots.autosave()
            self.emu = main
            self.run_ms(200)
        names = sorted(f for f in os.listdir(slots.folder) if f.endswith(".khs"))
        self.assertEqual(names, ["auto1.khs", "auto2.khs", "auto3.khs"])
        self.assertIn("Loaded the autosave", slots.load(0))
        self.assertIn("empty", slots.load(5))

        # a damaged or foreign file is refused without touching the game
        bad = os.path.join(self.tmp, "bad.khs")
        with open(bad, "wb") as f:
            f.write(b"not a state")
        frames = main.frames
        with self.assertRaises(StateError):
            main.load_state(bad)
        self.run_ms(500)
        self.assertGreater(main.frames, frames)


if __name__ == "__main__":
    unittest.main()
