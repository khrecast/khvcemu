"""The launcher's Options and Saves tabs: the three kinds of autosave (on the Saves tab) (timed with an editable interval, on quit, at loading
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
                         (True, 20.0, False, False), "Restore default settings is for the Options tab only")

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
        self.assertEqual(titles, ["Window", "While playing", "Speed", "Screenshots (F12)", "Online scores"])
        saves = [str(w.cget("text")) for w in walk(app.tab_frames["saves"]) if w.winfo_class() == "TLabelframe"]
        self.assertEqual(saves, ["Autosave (F8 turns it on and off in game)"], "autosave lives on the Saves tab")

    def test_the_speed_enhancements_window(self):
        from khvcemu import swerve_patch
        root, app = self.make_app({"speed_patches_off": ["matinv"]})
        self.assertEqual(app.speed_summary.cget("text"), "1 of %d off" % len(swerve_patch.NAMES))
        tips = []
        real = app.tooltip
        app.tooltip = lambda widget, text: tips.append(text)
        app.open_speed_window()
        self.assertIsNotNone(app.speed_win)
        checks = []

        def walk(w):
            for c in w.winfo_children():
                if c.winfo_class() == "TCheckbutton":
                    checks.append(str(c.cget("text")))
                walk(c)
        walk(app.speed_win)
        self.assertEqual(checks, [swerve_patch.LABELS[n] for n in swerve_patch.NAMES], "one switch each, in order")
        for n in swerve_patch.NAMES:
            self.assertIn(swerve_patch.HINTS[n], tips, "an info bubble for each")
            self.assertIn("Why turn it off?", swerve_patch.HINTS[n])
        app.speed_vars["span"].set(False)
        self.assertIn("2 of", app.speed_summary.cget("text"))
        cmd = L.build_command("dump", app.opts())
        self.assertEqual(set(cmd[cmd.index("--no-speed-patch") + 1].split(",")), {"span", "matinv"})
        app.open_speed_window()                                   # a second click brings the same window forward
        app.close_speed_window()
        self.assertIsNone(app.speed_win)
        app.tooltip = real
        app.restore_defaults(ask=False)
        self.assertEqual(app.speed_summary.cget("text"), "All on")

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

    def test_the_red_x_deletes_the_selected_screenshot_after_asking(self):
        folder = tempfile.mkdtemp()
        now = time.time()
        for i, name in enumerate(("a.png", "b.png", "c.png")):
            png(os.path.join(folder, name))
            os.utime(os.path.join(folder, name), (now - 300 + i * 100,) * 2)    # c is the newest
        root, app = self.make_app({"screenshots": folder})
        app.refresh_screenshots()
        app.shots_list.selection_clear(0, "end")
        app.shots_list.selection_set(1)                                         # b
        asked = []
        real_trash = L.to_trash
        self.addCleanup(setattr, L, "to_trash", real_trash)
        L.to_trash = lambda p: (os.remove(p), True)[1]                          # never the real Recycle Bin in a test
        app.confirm_delete_screenshot = lambda name: asked.append(name) or False
        app.delete_screenshot()
        self.assertTrue(os.path.exists(os.path.join(folder, "b.png")), "No: nothing happens")
        app.confirm_delete_screenshot = lambda name: asked.append(name) or True
        app.delete_screenshot()
        self.assertFalse(os.path.exists(os.path.join(folder, "b.png")))
        self.assertEqual(app._shots_names, ["c.png", "a.png"])
        self.assertEqual(app.shots_selected_name(), "a.png", "the next one along is selected")
        self.assertEqual(asked, ["b.png", "b.png"])
        # a file another program holds open (Photos does) cannot be deleted: say so plainly, keep it listed
        warned = []
        real_warn = L.messagebox.showwarning
        self.addCleanup(setattr, L.messagebox, "showwarning", real_warn)
        L.messagebox.showwarning = lambda *a, **k: warned.append(a)
        L.to_trash = lambda p: False
        app.delete_screenshot()
        self.assertEqual(len(warned), 1)
        self.assertIn("open in another program", warned[0][1])
        self.assertEqual(app._shots_names, ["c.png", "a.png"], "nothing changes")

    def test_the_delete_question_has_a_box_to_stop_asking(self):
        folder = tempfile.mkdtemp()
        for name in ("a.png", "b.png", "c.png"):
            png(os.path.join(folder, name))
        root, app = self.make_app({"screenshots": folder})
        real_trash = L.to_trash
        self.addCleanup(setattr, L, "to_trash", real_trash)
        L.to_trash = lambda p: (os.remove(p), True)[1]
        self.assertTrue(app.ask_delete.get(), "asks by default")

        def answer(button, untick):
            """Open the real question, tick or untick its box, press Yes or No."""
            def poke():
                dlg = next(w for w in root.winfo_children() if w.winfo_class() == "Toplevel")
                kids = []

                def walk(w):
                    for c in w.winfo_children():
                        kids.append(c)
                        walk(c)
                walk(dlg)
                box = next(c for c in kids if c.winfo_class() == "TCheckbutton")
                self.assertEqual(str(box.cget("text")), "Ask me before deleting a screenshot")
                if untick:
                    box.invoke()
                next(c for c in kids if c.winfo_class() == "TButton" and str(c.cget("text")) == button).invoke()
            root.after(100, poke)
            app.refresh_screenshots()
            app.shots_list.selection_clear(0, "end")
            app.shots_list.selection_set(0)
            before = len(app._shots_names)
            app.delete_screenshot()
            return before - len(app._shots_names)
        self.assertEqual(answer("No", untick=True), 0, "No deletes nothing")
        self.assertTrue(app.ask_delete.get(), "and an unticked box only counts with Yes")
        self.assertEqual(answer("Yes", untick=True), 1)
        self.assertFalse(app.ask_delete.get(), "unticked and Yes: it stops asking")
        self.assertIs(app.opts()["ask_before_deleting_screenshot"], False, "and that is remembered")
        app.refresh_screenshots()
        app.shots_list.selection_clear(0, "end")
        app.shots_list.selection_set(0)
        before = len(app._shots_names)
        app.delete_screenshot()                                  # no question now
        self.assertEqual(before - len(app._shots_names), 1)
        app.restore_defaults(ask=False)
        self.assertTrue(app.ask_delete.get(), "Restore default settings asks again")

    def test_the_rendered_music_can_be_cleared(self):
        data = tempfile.mkdtemp()
        real = L.data_dir_for
        L.data_dir_for = lambda dump: data
        self.addCleanup(setattr, L, "data_dir_for", real)
        cache = os.path.join(data, "audio_cache")
        os.makedirs(cache)
        for name in ("training-abc.npy", "island-def.npy"):
            with open(os.path.join(cache, name), "wb") as f:
                f.write(b"x" * 500_000)
        open(os.path.join(cache, "half.npy.1.2.tmp"), "w").close()
        open(os.path.join(cache, "keep.txt"), "w").close()
        self.assertEqual(L.music_cache_size("dump"), (2, 1_000_000))
        root, app = self.make_app({})
        real_ask = L.messagebox.askyesno
        self.addCleanup(setattr, L.messagebox, "askyesno", real_ask)
        L.messagebox.askyesno = lambda *a, **k: True
        app.open_advanced()
        self.assertIn("2 tunes kept, 1.0 MB", app.cache_status.cget("text"))
        app.clear_music()
        self.assertEqual(sorted(os.listdir(cache)), ["keep.txt"], "only rendered tunes (and half-written ones) go")
        self.assertEqual(app.cache_status.cget("text"), "Nothing kept yet")
        self.assertEqual(str(app.cache_button.cget("state")), "disabled")
        app.close_advanced()

    def test_pictures_of_any_size_fit_the_preview_box(self):
        folder = tempfile.mkdtemp()
        sizes = {"frame.png": (176, 220), "wide.png": (900, 300), "tall.png": (200, 1200), "tiny.png": (30, 20),
                 "window.png": (704, 880)}
        now = time.time()
        for i, (name, (w, h)) in enumerate(sizes.items()):
            png(os.path.join(folder, name), w, h)
            os.utime(os.path.join(folder, name), (now - 100 + i,) * 2)
        root, app = self.make_app({"screenshots": folder})
        app.refresh_screenshots()
        for name, (w, h) in sizes.items():
            app.shots_list.selection_clear(0, "end")
            app.shots_list.selection_set(app._shots_names.index(name))
            app.show_screenshot()
            img = app._shots_image
            self.assertIsNotNone(img, name)
            self.assertLessEqual(img.width(), L.SHOT_W, name)
            self.assertLessEqual(img.height(), L.SHOT_H, name)
            self.assertLessEqual(img.width(), w, f"{name}: never enlarged past its own size")
            if name in ("frame.png", "window.png"):
                self.assertGreaterEqual(img.height(), L.SHOT_H - 12, "a game frame fills the box")

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
