"""The play timer: no game files needed."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu.playtime import MAX_GAP_MS, PlayTimer  # noqa: E402


class FakeEmu:
    def __init__(self):
        self.now = 0
        self.logs = []

    def clock_ms(self):
        return self.now

    def log(self, s):
        self.logs.append(s)


class PlayTimerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "playtime.json")
        self.emu = FakeEmu()
        self.t = PlayTimer(self.emu, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def play(self, seconds, step=40):
        for _ in range(int(seconds * 1000 / step)):
            self.emu.now += step
            self.t.tick()

    def test_time_counts_only_inside_a_world(self):
        self.play(5)                                   # title screen
        self.t.file_opened("mif/island.m3g")
        self.play(90)
        self.assertEqual(self.t.totals["island"], 90_000)

    def test_summary_ends_the_run_and_the_next_one_starts_from_zero(self):
        self.t.file_opened("island.m3g")
        self.play(120)
        self.t.summary()
        self.t.summary()                               # drawn every frame: must act once
        self.assertEqual(self.t.clears, {"island": 120_000})
        self.assertNotIn("island", self.t.totals)
        self.play(30)                                  # Wonderland screens: nobody's world
        self.t.summary()                               # the stand-in's second Summary
        self.assertEqual(self.t.clears, {"island": 120_000}, "not overwritten by a ghost clear")
        self.t.file_opened("island.m3g")
        self.play(10)
        self.assertEqual(self.t.totals["island"], 10_000)

    def test_loading_a_save_state_neither_adds_nor_removes_time(self):
        self.t.file_opened("castle.m3g")
        self.play(60)
        self.emu.now = 5_000                           # a state from earlier: the clock jumps back
        self.t.resync("castle")
        self.play(20)
        self.assertEqual(self.t.totals["castle"], 80_000, "time already played is not taken back")
        self.emu.now = 9_999_000                       # a state from later: the clock jumps forward
        self.t.resync("castle")
        self.play(5)
        self.assertEqual(self.t.totals["castle"], 85_000, "the jump itself is not counted")

    def test_a_state_taken_outside_a_world_counts_nothing(self):
        self.t.resync(None)
        self.play(30)
        self.assertEqual(self.t.totals, {})

    def test_a_long_silence_is_not_play(self):
        self.t.file_opened("agrabah.m3g")
        self.play(10)
        self.emu.now += MAX_GAP_MS + 1
        self.t.tick()
        self.assertEqual(self.t.totals["agrabah"], 10_000)

    def test_totals_survive_quitting_and_adding_up_across_sittings(self):
        self.t.file_opened("island.m3g")
        self.play(100)
        self.t.save()
        again = PlayTimer(FakeEmu(), self.path)
        self.assertEqual(again.totals, {"island": 100_000})
        again.emu.now = 0
        again.resync("island")                         # Load Game puts you back in the world
        for _ in range(500):
            again.emu.now += 40
            again.tick()
        self.assertEqual(again.totals["island"], 120_000)

    def test_a_damaged_file_is_ignored(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(PlayTimer(self.emu, self.path).totals, {})

    def test_every_posted_score_is_logged_with_its_time(self):
        self.t.file_opened("island.m3g")
        self.play(754)
        self.t.summary()
        url = "http://x/disney/rank.php?uid=&aid=KH&lid=wonderland&s=918&t=8526672&u1=44&u2="
        self.t.on_post(url)                            # the Wonderland prompt repeats the Island run
        self.t.on_post("http://x/disney/rankex.php?lid=island&s=1&t=0")    # not a post
        self.assertTrue(any("12:34 of play" in m and "918" in m for m in self.emu.logs), self.emu.logs)
        with open(self.t.csv_path(), encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        self.assertEqual(lines[0], "when,event,world,score,play_seconds,game_t")
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(lines[1].endswith(",clear,island,,754,"), lines[1])
        self.assertTrue(lines[2].endswith(",post,wonderland,918,754,8526672"), lines[2])

    def test_every_clear_is_logged_even_when_no_score_is_posted(self):
        self.t.file_opened("island.m3g")
        self.play(300)
        self.t.summary()
        self.t.summary()                               # drawn again on the next frame: still one row
        self.t.file_opened("agrabah.m3g")
        self.play(200)
        self.t.summary()
        with open(self.t.csv_path(), encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(lines[1].endswith(",clear,island,,300,"), lines[1])
        self.assertTrue(lines[2].endswith(",clear,agrabah,,200,"), lines[2])

    def test_a_log_from_before_clears_were_logged_keeps_its_rows(self):
        with open(self.t.csv_path(), "w", encoding="utf-8") as f:
            f.write("when,world,score,play_seconds,game_t\n"
                    "2026-10-01 12:00:00,island,931,1430,8526672\n")
        self.t.file_opened("castle.m3g")
        self.play(250)
        self.t.summary()
        with open(self.t.csv_path(), encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        self.assertEqual(lines[0], "when,event,world,score,play_seconds,game_t")
        self.assertEqual(lines[1], "2026-10-01 12:00:00,post,island,931,1430,8526672")
        self.assertTrue(lines[2].endswith(",clear,castle,,250,"), lines[2])

    def test_the_time_to_send_is_whole_seconds_for_the_right_world(self):
        self.t.file_opened("island.m3g")
        self.play(754.4)
        self.t.summary()
        url = "http://x/disney/rank.php?uid=&aid=KH&lid=%s&s=918&t=1&u1=1&u2="
        self.assertEqual(self.t.seconds_for_url(url % "island"), 754)
        self.assertEqual(self.t.seconds_for_url(url % "wonderland"), 754, "that screen repeats the Island run")
        self.assertIsNone(self.t.seconds_for_url(url % "castle"))

    def test_an_unmeasured_world_is_logged_as_such(self):
        self.t.on_post("http://x/disney/rank.php?uid=&aid=KH&lid=castle&s=5&t=9&u1=1&u2=")
        self.assertTrue(any("not measured" in m for m in self.emu.logs))


class SummaryStatsTests(unittest.TestCase):
    """Munny, EXP and Level are read off the Summary screen as the game draws it."""

    POST = "http://x/disney/rank.php?uid=&aid=KH&lid=island&s=%s&t=1&u1=1&u2="

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.emu = FakeEmu()
        self.t = PlayTimer(self.emu, os.path.join(self.tmp.name, "playtime.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def summary_screen(self, munny=931, exp=6, level=2, strength=3, defense=2, score=None, only=None):
        """What the game draws, in the order it draws it (taken from a real run): the heading,
        the softkeys, then a label and its number on each row."""
        score = munny + 100 * exp if score is None else score
        t = self.t
        t.text_drawn("SUMMARY", 60, 12)
        t.text_drawn("(Game autosaved)", 35, 28)
        t.text_drawn("Continue", 7, 199)
        t.text_drawn("Replay", 125, 199)
        for i, (label, value) in enumerate((("Munny", munny), ("Strength", strength), ("Defense", defense),
                                            ("EXP", exp), ("Level", level), ("Score", score))):
            y = 55 + 19 * i
            t.text_drawn(label, 26, y)
            if only is None or label in only:
                t.text_drawn(str(value), 142, y)

    def test_the_numbers_on_the_summary_screen_are_read(self):
        self.summary_screen()
        self.assertEqual(self.t.stats, {"munny": 931, "exp": 6, "level": 2, "score": 1531})
        self.assertEqual(self.t.stats_for_url(self.POST % 1531), {"munny": 931, "exp": 6, "level": 2})

    def test_a_label_without_its_number_does_not_borrow_another_rows(self):
        self.summary_screen(only={"Munny", "EXP", "Score"})        # Level's number was never drawn
        self.assertEqual(self.t.stats, {"munny": 931, "exp": 6, "score": 1531})
        self.assertEqual(self.t.stats_for_url(self.POST % 1531), {"munny": 931, "exp": 6},
                         "a missing Level is just left out")

    def test_the_screen_is_drawn_every_frame_and_each_pass_starts_afresh(self):
        self.summary_screen(munny=100, exp=1)
        self.summary_screen(munny=931, exp=6)                       # the next frame, or the next world
        self.assertEqual(self.t.stats["munny"], 931)
        self.t.text_drawn("SUMMARY", 60, 12)                        # a new pass: nothing carried over
        self.assertEqual(self.t.stats, {})

    def test_numbers_that_do_not_make_the_score_are_never_sent(self):
        self.summary_screen()
        self.assertIsNone(self.t.stats_for_url(self.POST % 1530), "another score than the screen showed")
        self.summary_screen(score=1600)                             # the screen contradicts itself
        self.assertIsNone(self.t.stats_for_url(self.POST % 1531))
        self.assertIsNone(self.t.stats_for_url(self.POST % "abc"))
        self.assertIsNone(self.t.stats_for_url("http://x/disney/rankex.php?lid=island&s=1531"), "not a post")
        self.assertIsNone(PlayTimer(self.emu, os.path.join(self.tmp.name, "other.json")).stats_for_url(self.POST % 1531),
                          "nothing read yet")

    def test_other_text_is_not_mistaken_for_a_number(self):
        t = self.t
        t.text_drawn("Munny", 26, 55)
        t.text_drawn("12 coins", 142, 55)
        t.text_drawn("-5", 142, 55)
        t.text_drawn("1234567890123", 142, 55)
        self.assertEqual(t.stats, {})
        t.text_drawn("42", 142, 56)                                 # a different row
        self.assertEqual(t.stats, {})
        t.text_drawn("42", 142, 55)
        self.assertEqual(t.stats, {"munny": 42})

    def test_the_summary_still_ends_the_run(self):
        self.emu.now = 0
        self.t.file_opened("island.m3g")
        self.t.tick()
        for _ in range(75):                          # the game's frames, ten seconds apart
            self.emu.now += 10_000
            self.t.tick()
        self.summary_screen()
        self.assertEqual(self.t.clears["island"], 750_000)
        self.assertIsNone(self.t.world)


if __name__ == "__main__":
    unittest.main()
