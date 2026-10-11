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

    def test_the_menu_font_alphabet_is_whole_and_copied_to_the_app(self):
        menu = os.path.join(ROOT, "khvcemu", "assets", "menu", "font_atlas.txt")
        raw = os.path.join(ROOT, "android", "app", "src", "main", "res", "raw", "menu_font_atlas.txt")
        with open(menu, "rb") as a, open(raw, "rb") as b:
            self.assertEqual(a.read(), b.read(), "run tools/make_tab_labels.py to refresh res/raw/menu_font_atlas.txt")
        with open(menu, encoding="utf-8") as f:
            lines = f.read().split("\n")
        height = int(lines[0])
        cells = {chr(int(p[0])): (int(p[1]), int(p[2])) for p in (l.split() for l in lines[1:] if l.strip())}
        self.assertTrue(set("ABCXYZabcxyz0189") <= set(cells), "the alphabet lacks letters")
        spans = sorted(cells.values())
        self.assertTrue(all(a[0] + a[1] <= b[0] for a, b in zip(spans, spans[1:])), "two cells overlap")
        with open(os.path.join(ROOT, "khvcemu", "assets", "menu", "font_atlas.png"), "rb") as f:
            png = f.read()
        import struct
        width, h = struct.unpack(">II", png[16:24])
        self.assertEqual(h, height)
        self.assertTrue(all(x >= 0 and x + w <= width for x, w in cells.values()), "a cell lies outside the picture")

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

    def test_the_apps_recordings_reach_the_core_only_when_the_files_exist(self):
        import json
        import tempfile
        py = os.path.join(ROOT, "android", "app", "src", "main", "python")
        sys.path.insert(0, py)
        try:
            import recast_app
            from khvcemu import audio
            with tempfile.TemporaryDirectory() as tmp:
                have = os.path.join(tmp, "t.flac")
                open(have, "wb").close()
                text = json.dumps({"Training.mid": {"path": have, "gain": 2.5},
                                   "island.mid": {"path": os.path.join(tmp, "gone.flac")},
                                   "bad.mid": 3})
                self.assertEqual(recast_app._music_files(text), {"training.mid": {"path": have, "gain": 2.5}})
            self.assertEqual(recast_app._music_files(""), {})
            self.assertEqual(recast_app._music_files("not json"), {})
            old = audio.FILE_DECODER
            try:
                recast_app._install_decoder()
                self.assertIs(audio.FILE_DECODER, recast_app._decode_with_android)
            finally:
                audio.FILE_DECODER = old
        finally:
            sys.path.remove(py)

    def test_match_gain_aims_at_the_built_in_tunes_level(self):
        import numpy as np
        from unittest import mock
        py = os.path.join(ROOT, "android", "app", "src", "main", "python")
        sys.path.insert(0, py)
        try:
            import recast_app
            import tempfile
            ours = (np.sin(np.arange(22050) / 10.0) * 6000).astype(np.int16)     # RMS about 4240, above the 3000 floor
            quiet = (ours // 4).astype(np.int16)
            with tempfile.TemporaryDirectory() as tmp:
                pcm = os.path.join(tmp, "q.pcm")
                quiet.tofile(pcm)
                with mock.patch.object(recast_app, "render_tune", return_value=ours.tobytes()):
                    gain = recast_app.match_gain(".", "training.mid", "", pcm)
            self.assertAlmostEqual(gain, 4.0, delta=0.15)                       # four times quieter: about 4 (the most allowed)
        finally:
            sys.path.remove(py)

    def test_sharp_text_hands_the_app_the_picture_and_its_strings_together(self):
        import json
        from types import SimpleNamespace
        import numpy as np
        py = os.path.join(ROOT, "android", "app", "src", "main", "python")
        sys.path.insert(0, py)
        try:
            import recast_app
            base = np.zeros((220, 176), np.uint16)
            clean = base.copy()
            clean[0, 0] = 7
            item = {"text": "Hi", "font_id": 0x8000, "x": 10, "y": 20, "box": (10, 20, 30, 32), "fg": 0xFFFF, "size": (18, 12),
                    "bg": np.full((12, 20), 0xF800, np.uint16)}
            emu = SimpleNamespace(last_frame=base, overlay=(clean, [item]))
            old = recast_app._game
            recast_app._game = SimpleNamespace(emu=emu, lm_pages=[], items_json="[]", sharp=True)
            try:
                got = np.frombuffer(recast_app.frame_bytes(), "<u2")
                self.assertEqual(int(got[0]), 7, "the picture without its low-res text, not the plain frame")
                items = json.loads(recast_app.frame_text())
                self.assertEqual(items, [{"t": "Hi", "f": 0x8000, "x": 10, "y": 20, "w": 18, "h": 12, "c": 0xFFFF,
                                          "g": 0xF800, "b": [10, 20, 30, 32]}])
                recast_app._game.sharp = False                         # only the softkey names wanted: the plain picture, the strings
                self.assertEqual(int(np.frombuffer(recast_app.frame_bytes(), "<u2")[0]), 0)
                self.assertEqual(json.loads(recast_app.frame_text())[0]["t"], "Hi")
                recast_app._game.sharp = True
                emu.overlay = None                                     # nothing drawn: the plain frame, no strings
                got = np.frombuffer(recast_app.frame_bytes(), "<u2")
                self.assertEqual(int(got[0]), 0)
                self.assertEqual(recast_app.frame_text(), "[]")
                recast_app._game.lm_pages = [clean]                    # a lost-media page: that page, no strings
                emu.overlay = (base, [item])
                self.assertEqual(int(np.frombuffer(recast_app.frame_bytes(), "<u2")[0]), 7)
                self.assertEqual(recast_app.frame_text(), "[]")
            finally:
                recast_app._game = old
        finally:
            sys.path.remove(py)

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
