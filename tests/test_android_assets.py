"""Files the Android app keeps a copy of must stay identical to the originals in khvcemu/assets."""
import os
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


if __name__ == "__main__":
    unittest.main()
