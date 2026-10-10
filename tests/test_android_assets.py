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


if __name__ == "__main__":
    unittest.main()
