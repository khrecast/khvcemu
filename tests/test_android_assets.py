"""Files the Android app keeps a copy of must stay identical to the originals in khvcemu/assets."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AndroidAssetCopyTests(unittest.TestCase):
    def test_the_home_screen_logo_is_the_project_logo(self):
        original = os.path.join(ROOT, "khvcemu", "assets", "recast_logo_lowres_hardpixels.png")
        copy = os.path.join(ROOT, "android", "app", "src", "main", "res", "drawable-nodpi", "recast_logo.png")
        with open(original, "rb") as a, open(copy, "rb") as b:
            self.assertEqual(a.read(), b.read(), "re-copy the logo into android/app/src/main/res/drawable-nodpi/recast_logo.png")

    def test_the_app_menu_labels_match_the_ones_made_for_the_launcher_font(self):
        menu = os.path.join(ROOT, "khvcemu", "assets", "menu")
        res = os.path.join(ROOT, "android", "app", "src", "main", "res", "drawable-nodpi")
        names = sorted(n for n in os.listdir(menu) if n.endswith(".png"))
        self.assertTrue(names, "no menu labels found")
        for name in names:
            with open(os.path.join(menu, name), "rb") as a, open(os.path.join(res, "menu_" + name), "rb") as b:
                self.assertEqual(a.read(), b.read(), name + ": run tools/make_tab_labels.py to refresh the Android copies")

    def test_the_apps_sound_tables_match_music_settings(self):
        import re
        from khvcemu import music_settings as ms
        path = os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "khrecast", "recast", "SoundSettings.java")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        sliders = re.findall(r'\{"(\w+)", "([^"]+)", "([\d.]+)", "([\d.]+)"\}', source)
        self.assertEqual([(k, label, float(lo), float(hi)) for k, label, lo, hi in sliders],
                         [(s.key, s.label, s.low, s.high) for s in ms.VOLUMES + ms.CHARACTER],
                         "SoundSettings.SLIDERS differs from music_settings")
        self.assertIn("VOLUME_COUNT = %d;" % len(ms.VOLUMES), source)
        presets = re.findall(r'\{"([A-Za-z ]+)", "([a-z_=0-9.,]*)"\}', source)
        self.assertEqual([name for name, _ in presets], list(ms.PRESETS))
        for name, text in presets:
            self.assertEqual(ms.parse(text, strict=False), ms.changed(ms.PRESETS[name]), name)

    def test_the_apps_tune_list_matches_music_preview(self):
        import re
        from khvcemu import music_preview
        path = os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "khrecast", "recast", "SoundSettings.java")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        start = source.index("TUNES = {")
        block = source[start:source.index("};", start)]
        tunes = re.findall(r'\{"([a-z_]+\.mid)", "([^"]+)"\}', block)
        self.assertEqual(tunes, list(music_preview.TUNES))

    def test_the_sound_screen_can_make_a_tune_from_the_game_files(self):
        dump = os.environ.get("KH_DUMP", "")
        from khvcemu import music_preview
        if not dump or not music_preview.tune_path(dump, "keyblade.mid"):
            self.skipTest("the game files are not here")
        sys.path.insert(0, os.path.join(ROOT, "android", "app", "src", "main", "python"))
        try:
            import recast_app
            pcm = recast_app.render_tune(dump, "keyblade.mid", "bass=1.6")
            self.assertGreater(len(pcm), 1000)
            self.assertEqual(len(pcm) % 2, 0)                      # 16-bit samples
            with self.assertRaises(FileNotFoundError):
                recast_app.render_tune(dump, "no_such_tune.mid", "")
        finally:
            sys.path.remove(os.path.join(ROOT, "android", "app", "src", "main", "python"))

    def test_the_apps_leaderboard_address_is_the_launchers(self):
        from khvcemu.launcher import LEADERBOARD_URL
        path = os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "khrecast", "recast", "Settings.java")
        with open(path, encoding="utf-8") as f:
            self.assertIn('LEADERBOARD_URL = "%s";' % LEADERBOARD_URL, f.read())

    def test_the_connection_check_says_so_when_the_server_cannot_be_reached(self):
        import importlib.util
        path = os.path.join(ROOT, "android", "app", "src", "main", "python", "recast_app.py")
        spec = importlib.util.spec_from_file_location("recast_app_for_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        answer = module.check_online("http://127.0.0.1:9")            # nothing listens on the discard port
        self.assertTrue(answer.startswith("Could not reach http://127.0.0.1:9"), answer)


if __name__ == "__main__":
    unittest.main()
