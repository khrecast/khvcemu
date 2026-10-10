"""The Android core's handling of the Wonderland splash: Soft 1 on it starts khvcemu's pages, they hold the game and turn with
Soft 1, Action or a tap, and after the last one the game gets its Continue press and does not see the time that passed."""
import importlib.util
import os
import sys
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from khvcemu.keys import AVK  # noqa: E402


def load_core():
    path = os.path.join(ROOT, "android", "app", "src", "main", "python", "recast_app.py")
    spec = importlib.util.spec_from_file_location("recast_app_lm_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeEmu:
    def __init__(self):
        self.wonderland_splash_up = True
        self.keys_held = set()
        self._t0 = 100.0
        self.events = []

    def key_down(self, avk):
        self.events.append(("down", avk))

    def key_up(self, avk):
        self.events.append(("up", avk))


def make_game(module):
    g = object.__new__(module._Game)
    g.AVK = AVK
    g.emu = FakeEmu()
    g.taps = module.collections.deque()
    g.key_script = []
    g.lm_pages, g.lm_start, g.lm_next, g.lm_serial, g.lm_t0, g.lm_paused = [], False, False, 0, 0.0, 0.0
    g.lm_ended = 0.0
    g.soft1_down = 0.0
    g._log = lambda line: None
    g.paused_at = None
    g.played = False
    g.messages = module.collections.deque(maxlen=4)
    g.requests = module.collections.deque()

    class Slots:
        def __init__(self):
            self.calls = []

        def save(self, slot):
            time.sleep(0.05)
            self.calls.append(("save", slot))
            return "Saved to slot %s" % slot

        def load(self, slot):
            self.calls.append(("load", slot))
            return "Loaded slot %s" % slot if slot != 9 else "Slot 9 is empty"

        autosave = None
    g.slots = Slots()
    return g


class LostMediaCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = load_core()

    def test_soft1_on_the_splash_starts_the_pages_and_the_game_does_not_see_it(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._press(AVK["SOFT1"], False)
        self.assertEqual(g.emu.events, [], "nothing reached the game")
        self.assertTrue(g._lost_media())
        self.assertEqual(len(g.lm_pages), 2)

    def test_other_keys_still_reach_the_game_on_the_splash(self):
        g = make_game(self.core)
        g._press(AVK["UP"], True)
        self.assertEqual(g.emu.events, [("down", AVK["UP"])])

    def test_the_pages_turn_and_then_the_game_gets_continue_and_the_clock_is_kept(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g.lm_t0 = time.monotonic() - 5.0                       # the pages have been up for five seconds
        before = g.emu._t0
        g._press(AVK["SELECT"], True)                          # Action turns the page
        self.assertTrue(g._lost_media())
        self.assertEqual(len(g.lm_pages), 1)
        g._press(AVK["SOFT1"], True)                           # Soft 1 turns the last one
        self.assertFalse(g._lost_media())
        self.assertFalse(g.emu.wonderland_splash_up)
        self.assertEqual(g.emu.events, [("down", AVK["SOFT1"])], "the game now gets its Continue")
        self.assertAlmostEqual(g.emu._t0 - before, 5.0, delta=0.5, msg="the game's clock skips the pages' time")
        self.assertEqual(len(g.key_script), 1)                 # and Continue is released a moment later
        self.assertEqual(g.key_script[0][1:], ["up", AVK["SOFT1"]])

    def test_a_tap_turns_the_page_and_other_keys_do_nothing_meanwhile(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g._press(AVK["UP"], True)
        self.assertEqual(g.emu.events, [], "no key reaches the game while the pages are up")
        g.taps.append((80.0, 100.0))
        g._handle_taps()
        self.assertTrue(g.lm_next)
        g._lost_media()
        self.assertEqual(len(g.lm_pages), 1)

    def test_the_time_the_app_spent_paused_is_not_counted_twice(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g.lm_t0 = time.monotonic() - 10.0
        g.lm_paused = 4.0                                      # four of those ten seconds the loop already added to the clock
        before = g.emu._t0
        g.lm_next = True
        g._lost_media()
        g.lm_next = True
        g._lost_media()
        self.assertAlmostEqual(g.emu._t0 - before, 6.0, delta=0.5)

    def test_the_finger_that_turned_the_last_page_does_not_cut_the_continue_press_short(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g.lm_next = True
        g._lost_media()
        g.lm_next = True
        g._lost_media()                                        # the last page is gone: the game was given its Continue
        g.emu.events.clear()
        g._press(AVK["SOFT1"], False)                          # the player lifts the finger at once
        self.assertEqual(g.emu.events, [], "a physical release right after the pages is not passed on")
        g._press(AVK["SOFT1"], False, scripted=True)           # the scripted release, 0.15 s later, is
        self.assertEqual(g.emu.events, [("up", AVK["SOFT1"])])

    def test_a_menu_load_while_the_pages_are_up_ends_them(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g.requests.append(("load", "1"))
        g._handle_requests()
        self.assertEqual(g.slots.calls, [("load", 1)])
        self.assertEqual(g.lm_pages, [])

    def test_a_failed_menu_load_leaves_the_pages_up(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g.requests.append(("load", "9"))                        # an empty slot
        g._handle_requests()
        self.assertEqual(len(g.lm_pages), 2, "nothing was loaded: the pages are still up")

    def test_a_new_press_of_soft1_after_the_pages_is_released_normally(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        g.lm_next = True
        g._lost_media()
        g.lm_next = True
        g._lost_media()
        time.sleep(0.01)
        g.emu.events.clear()
        g._press(AVK["SOFT1"], True)                            # a fresh press right after the pages
        g._press(AVK["SOFT1"], False)                           # and its release must not be swallowed
        self.assertEqual(g.emu.events, [("down", AVK["SOFT1"]), ("up", AVK["SOFT1"])])

    def test_the_time_a_save_takes_while_the_pages_are_up_is_not_counted_twice(self):
        g = make_game(self.core)
        g._press(AVK["SOFT1"], True)
        g._lost_media()
        before = g.emu._t0
        g.requests.append(("save", "1"))
        g._handle_requests()
        self.assertGreater(g.emu._t0 - before, 0.04, "the save's time is added to the clock")
        self.assertAlmostEqual(g.lm_paused, g.emu._t0 - before, delta=0.01, msg="and kept out of the pages' hold")

    def test_without_a_font_the_game_just_continues(self):
        g = make_game(self.core)
        from khvcemu import lostmedia
        original = lostmedia.build_screens_pil
        lostmedia.build_screens_pil = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no font"))
        try:
            g._press(AVK["SOFT1"], True)
            self.assertFalse(g._lost_media())
        finally:
            lostmedia.build_screens_pil = original
        self.assertFalse(g.emu.wonderland_splash_up)
        self.assertEqual(g.emu.events, [("down", AVK["SOFT1"])])


if __name__ == "__main__":
    unittest.main()
