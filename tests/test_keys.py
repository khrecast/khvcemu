"""Changing the game's keys: the shared rules (keys.py), the pygame key map and the launcher's Controls tab."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import keys  # noqa: E402
from khvcemu import launcher as L  # noqa: E402


class KeyRuleTests(unittest.TestCase):
    def test_defaults_are_the_keys_the_game_always_had(self):
        self.assertEqual(keys.DEFAULT_KEYS, {"UP": "w", "DOWN": "s", "LEFT": "a", "RIGHT": "d", "SELECT": "space",
                                             "STAR": "f", "0": "z", "SOFT1": "q", "SOFT2": "e", "CLR": "backspace"})
        self.assertEqual(set(keys.ALSO), set(keys.DEFAULT_KEYS))
        self.assertEqual(keys.parse_key_options([]), {})

    def test_parse_accepts_changes_and_ignores_the_default_given_back(self):
        self.assertEqual(keys.parse_key_options(["UP=i", "star=G", "DOWN=s"]), {"UP": "i", "STAR": "g"})
        self.assertEqual(keys.parse_key_options(["UP=i", "DOWN=w"]), {"UP": "i", "DOWN": "w"}, "keys can be swapped round")

    def test_parse_refuses_what_cannot_work(self):
        for bad, why in ((["UP=1"], "digit"), (["UP=up"], "name"), (["UP=return"], "enter"), (["UP=space"], "taken by Action"), (["FOO=a"], "action"),
                         (["UP=s"], "taken by Move down"), (["UP=a", "LEFT=a"], "same key twice"), (["UP"], "no key"),
                         (["UP="], "empty")):
            with self.subTest(why=why), self.assertRaises(ValueError):
                keys.parse_key_options(bad)

    def test_tk_keys_become_names_and_the_rest_are_refused(self):
        for tk_name, want in (("w", "w"), ("W", "w"), ("semicolon", ";"), ("slash", "/"), ("Tab", "tab"), ("grave", "`"),
                              ("backslash", chr(92)), ("BackSpace", "backspace"), ("1", None), ("F5", None), ("Up", None), ("space", "space"),
                              ("Return", None), ("Escape", None), ("Shift_L", None), ("bracketleft", None), ("bracketright", None)):
            self.assertEqual(keys.key_from_tk(tk_name), want, tk_name)

    def test_display_and_owner(self):
        self.assertEqual((keys.display_key("w"), keys.display_key(";"), keys.display_key("tab"), keys.display_key("space")),
                         ("W", ";", "Tab", "Space"))
        self.assertEqual(keys.key_owner({}, "w"), "UP")
        self.assertEqual(keys.key_owner({"UP": "i"}, "w"), None, "W is free once Up moved to I")
        self.assertEqual(keys.key_owner({"UP": "i"}, "i"), "UP")
        self.assertEqual(keys.key_owner({"UP": "i"}, "i", except_action="UP"), None)

    def test_every_allowed_key_has_a_pygame_name(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        pygame.display.init()
        for k in sorted(keys.ALLOWED_KEYS):
            self.assertIsInstance(pygame.key.key_code(k), int, k)


class KeyMapTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        pygame.display.init()
        self.pg = pygame

    def test_the_default_map_is_unchanged(self):
        from khvcemu.frontend import build_keymap
        m = build_keymap(self.pg)
        self.assertEqual((m[self.pg.K_w], m[self.pg.K_f], m[self.pg.K_z], m[self.pg.K_q], m[self.pg.K_e]),
                         ("UP", "STAR", "0", "SOFT1", "SOFT2"))
        self.assertEqual(build_keymap(self.pg, {}), m)
        self.assertEqual(build_keymap(self.pg, {"UP": "w"}), m, "the default given back changes nothing")

    def test_a_changed_key_moves_only_that_action(self):
        from khvcemu.frontend import build_keymap
        pg = self.pg
        m = build_keymap(pg, {"UP": "i", "STAR": "g", "SOFT2": ";"})
        self.assertEqual((m[pg.K_i], m[pg.K_g], m[pg.K_SEMICOLON]), ("UP", "STAR", "SOFT2"))
        for old in (pg.K_w, pg.K_f, pg.K_e):
            self.assertNotIn(old, m, "the old letter no longer does it")
        self.assertEqual((m[pg.K_UP], m[pg.K_LEFTBRACKET], m[pg.K_KP_MULTIPLY], m[pg.K_F2]),
                         ("UP", "STAR", "STAR", "SOFT2"), "arrows, [, number pad * and F2 still work")
        self.assertEqual((m[pg.K_s], m[pg.K_a], m[pg.K_d], m[pg.K_z], m[pg.K_q]), ("DOWN", "LEFT", "RIGHT", "0", "SOFT1"))

    def test_the_action_key_can_move_off_space_and_enter_and_5_stay(self):
        from khvcemu.frontend import build_keymap
        pg = self.pg
        m = build_keymap(pg, {"SELECT": "x"})
        self.assertEqual((m[pg.K_x], m[pg.K_RETURN], m[pg.K_KP_ENTER], m[pg.K_5]), ("SELECT", "SELECT", "SELECT", "5"))
        self.assertNotIn(pg.K_SPACE, m)
        m = build_keymap(pg, keys.parse_key_options(["SELECT=x", "STAR=space"]))
        self.assertEqual((m[pg.K_SPACE], m[pg.K_x]), ("STAR", "SELECT"), "Space can go to another action once it is free")

    def test_backspace_can_be_moved_and_the_hash_keys_do_nothing(self):
        from khvcemu.frontend import build_keymap
        pg = self.pg
        m = build_keymap(pg)
        self.assertEqual(m[pg.K_BACKSPACE], "CLR")
        self.assertNotIn(pg.K_RIGHTBRACKET, m, "] was the # key, which the game ignores")
        self.assertNotIn(pg.K_KP_DIVIDE, m)
        self.assertNotIn("POUND", set(m.values()))
        m = build_keymap(pg, {"CLR": "x"})
        self.assertEqual(m[pg.K_x], "CLR")
        self.assertNotIn(pg.K_BACKSPACE, m)
        for custom in ({"STAR": "backspace", "CLR": "x"}, {"CLR": "x", "STAR": "backspace"}):    # either order
            m = build_keymap(pg, keys.parse_key_options([f"{a}={k}" for a, k in custom.items()]))
            self.assertEqual((m[pg.K_BACKSPACE], m[pg.K_x]), ("STAR", "CLR"), "Backspace given to magic once it is free")
            self.assertNotIn(pg.K_f, m)

    def test_keys_can_be_swapped(self):
        from khvcemu.frontend import build_keymap
        pg = self.pg
        m = build_keymap(pg, keys.parse_key_options(["UP=s", "DOWN=w"]))
        self.assertEqual((m[pg.K_s], m[pg.K_w]), ("UP", "DOWN"))

    def test_the_command_line_checks_the_option(self):
        import subprocess
        dump = tempfile.mkdtemp()
        os.makedirs(os.path.join(dump, "mif"))
        r = subprocess.run([sys.executable, "-m", "khvcemu", dump, "--key", "UP=s"], capture_output=True,
                           text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("given to both", r.stderr)


class ControlsTabTests(unittest.TestCase):
    def make_app(self, cfg):
        import tkinter as tk
        old = (L.load_config, L.save_config)
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "mif"), exist_ok=True)
        os.makedirs(os.path.join(d, "mod", "11839"), exist_ok=True)
        saved = []
        L.load_config = lambda: dict(cfg, dump=d)
        L.save_config = lambda c: saved.append(dict(c))
        self.addCleanup(setattr, L, "load_config", old[0])
        self.addCleanup(setattr, L, "save_config", old[1])
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display for Tk")
        root.withdraw()

        def close():
            try:
                root.destroy()
            except tk.TclError:
                pass                                            # the test closed it already
        self.addCleanup(close)
        return root, L.Launcher(root), saved

    def test_the_tab_shows_the_current_keys_and_changes_them(self):
        root, app, saved = self.make_app({})
        self.assertEqual([str(app.key_buttons[a].cget("text")) for a in keys.DEFAULT_KEYS],
                         ["W", "S", "A", "D", "Space", "F", "Z", "Q", "E", "Backspace"])
        self.assertNotIn("--key", L.build_command("dump", app.opts()))
        self.assertTrue(app.apply_key("UP", "i"))
        self.assertEqual(str(app.key_buttons["UP"].cget("text")), "I *", "a changed key is marked")
        cmd = L.build_command("dump", app.opts())
        self.assertEqual(cmd[cmd.index("--key") + 1], "UP=i")
        self.assertEqual(saved[-1]["custom_keys"], {"UP": "i"}, "and remembered")
        self.assertTrue(app.apply_key("DOWN", "w"), "W is free now")
        self.assertEqual(app.custom_keys, {"UP": "i", "DOWN": "w"})
        self.assertFalse(app.apply_key("UP", "w"), "W is Move down's now")
        self.assertIn("already move down", app.status.cget("text"))
        self.assertTrue(app.apply_key("DOWN", "s"), "back to its own default: no longer a change")
        self.assertEqual(app.custom_keys, {"UP": "i"})

    def test_keys_that_cannot_be_used_are_refused_with_a_reason(self):
        root, app, _ = self.make_app({})
        for keysym in ("1", "F5", "Up", "Return", "bracketleft", "Shift_L", "KP_Enter"):
            self.assertFalse(app.apply_key("STAR", keysym), keysym)
            self.assertIn("cannot be used", app.status.cget("text"))
        self.assertEqual(app.custom_keys, {})

    def test_clicking_a_key_then_pressing_one_captures_it_and_escape_cancels(self):
        root, app, _ = self.make_app({})

        class Event:
            def __init__(self, keysym):
                self.keysym = keysym
        app.start_key_capture("SOFT1")
        self.assertEqual(str(app.key_buttons["SOFT1"].cget("text")), "Press a key...")
        self.assertEqual(app.on_key_capture(Event("Escape")), "break")
        self.assertIsNone(app.capturing)
        self.assertEqual(str(app.key_buttons["SOFT1"].cget("text")), "Q")
        app.start_key_capture("SOFT1")
        app.on_key_capture(Event("1"))                          # refused: still waiting for a usable key
        self.assertEqual(app.capturing, "SOFT1")
        app.on_key_capture(Event("p"))
        self.assertIsNone(app.capturing)
        self.assertEqual(app.custom_keys, {"SOFT1": "p"})

    def test_leaving_the_tab_ends_a_capture(self):
        root, app, _ = self.make_app({})
        app.start_key_capture("UP")
        self.assertEqual(app.capturing, "UP")
        app.tabs.select(app.tab_frames["options"])
        root.update()
        self.assertIsNone(app.capturing, "typing in the Options tab must not rebind a game key")
        self.assertEqual(str(app.key_buttons["UP"].cget("text")), "W")
        self.assertIsNone(app._capture_bind)

    def test_reset_and_a_damaged_setting(self):
        root, app, _ = self.make_app({"custom_keys": {"UP": "i", "STAR": "g"}})
        self.assertEqual(app.custom_keys, {"UP": "i", "STAR": "g"}, "read back from the settings")
        app.reset_keys()
        self.assertEqual(app.custom_keys, {})
        root.destroy()                                          # one Tk at a time: images belong to the first one
        root2, app2, _ = self.make_app({"custom_keys": {"UP": "s", "NOPE": "x", "DOWN": "1"}})
        self.assertEqual(app2.custom_keys, {}, "a bad setting is dropped, not crashed on")
        root2.destroy()
        root3, app3, _ = self.make_app({"custom_keys": "garbage"})
        self.assertEqual(app3.custom_keys, {})

    def test_restore_default_settings_leaves_the_keys_alone(self):
        root, app, _ = self.make_app({})
        app.apply_key("UP", "i")
        app.restore_defaults(ask=False)
        self.assertEqual(app.custom_keys, {"UP": "i"})


if __name__ == "__main__":
    unittest.main()
