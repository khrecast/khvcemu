"""The launcher notices save states written by the running game (no game files needed)."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import launcher as L  # noqa: E402


class Sandbox:
    """A fake game folder, and a home folder of its own so the real ~/.khvcemu is never touched."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        home = os.path.join(self.tmp.name, "home")
        os.makedirs(home)
        os.environ["HOME"] = os.environ["USERPROFILE"] = home
        self.dump = os.path.join(self.tmp.name, "game")
        os.makedirs(os.path.join(self.dump, "mif"))
        os.makedirs(os.path.join(self.dump, "mod"))
        return self

    def state(self, slot, data=b"x"):
        p = L.slot_file(self.dump, slot)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()


class SignatureTests(unittest.TestCase):
    def test_the_signature_changes_when_the_game_saves_and_not_otherwise(self):
        with Sandbox() as sb:
            sig = lambda: L.Launcher.states_signature(None, sb.dump)      # noqa: E731
            empty = sig()
            self.assertEqual(sig(), empty, "nothing happened")
            p = sb.state("1", b"one")
            after_save = sig()
            self.assertNotEqual(after_save, empty, "a new state")
            self.assertEqual(sig(), after_save)
            with open(p, "wb") as f:
                f.write(b"one, saved again with more in it")
            self.assertNotEqual(sig(), after_save, "the same slot saved over")
            png = os.path.splitext(p)[0] + ".png"
            before_png = sig()
            with open(png, "wb") as f:
                f.write(b"thumb")
            self.assertNotEqual(sig(), before_png, "the preview arriving after the state")
            os.remove(p)
            self.assertNotEqual(sig(), before_png, "a state deleted")

    def test_no_game_folder_means_no_signature(self):
        self.assertEqual(L.Launcher.states_signature(None, ""), ())


class LiveListTests(unittest.TestCase):
    def pump(self, root, seconds):
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    def test_the_list_and_the_continue_card_follow_the_game(self):
        import tkinter as tk
        with Sandbox() as sb:
            old = (L.load_config, L.save_config, L.STATES_POLL_MS)
            L.load_config = lambda: {"dump": sb.dump}
            L.save_config = lambda c: None
            L.STATES_POLL_MS = 40
            try:
                try:
                    root = tk.Tk()
                except tk.TclError:
                    self.skipTest("no display for Tk")
                root.withdraw()
                try:
                    app = L.Launcher(root)
                    self.pump(root, 0.2)
                    self.assertIn("empty", app.slots.get(0))
                    self.assertEqual(app.hero_title.cget("text"), "Start a new game")
                    sb.state("2")                                  # the player presses F5 in the game
                    self.pump(root, 0.5)
                    self.assertNotIn("empty", app.slots.get(1), "Slot 2 shows up without a restart")
                    self.assertIn("Slot 2", app.hero_title.cget("text") + app.continue_label.cget("text"))
                    self.assertEqual(app.selected_slot(), "2", "the newest state is selected")
                    time.sleep(0.05)
                    sb.state("3")                                  # saved again: the highlight follows
                    self.pump(root, 0.5)
                    self.assertNotIn("empty", app.slots.get(2))
                    self.assertEqual(app.selected_slot(), "3", "the highlight follows the newest save")
                    app.slots.selection_clear(0, "end")
                    app.slots.selection_set(0)                     # the player clicks Slot 1 meanwhile
                    self.assertTrue(app.slots.bind("<<ListboxSelect>>"), "a click on the list is noticed")
                    app.slot_chosen()                              # (what that click runs; a hidden window gets no events)
                    self.pump(root, 0.1)
                    time.sleep(0.05)
                    sb.state("6")
                    self.pump(root, 0.5)
                    self.assertNotIn("empty", app.slots.get(5))
                    self.assertEqual(app.selected_slot(), "1", "their own choice is kept")

                    L.STATES_POLL_MS = 600_000                     # from the next tick on, only a click or focus can notice
                    self.pump(root, 0.2)
                    sb.state("4")
                    self.pump(root, 0.3)
                    self.assertIn("empty", app.slots.get(3), "the timer alone no longer sees it")
                    root.event_generate("<Button-1>", x=5, y=5)
                    self.pump(root, 0.1)
                    self.assertNotIn("empty", app.slots.get(3), "clicking the launcher refreshes at once")
                    sb.state("5")
                    root.event_generate("<FocusIn>")
                    self.pump(root, 0.1)
                    self.assertNotIn("empty", app.slots.get(4), "bringing it forward refreshes at once")
                finally:
                    root.destroy()
            finally:
                L.load_config, L.save_config, L.STATES_POLL_MS = old


if __name__ == "__main__":
    unittest.main()
