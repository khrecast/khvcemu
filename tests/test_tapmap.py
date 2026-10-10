"""tapmap: a tap on the game's picture becomes the keys that do what the tapped thing says."""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu import tapmap  # noqa: E402


def item(text, x0, y0, x1, y1, fg=100):
    return {"text": text, "box": (x0, y0, x1, y1), "fg": fg}


def blank():
    return np.zeros((220, 176), np.uint16)


def paint(frame, it, color):
    """Fill the strip left of a string, which is where the code looks for its background."""
    x0, y0, x1, y1 = it["box"]
    frame[y0:y1, max(0, x0 - 8):x0] = color


class SoftkeyTests(unittest.TestCase):
    ITEMS = [item("Continue", 7, 199, 57, 213), item("Options", 122, 199, 165, 213)]

    def test_each_bar_presses_its_own_key(self):
        self.assertEqual(tapmap.resolve_tap(30, 206, self.ITEMS, blank()), ["SOFT1"])
        self.assertEqual(tapmap.resolve_tap(143, 206, self.ITEMS, blank()), ["SOFT2"])

    def test_a_bar_without_a_label_does_nothing(self):
        only_left = [self.ITEMS[0]]
        self.assertEqual(tapmap.resolve_tap(150, 206, only_left, blank()), [])
        self.assertEqual(tapmap.resolve_tap(30, 206, [], blank()), [])

    def test_a_tap_above_the_bars_is_not_a_softkey(self):
        self.assertEqual(tapmap.resolve_tap(30, 150, self.ITEMS, blank()), [])


class ListTests(unittest.TestCase):
    def menu(self, selected, n=5):
        """Entries 25 rows apart; the selected one has another text color and another background."""
        items, frame = [], blank()
        for i in range(n):
            it = item("Entry %d" % i, 105, 90 + 25 * i, 167, 104 + 25 * i, fg=65516 if i == selected else 50688)
            items.append(it)
            paint(frame, it, 25356 if i == selected else 0)
        return items, frame

    def test_the_first_tap_moves_the_highlight_and_a_tap_on_it_presses_action(self):
        items, frame = self.menu(selected=0)
        self.assertEqual(tapmap.resolve_tap(130, 97, items, frame), ["SELECT"])
        self.assertEqual(tapmap.resolve_tap(130, 122, items, frame), ["DOWN"])
        self.assertEqual(tapmap.resolve_tap(130, 172, items, frame), ["DOWN"] * 3)
        items, frame = self.menu(selected=3)
        self.assertEqual(tapmap.resolve_tap(130, 97, items, frame), ["UP"] * 3)
        self.assertEqual(tapmap.resolve_tap(130, 172, items, frame), ["SELECT"])

    def test_a_tap_beside_or_between_entries_does_nothing(self):
        items, frame = self.menu(selected=0)
        self.assertEqual(tapmap.resolve_tap(20, 97, items, frame), [], "far to the left of the list")
        self.assertEqual(tapmap.resolve_tap(130, 20, items, frame), [], "above the list")

    def test_the_last_entry_may_reach_into_the_softkey_band(self):
        items, frame = self.menu(selected=0)                       # the 5th entry spans rows 190 to 204
        self.assertEqual(tapmap.resolve_tap(135, 197, items, frame), ["DOWN"] * 4)

    def test_a_paragraph_is_not_a_menu(self):
        items, frame = [], blank()
        for i, text in enumerate(("Sora, bearer of the", "magical KeyBlade, is", "returning from a", "quest with")):
            items.append(item(text, 31, 48 + 14 * i, 140, 62 + 14 * i, fg=0))
        self.assertEqual(tapmap.resolve_tap(80, 70, items, frame), [], "every line looks alike: nothing is highlighted")

    def test_two_entries_are_not_a_list(self):
        items, frame = self.menu(selected=0, n=2)
        self.assertEqual(tapmap.resolve_tap(130, 97, items, frame), [])

    def test_a_header_above_a_list_is_not_an_entry(self):
        items, frame = [], blank()
        header = item("OPTIONS", 61, 12, 114, 26, fg=0)
        items.append(header)
        paint(frame, header, 61278)
        for i in range(4):
            it = item("Row %d" % i, 60, 41 + 22 * i, 115, 55 + 22 * i, fg=61278 if i == 1 else 16937)
            items.append(it)
            paint(frame, it, 31762 if i == 1 else 52795)
        self.assertEqual(tapmap.resolve_tap(87, 19, items, frame), [], "the header is not tappable")
        self.assertEqual(tapmap.resolve_tap(87, 48, items, frame), ["UP"])
        self.assertEqual(tapmap.resolve_tap(87, 70, items, frame), ["SELECT"])

    def test_no_frame_means_no_guess(self):
        items, _frame = self.menu(selected=0)
        self.assertEqual(tapmap.resolve_tap(130, 97, items, None), [])


