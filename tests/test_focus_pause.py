"""Losing window focus holds the game clock still.

    KH_DUMP=/path/to/dump python -m unittest tests.test_focus_pause -v

Runs the real window under SDL's dummy video driver, posts the focus events pygame would
deliver, and compares the emulated game clock with real time.
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DUMP = os.environ.get("KH_DUMP")


@unittest.skipUnless(DUMP and os.path.isdir(os.path.join(DUMP, "mif")), "set KH_DUMP to the game folder")
class FocusPauseTests(unittest.TestCase):
    def setUp(self):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        self.pg = pygame
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script, **window_options):
        """Start the game in the real window; `script(emu, post, marks)` runs in a thread once
        the game is running and must end by closing the window. Returns what it recorded."""
        from khvcemu.frontend import run_window
        from khvcemu.runtime import Emulator
        pg = self.pg
        emu = Emulator(DUMP, self.tmp.name, realtime=True, audio=False, log=lambda s: None)
        emu.start()
        marks, errors = {}, []

        def post(ev_type, **kw):
            pg.event.post(pg.event.Event(ev_type, **kw))

        def driver():
            try:
                t0 = time.time()
                while not (pg.display.get_init() and pg.display.get_surface() and emu.frames > 30):
                    time.sleep(0.1)
                    assert time.time() - t0 < 60, "the game never got going"
                script(emu, post, marks)
            except BaseException as e:                     # reported by the test, not lost in a thread
                errors.append(repr(e))
                post(pg.QUIT)
                post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        threading.Thread(target=driver, daemon=True).start()
        window_options.setdefault("shots_dir", self.tmp.name)
        window_options.setdefault("autosave", False)
        run_window(emu, scale=1, **window_options)
        self.assertEqual(errors, [])
        return marks

    def test_time_away_is_not_game_time(self):
        pg = self.pg

        def script(emu, post, m):
            m["before"] = emu.clock_ms()
            post(pg.WINDOWFOCUSLOST)
            time.sleep(0.4)
            m["frames_a"] = emu.frames
            time.sleep(2.0)                                # alt-tabbed away
            m["frames_b"] = emu.frames
            post(pg.WINDOWFOCUSGAINED)
            time.sleep(0.5)
            m["after"] = emu.clock_ms()
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script)
        self.assertLessEqual(m["frames_b"] - m["frames_a"], 1, "the game did not run while in the background")
        gained = m["after"] - m["before"]
        self.assertLess(gained, 1700, f"2.4 s were spent away, but the game clock moved {gained} ms")
        self.assertGreater(gained, 300, "and it does carry on afterwards")

    def test_with_the_option_off_the_game_keeps_running_in_the_background(self):
        """Options tab: "Pause when the window loses focus" unticked (--no-focus-pause)."""
        pg = self.pg

        def script(emu, post, m):
            m["before"] = emu.clock_ms()
            post(pg.WINDOWFOCUSLOST)
            time.sleep(0.4)
            m["frames_a"] = emu.frames
            time.sleep(1.5)
            m["frames_b"] = emu.frames
            post(pg.WINDOWFOCUSGAINED)
            m["after"] = emu.clock_ms()
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script, pause_on_focus_loss=False)
        self.assertGreater(m["frames_b"] - m["frames_a"], 3, "the game went on running")
        self.assertGreater(m["after"] - m["before"], 1500, "and its clock kept time")

    def test_a_prompt_opened_while_away_counts_the_time_once(self):
        pg = self.pg

        def script(emu, post, m):
            m["before"] = emu.clock_ms()
            post(pg.WINDOWFOCUSLOST)
            time.sleep(1.0)
            post(pg.QUIT)                                  # the quit prompt opens over the paused game
            time.sleep(1.0)
            post(pg.KEYDOWN, key=pg.K_ESCAPE, mod=0, unicode="", scancode=0)   # No: carry on
            time.sleep(0.5)
            m["after"] = emu.clock_ms()
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script)
        gained = m["after"] - m["before"]
        self.assertGreaterEqual(gained, 0, "the clock never goes backwards")
        self.assertLess(gained, 1300, f"2.5 s were spent paused, but the game clock moved {gained} ms")

    def test_without_a_focus_event_time_runs_normally(self):
        pg = self.pg

        def script(emu, post, m):
            m["before"] = emu.clock_ms()
            time.sleep(1.5)
            m["after"] = emu.clock_ms()
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script)
        self.assertGreater(m["after"] - m["before"], 1300, "the control: the clock normally tracks real time")

    def test_a_window_that_opens_unfocused_holds_the_game_until_it_is_focused(self):
        """No focus-lost event ever comes for a window that opens behind another one, so the
        window looks at startup. (The dummy driver is never judged, so the check is forced.)"""
        import khvcemu.frontend as fe
        pg = self.pg
        real = fe.window_unfocused
        fe.window_unfocused = lambda _pg: True
        wait = fe.STARTUP_FOCUS_CHECK_S
        fe.STARTUP_FOCUS_CHECK_S = 8.0                     # after the harness sees the game running
        self.addCleanup(setattr, fe, "window_unfocused", real)
        self.addCleanup(setattr, fe, "STARTUP_FOCUS_CHECK_S", wait)

        def script(emu, post, m):
            t0 = time.time()
            while emu.frames > 0 and time.time() - t0 < 12 and not getattr(emu, "_held_probe", False):
                time.sleep(0.1)
                if time.time() - t0 > 9:
                    break                                  # the startup look has happened
            m["frames_a"] = emu.frames
            m["before"] = emu.clock_ms()
            time.sleep(1.5)
            m["frames_b"] = emu.frames
            post(pg.WINDOWFOCUSGAINED)                     # the player clicks it
            time.sleep(0.2)
            m["resumed"] = emu.clock_ms()
            time.sleep(0.6)
            m["after"] = emu.clock_ms()
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script)
        self.assertLessEqual(m["frames_b"] - m["frames_a"], 1, "held still while unfocused")
        moved = m["resumed"] - m["before"]
        self.assertLess(moved, 300, f"1.7 s passed unfocused, but the clock moved {moved} ms")
        self.assertGreater(m["after"] - m["resumed"], 400, "and it carries on once focused")

    def test_dark_screen_opens_a_backdrop_that_never_pauses_or_steals_the_game(self):
        """--dark-screen: a black window behind the game. Clicking it must not pause the game, and
        it is closed again when the game ends."""
        import khvcemu.frontend as fe
        pg = self.pg
        made = []
        real = fe.open_backdrop

        def spy(pygame, emu=None):
            back, main = real(pygame, emu)
            made.append(back)
            return back, main
        fe.open_backdrop = spy
        self.addCleanup(setattr, fe, "open_backdrop", real)

        def script(emu, post, m):
            m["frames_a"] = emu.frames
            post(pg.WINDOWFOCUSGAINED, window=made[0])     # the backdrop was clicked
            post(pg.WINDOWFOCUSLOST, window=made[0])       # ...and let go of again
            time.sleep(1.0)
            m["frames_b"] = emu.frames
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script, dark_screen=True)
        self.assertIsNotNone(made[0], "the backdrop was made")
        self.assertGreater(m["frames_b"] - m["frames_a"], 3, "the game kept running")

    def test_the_x_button_still_asks_to_quit_with_the_dark_screen_on(self):
        """With two windows SDL sends the game window's X as WINDOWCLOSE, not QUIT."""
        import khvcemu.frontend as fe
        pg = self.pg
        made = []
        real = fe.open_backdrop

        def spy(pygame, emu=None):
            back, main = real(pygame, emu)
            made.append((back, main))
            return back, main
        fe.open_backdrop = spy
        self.addCleanup(setattr, fe, "open_backdrop", real)
        drawn = []
        real_prompt = fe.draw_quit_prompt
        fe.draw_quit_prompt = lambda p, screen, fc: drawn.append(1)
        self.addCleanup(setattr, fe, "draw_quit_prompt", real_prompt)

        def script(emu, post, m):
            post(pg.WINDOWCLOSE, window=made[0][1])        # the X on the game window
            time.sleep(0.6)
            m["prompt"] = len(drawn)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)   # Enter: quit

        m = self.run_script(script, dark_screen=True)
        self.assertGreater(m["prompt"], 0, "the X opened the quit prompt")

    def test_with_the_question_turned_off_quitting_is_immediate(self):
        pg = self.pg
        drawn = []
        import khvcemu.frontend as fe
        real = fe.draw_quit_prompt
        fe.draw_quit_prompt = lambda p, screen, fc: drawn.append(1)
        self.addCleanup(setattr, fe, "draw_quit_prompt", real)

        def script(emu, post, m):
            m["t"] = time.time()
            post(pg.QUIT)                                   # no Enter after it: it must end by itself

        t0 = time.time()
        self.run_script(script, ask_before_quit=False)
        self.assertEqual(drawn, [], "no question was asked")
        self.assertLess(time.time() - t0, 40)

    def test_d_in_the_prompt_quits_and_remembers_not_to_ask_again(self):
        pg = self.pg
        saved = []

        def script(emu, post, m):
            post(pg.QUIT)
            time.sleep(0.5)
            post(pg.KEYDOWN, key=pg.K_d, mod=0, unicode="d", scancode=0)

        self.run_script(script, remember_no_quit_prompt=lambda: saved.append(True))
        self.assertEqual(saved, [True])

    def test_without_the_option_there_is_no_backdrop(self):
        import khvcemu.frontend as fe
        made = []
        real = fe.open_backdrop
        fe.open_backdrop = lambda *a, **k: made.append(1) or real(*a, **k)
        self.addCleanup(setattr, fe, "open_backdrop", real)
        pg = self.pg

        def script(emu, post, m):
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)
        self.run_script(script)
        self.assertEqual(made, [])

    def test_a_paused_game_says_so_and_the_label_goes_when_it_resumes(self):
        import khvcemu.frontend as fe
        pg = self.pg
        drawn = []
        real = fe.draw_pause_label
        fe.draw_pause_label = lambda p, screen, fc: drawn.append(time.monotonic())
        self.addCleanup(setattr, fe, "draw_pause_label", real)

        def script(emu, post, m):
            m["n0"] = len(drawn)
            post(pg.WINDOWFOCUSLOST)
            time.sleep(0.6)
            m["n1"] = len(drawn)
            post(pg.WINDOWFOCUSGAINED)
            time.sleep(0.6)
            m["n2"] = len(drawn)
            time.sleep(0.6)
            m["n3"] = len(drawn)
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script)
        self.assertEqual(m["n0"], 0, "not shown while playing")
        self.assertGreater(m["n1"], 0, "shown while the window is in the background")
        self.assertEqual(m["n3"], m["n2"], "gone once it is focused again")

    def test_the_pause_label_draws_at_any_window_size(self):
        import khvcemu.frontend as fe
        pg = self.pg
        pg.font.init()
        for size in ((176, 220), (352, 440), (700, 880), (90, 120)):
            screen = pg.Surface(size)
            screen.fill((200, 40, 40))
            fe.draw_pause_label(pg, screen, {})
            self.assertNotEqual(screen.get_at((size[0] // 2, size[1] // 2))[:3], (200, 40, 40), size)
            self.assertEqual(screen.get_at((0, 0))[:3][0] < 200, True, "the picture behind is dimmed")

    def test_a_new_area_is_autosaved_a_few_seconds_after_its_loading_screen(self):
        """The game draws "Loading....." between areas; 3 s after the last of those frames the window
        autosaves (once a key has been pressed)."""
        from khvcemu import savestate
        pg = self.pg
        real = savestate.AREA_SAVE_MIN_GAP_MS
        savestate.AREA_SAVE_MIN_GAP_MS = 0
        self.addCleanup(setattr, savestate, "AREA_SAVE_MIN_GAP_MS", real)
        states = os.path.join(self.tmp.name, "states", "auto1.khs")
        import khvcemu.frontend as fe
        icons, toasts = [], []
        real_icon, real_toast = fe.draw_save_icon, fe.draw_toast
        fe.draw_save_icon = lambda p, screen: icons.append(1)
        fe.draw_toast = lambda p, screen, text, fc: toasts.append(text)
        self.addCleanup(setattr, fe, "draw_save_icon", real_icon)
        self.addCleanup(setattr, fe, "draw_toast", real_toast)

        def script(emu, post, m):
            post(pg.KEYDOWN, key=pg.K_UP, mod=0, unicode="", scancode=0)      # a game key: something was played
            post(pg.KEYUP, key=pg.K_UP, mod=0, unicode="", scancode=0)
            time.sleep(0.3)
            m["before"] = os.path.exists(states)
            emu.last_loading_ms = emu.clock_ms()                 # "Loading" has just been drawn
            time.sleep(2.0)
            m["early"] = os.path.exists(states)                  # 2 s: too soon
            time.sleep(2.5)
            m["after"] = os.path.exists(states)
            m["cleared"] = emu.last_loading_ms is None
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script, autosave=True)
        self.assertFalse(m["before"])
        self.assertFalse(m["early"], "not while the Loading screen has only just gone")
        self.assertTrue(m["after"], "about 3 seconds after it")
        self.assertTrue(m["cleared"])
        self.assertGreater(len(icons), 0, "a floppy disc in the corner says it autosaved")
        self.assertFalse([t for t in toasts if "utosaved" in t], "and no text message over the game")

    def autosave_script(self, wait, quit_at_end=True):
        pg = self.pg

        def script(emu, post, m):
            post(pg.KEYDOWN, key=pg.K_UP, mod=0, unicode="", scancode=0)      # a game key: something was played
            post(pg.KEYUP, key=pg.K_UP, mod=0, unicode="", scancode=0)
            time.sleep(wait)
            m["before_quit"] = os.path.exists(os.path.join(self.tmp.name, "states", "auto1.khs"))
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)
        return script

    def test_the_timed_autosave_uses_the_interval_from_the_launcher(self):
        """--autosave-every: 0.03 minutes is under two seconds of play; 0 turns the timed autosave off."""
        m = self.run_script(self.autosave_script(3.0), autosave=True, autosave_minutes=0.03,
                            autosave_on_quit=False, autosave_on_loading=False)
        self.assertTrue(m["before_quit"], "saved by the timer alone")
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        m = self.run_script(self.autosave_script(3.0), autosave=True, autosave_minutes=0,
                            autosave_on_quit=False, autosave_on_loading=False)
        self.assertFalse(m["before_quit"], "0 minutes: no timed autosave")

    def test_autosave_on_quit_has_its_own_switch(self):
        states = lambda: os.path.exists(os.path.join(self.tmp.name, "states", "auto1.khs"))  # noqa: E731
        self.run_script(self.autosave_script(0.5), autosave=True, autosave_minutes=0, autosave_on_loading=False)
        self.assertTrue(states(), "closing the window mid-game writes one more autosave")
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.run_script(self.autosave_script(0.5), autosave=True, autosave_minutes=0, autosave_on_loading=False,
                        autosave_on_quit=False)
        self.assertFalse(states(), "unticked: it is not written")

    def test_the_loading_screen_autosave_has_its_own_switch(self):
        from khvcemu import savestate
        pg = self.pg
        real = savestate.AREA_SAVE_MIN_GAP_MS
        savestate.AREA_SAVE_MIN_GAP_MS = 0
        self.addCleanup(setattr, savestate, "AREA_SAVE_MIN_GAP_MS", real)

        def script(emu, post, m):
            post(pg.KEYDOWN, key=pg.K_UP, mod=0, unicode="", scancode=0)
            post(pg.KEYUP, key=pg.K_UP, mod=0, unicode="", scancode=0)
            time.sleep(0.3)
            emu.last_loading_ms = emu.clock_ms()
            time.sleep(4.5)
            m["saved"] = os.path.exists(os.path.join(self.tmp.name, "states", "auto1.khs"))
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script, autosave=True, autosave_minutes=0, autosave_on_quit=False, autosave_on_loading=False)
        self.assertFalse(m["saved"], "unticked: a Loading screen does not save")

    def test_the_floppy_disc_is_small_and_stays_in_the_bottom_left_corner(self):
        import khvcemu.frontend as fe
        pg = self.pg
        for size in ((176, 220), (352, 440), (700, 880)):
            screen = pg.Surface(size)
            screen.fill((0, 0, 0))
            fe.draw_save_icon(pg, screen)
            lit = [(x, y) for x in range(size[0]) for y in range(size[1]) if screen.get_at((x, y))[:3] != (0, 0, 0)]
            self.assertTrue(lit, size)
            xs, ys = [p[0] for p in lit], [p[1] for p in lit]
            self.assertLess(max(xs), size[0] // 6, "in the left corner")
            self.assertGreater(min(ys), size[1] * 0.8, "at the bottom, away from the dialogue")

    def test_f12_saves_a_screenshot_and_says_where(self):
        import khvcemu.frontend as fe
        pg = self.pg
        said = []
        real = fe.draw_toast
        fe.draw_toast = lambda p, screen, text, fc: said.append(text)
        self.addCleanup(setattr, fe, "draw_toast", real)

        def script(emu, post, m):
            post(pg.KEYDOWN, key=pg.K_F12, mod=0, unicode="", scancode=0)
            time.sleep(0.8)
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        folder = os.path.join(self.tmp.name, "my shots", "deeper")           # not there yet: made on demand
        self.run_script(script, shots_dir=folder)
        pngs = [f for f in os.listdir(folder) if f.startswith("khvcemu_") and f.endswith(".png")]
        self.assertEqual(len(pngs), 1, "the screenshot was written to the chosen folder")
        self.assertTrue(any(t.startswith("Saved: ") and pngs[0] in t for t in said), said)

    def test_the_screenshot_message_names_the_file_and_its_folder_only(self):
        from khvcemu.frontend import screenshot_label
        self.assertEqual(screenshot_label(os.path.join("C:\\", "Users", "x", "Games", "khvcemu_1.png")),
                         "Saved: .../Games/khvcemu_1.png")
        self.assertLess(len(screenshot_label(os.path.join("a" * 80, "b" * 80, "khvcemu_20260101_000000.png"))), 130)

    def test_f10_flashes_a_speaker_icon_that_goes_away_again(self):
        """Muting is easy to miss in a game that is mostly quiet: F10 shows a speaker for a moment."""
        import numpy as np
        pg = self.pg
        from khvcemu import frontend

        def script(emu, post, m):
            def corner():
                surf = pg.display.get_surface()
                w, h = surf.get_size()
                return pg.surfarray.array3d(surf)[int(w * 0.8):, : int(h * 0.2)].astype(int)
            time.sleep(0.5)
            m["before"] = corner()
            post(pg.KEYDOWN, key=pg.K_F10, mod=0, unicode="", scancode=0)
            time.sleep(0.4)
            m["muted"] = corner()
            time.sleep(frontend.MUTE_ICON_SECS + 0.8)
            m["after"] = corner()
            post(pg.KEYDOWN, key=pg.K_F10, mod=0, unicode="", scancode=0)
            time.sleep(0.4)
            m["unmuted"] = corner()
            m["audio"] = emu.audio.master_volume
            post(pg.QUIT)
            time.sleep(0.2)
            post(pg.KEYDOWN, key=pg.K_RETURN, mod=0, unicode="", scancode=0)

        m = self.run_script(script)
        diff = lambda a, b: int((np.abs(a - b).sum(axis=2) > 60).sum())             # noqa: E731
        self.assertGreater(diff(m["muted"], m["before"]), 300, "the icon appears when muted")
        self.assertLess(diff(m["after"], m["before"]), 60, "and goes away again by itself")
        self.assertGreater(diff(m["unmuted"], m["before"]), 300, "and appears again when sound is back")
        self.assertGreater(diff(m["unmuted"], m["muted"]), 100, "looking different")
        self.assertEqual(m["audio"], 1.0)

    def test_dummy_and_offscreen_windows_are_not_judged(self):
        from khvcemu.frontend import window_unfocused
        self.pg.display.init()
        self.assertFalse(window_unfocused(self.pg), "the dummy driver is never judged")


if __name__ == "__main__":
    unittest.main()
