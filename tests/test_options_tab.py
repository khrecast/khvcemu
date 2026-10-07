"""The redesigned Options tab: the three kinds of autosave (timed with an editable interval, on quit, at loading
screens) and the screenshot list with its preview. The launcher tests skip themselves without a display."""
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import launcher as L  # noqa: E402
from khvcemu import savestate  # noqa: E402


def png(path, w=176, h=220, shade=90):
    """A small valid PNG (a flat grey picture) written without any imaging library."""
    raw = b"".join(b"\x00" + bytes([shade]) * (w * 3) for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class AutosaveCommandTests(unittest.TestCase):
    def flags(self, **opts):
        cmd = L.build_command("dump", opts)
        return [a for a in cmd if "autosave" in a] + ([cmd[cmd.index("--autosave-every") + 1]] if "--autosave-every" in cmd else [])

    def test_the_defaults_pass_nothing(self):
        self.assertEqual(self.flags(), [])
        self.assertEqual(self.flags(autosave=True, autosave_minutes=5, autosave_on_quit=True, autosave_on_loading=True), [])

    def test_each_kind_has_its_own_flag(self):
        self.assertEqual(self.flags(autosave_minutes=12), ["--autosave-every", "12"])
        self.assertEqual(self.flags(autosave=False), ["--autosave-every", "0"])
        self.assertEqual(self.flags(autosave_on_quit=False), ["--no-autosave-on-quit"])
        self.assertEqual(self.flags(autosave_on_loading=False), ["--no-autosave-on-loading"])
        self.assertEqual(self.flags(autosave=False, autosave_on_quit=False, autosave_on_loading=False), ["--no-autosave"])

    def test_the_interval_is_kept_sane(self):
        for text, want in (("12", 12.0), ("1.5", 1.5), ("1,5", 1.5), ("0", 1.0), ("-4", 1.0), ("9999", 120.0),
                           ("abc", 5.0), ("", 5.0), (None, 5.0), ("nan", 5.0), ("7.3", 7.5)):
            self.assertEqual(L.clean_minutes(text), want, repr(text))
        self.assertEqual(self.flags(autosave_minutes="abc"), [], "a typo means the default, five minutes")


class StateSlotKindsTests(unittest.TestCase):
    class FakeEmu:
        def __init__(self):
            self.now = 0
            self.applet_ptr = 1
            self.data_dir = tempfile.gettempdir()
            self.last_loading_ms = None

        def clock_ms(self):
            return self.now

    def test_the_timed_autosave_follows_the_interval_and_zero_turns_it_off(self):
        emu = self.FakeEmu()
        slots = savestate.StateSlots(emu, folder=tempfile.gettempdir())
        slots.autosave_every_ms = 2 * 60_000
        emu.now = 119_000
        self.assertFalse(slots.autosave_due())
        emu.now = 121_000
        self.assertTrue(slots.autosave_due())
        slots.autosave_every_ms = 0
        self.assertFalse(slots.autosave_due(), "0 minutes: no timed autosave")
        slots.autosave_every_ms = 2 * 60_000
        slots.autosave_enabled = False
        self.assertFalse(slots.autosave_due(), "F8 / --no-autosave turn all of them off")

    def test_the_loading_screen_autosave_has_its_own_switch(self):
        emu = self.FakeEmu()
        slots = savestate.StateSlots(emu, folder=tempfile.gettempdir())
        emu.last_loading_ms = 0
        emu.now = savestate.AREA_SAVE_DELAY_MS + 1
        self.assertTrue(slots.area_save_due())
        slots.autosave_on_loading = False
        self.assertFalse(slots.area_save_due())
        slots.autosave_every_ms = 60_000
        emu.now = 61_000
        self.assertTrue(slots.autosave_due(), "the timed one is separate")

    def test_f8_describes_what_is_on(self):
        slots = savestate.StateSlots(self.FakeEmu(), folder=tempfile.gettempdir())
        self.assertEqual(slots.describe_autosave(), "every 5 min, at loading screens, on quit")
        slots.autosave_every_ms = int(7.5 * 60_000)
        slots.autosave_on_quit = False
        self.assertEqual(slots.describe_autosave(), "every 7.5 min, at loading screens")
        slots.autosave_every_ms = 0
        slots.autosave_on_loading = False
        self.assertEqual(slots.describe_autosave(), "")

class ScreenshotLabelTests(unittest.TestCase):
    def test_a_screenshot_is_listed_by_the_time_it_was_taken(self):
        self.assertEqual(L.shot_label("khvcemu_20261004_214135.png"), "Oct 04  21:41:35")
        self.assertEqual(L.shot_label("khvcemu_20260102_030405-2.png"), "Jan 02  03:04:05", "a repeat in the same second")
        self.assertEqual(L.shot_label("khvcemu_20261304_214135.png"), "khvcemu_20261304_214135.png", "not a date")
        self.assertEqual(L.shot_label("holiday.png"), "holiday.png", "any other file keeps its name")


class OptionsTabTests(unittest.TestCase):
    def make_app(self, cfg):
        import tkinter as tk
        old = (L.load_config, L.save_config)
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "mif"), exist_ok=True)
        os.makedirs(os.path.join(d, "mod", "11839"), exist_ok=True)
        L.load_config = lambda: dict(cfg, dump=d)
        L.save_config = lambda c: None
        self.addCleanup(setattr, L, "load_config", old[0])
        self.addCleanup(setattr, L, "save_config", old[1])
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display for Tk")
        root.withdraw()
        self.addCleanup(lambda: root.winfo_exists() and root.destroy())
        return root, L.Launcher(root)

    def test_the_three_autosave_options_and_the_interval_are_saved_and_restored(self):
        root, app = self.make_app({"autosave_minutes": 9, "autosave_on_quit": False})
        self.assertEqual(app.autosave_minutes.get(), "9")
        opts = app.opts()
        self.assertEqual((opts["autosave"], opts["autosave_minutes"], opts["autosave_on_quit"], opts["autosave_on_loading"]),
                         (True, 9.0, False, True))
        app.autosave_minutes.set("20")                         # the box is editable
        app.autosave_on_loading.set(False)
        cmd = L.build_command("dump", app.opts())
        self.assertEqual(cmd[cmd.index("--autosave-every") + 1], "20")
        self.assertIn("--no-autosave-on-quit", cmd)
        self.assertIn("--no-autosave-on-loading", cmd)
        app.restore_defaults(ask=False)
        opts = app.opts()
        self.assertEqual((opts["autosave"], opts["autosave_minutes"], opts["autosave_on_quit"], opts["autosave_on_loading"]),
                         (True, 5.0, True, True))

    def test_an_old_config_with_autosave_off_keeps_all_three_off(self):
        root, app = self.make_app({"autosave": False})
        opts = app.opts()
        self.assertEqual((opts["autosave"], opts["autosave_on_quit"], opts["autosave_on_loading"]), (False, False, False))
        self.assertIn("--no-autosave", L.build_command("dump", opts))

    def test_the_window_size_note_box_is_gone(self):
        root, app = self.make_app({})

        def walk(w):
            yield w
            for c in w.winfo_children():
                yield from walk(c)
        titles = [str(w.cget("text")) for w in walk(app.tab_frames["options"]) if w.winfo_class() == "TLabelframe"]
        self.assertEqual(titles, ["Window", "While playing", "Screenshots (F12)", "Online scores", "Speed-ups (same picture)"])

    def test_the_screenshot_list_shows_the_newest_first_and_previews_the_selected_one(self):
        folder = tempfile.mkdtemp()
        now = time.time()
        for i, name in enumerate(("old.png", "mid.png", "new.png")):
            png(os.path.join(folder, name), shade=50 * (i + 1))
            os.utime(os.path.join(folder, name), (now - 300 + i * 100,) * 2)
        open(os.path.join(folder, "notes.txt"), "w").close()                   # not a picture
        root, app = self.make_app({"screenshots": folder})
        app.refresh_screenshots()
        self.assertEqual(app._shots_names, ["new.png", "mid.png", "old.png"])
        self.assertEqual(app.shots_list.size(), 3)
        self.assertEqual(app.shots_selected_name(), "new.png", "the latest is shown at first")
        self.assertIsNotNone(app._shots_image)
        self.assertLessEqual(app._shots_image.width(), L.SHOT_W)
        self.assertLessEqual(app._shots_image.height(), L.SHOT_H)
        app.shots_list.selection_clear(0, "end")
        app.shots_list.selection_set(2)
        app.show_screenshot()
        self.assertEqual(app.shots_selected_name(), "old.png")
        opened = []
        real = L.open_in_viewer
        L.open_in_viewer = opened.append
        self.addCleanup(setattr, L, "open_in_viewer", real)
        app.open_screenshot()
        app.open_screenshot_folder()
        self.assertEqual(opened, [os.path.join(folder, "old.png"), folder])
        # a new screenshot appears on the next refresh and the choice is kept
        png(os.path.join(folder, "newest.png"))
        app.refresh_screenshots()
        self.assertEqual(app._shots_names[0], "newest.png")
        self.assertEqual(app.shots_selected_name(), "old.png")

    def test_an_empty_or_missing_folder_is_fine(self):
        root, app = self.make_app({"screenshots": os.path.join(tempfile.mkdtemp(), "not made yet")})
        app.refresh_screenshots()
        self.assertEqual(app.shots_list.size(), 0)
        self.assertIsNone(app.shots_selected_name())
        app.open_screenshot()                                        # nothing to open: no error
        app.open_screenshot_folder()
        self.assertIn("doesn't exist yet", app.status.cget("text"))
        broken = tempfile.mkdtemp()
        with open(os.path.join(broken, "bad.png"), "wb") as f:
            f.write(b"not a png")
        app.screenshots.set(broken)
        app.refresh_screenshots()
        self.assertEqual(app._shots_names, ["bad.png"])
        self.assertIn("can't preview", str(app.shots_preview.cget("text")))


if __name__ == "__main__":
    unittest.main()