@unittest.skipUnless(os.environ.get("KH_DUMP"), "needs the game files (KH_DUMP)")
class RealScreensTests(unittest.TestCase):
    """The title menu, the intro page, the pause screen and the Options menu of the real game."""

    def test_taps_on_the_games_own_screens(self):
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        from khvcemu.keys import AVK
        from khvcemu.runtime import Emulator
        logs, opened = [], []
        emu = Emulator(os.environ["KH_DUMP"], tempfile.mkdtemp(), realtime=False, audio=False, log=logs.append,
                       verbose=True)

        class Rec:
            def on_file_opened(self, name, mode):
                opened.append(name.lower())
        emu.hooks.append(Rec())
        emu.start()

        def step(ms, key=None, hold=140):
            t, down = 0, False
            while t < ms:
                if key and t == 0:
                    emu.key_down(AVK[key])
                    down = True
                if key and down and t >= hold:
                    emu.key_up(AVK[key])
                    down = False
                emu.advance(10)
                emu.run_due()
                t += 10
            if down:
                emu.key_up(AVK[key])

        def tap(x, y):
            emu.display.build_overlay(emu.last_frame)
            return tapmap.resolve_tap(x, y, emu.display.text_items, emu.last_frame)

        step(11000)
        self.assertEqual(tap(130, 97), ["SELECT"], "New Game is the highlighted entry")
        self.assertEqual(tap(130, 122), ["DOWN"])
        self.assertEqual(tap(135, 197), ["DOWN"] * 4, "Quit, whose row reaches into the softkey band")
        self.assertEqual(tap(40, 100), [], "Sora, not a button")
        step(300, "SELECT")
        mark = len(logs)
        for _ in range(60):
            step(1500)
            drawn = [m.group(1) for line in logs[mark:] if "DrawText" in line for m in [re.search(r"'(.*)'", line)] if m]
            mark = len(logs)
            if any("training_part1" in n for n in opened):
                break
            if "Continue" in drawn:
                self.assertEqual(tap(30, 205), ["SOFT1"], "the Continue bar on an intro page")
                self.assertEqual(tap(150, 205), [], "the right bar has no label")
                step(300, "SOFT1")
        step(8000)
        self.assertEqual(tap(20, 205), [], "a corner of the screen during play has no softkey label")
        step(600, "SOFT1")
        self.assertEqual(tap(30, 206), ["SOFT1"], "the pause screen's Continue")
        self.assertEqual(tap(143, 206), ["SOFT2"], "and its Options")
        step(800, "SOFT2")
        self.assertEqual(tap(87, 48), ["SELECT"], "the Options menu: Controls is highlighted")
        keys = tap(87, 136)
        self.assertEqual(keys, ["DOWN"] * 4, "About is four entries down")
        for k in keys:
            step(200, k, hold=80)
        step(500)
        self.assertEqual(tap(87, 136), ["SELECT"], "after the four Down presses About is the highlighted entry")


if __name__ == "__main__":
    unittest.main()
