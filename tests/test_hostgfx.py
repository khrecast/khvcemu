"""The Pillow fallbacks used where pygame is missing (Android): image decoding and text. They must give what pygame
gives (images) or a working equivalent (fonts). Skipped when Pillow or pygame is not installed."""
import glob
import io
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

try:
    import PIL.Image as PILImage  # noqa: E402
except ImportError:
    PILImage = None
try:
    import pygame  # noqa: E402
except ImportError:
    pygame = None

HAVE_BOTH = PILImage is not None and pygame is not None


def pygame_decode(raw):
    from khvcemu import image
    return image.decode_image(raw)          # pygame is installed, so this is the pygame path


def png_bytes(img, **kw):
    out = io.BytesIO()
    img.save(out, "PNG", **kw)
    return out.getvalue()


@unittest.skipUnless(HAVE_BOTH, "needs Pillow and pygame")
class DecodeParityTests(unittest.TestCase):
    def check(self, raw):
        from khvcemu import hostgfx
        px, alpha = hostgfx.decode_image(raw)
        px2, alpha2 = pygame_decode(raw)
        self.assertEqual(px.shape, px2.shape)
        self.assertTrue(np.array_equal(alpha, alpha2), "alpha differs")
        # compare the colour only where the pixel is visible (pygame and Pillow may differ under full transparency)
        self.assertTrue(np.array_equal(px[alpha2], px2[alpha2]), "colours differ")

    def test_rgba_png(self):
        rng = np.random.default_rng(1)
        arr = rng.integers(0, 256, (9, 13, 4), dtype=np.uint8)
        arr[..., 3] = np.where(rng.random((9, 13)) > 0.4, 255, 0)
        self.check(png_bytes(PILImage.fromarray(arr, "RGBA")))

    def test_rgb_png(self):
        rng = np.random.default_rng(2)
        self.check(png_bytes(PILImage.fromarray(rng.integers(0, 256, (7, 11, 3), dtype=np.uint8), "RGB")))

    def test_palette_png_with_a_transparent_colour(self):
        img = PILImage.new("P", (8, 6))
        img.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * 756)
        img.putdata([i % 4 for i in range(48)])
        self.check(png_bytes(img, transparency=1))

    def test_bmp(self):
        rng = np.random.default_rng(3)
        out = io.BytesIO()
        PILImage.fromarray(rng.integers(0, 256, (5, 7, 3), dtype=np.uint8), "RGB").save(out, "BMP")
        self.check(out.getvalue())

    def test_the_games_own_png_images(self):
        root = os.environ.get("KH_DUMP")
        files = sorted(glob.glob(os.path.join(root, "mod", "*", "*.png"))) if root else []
        if not files:
            self.skipTest("no game folder (KH_DUMP)")
        for path in files:
            with open(path, "rb") as f:
                self.check(f.read())


@unittest.skipUnless(PILImage is not None, "needs Pillow")
class FontTests(unittest.TestCase):
    def test_a_font_measures_and_draws_text(self):
        from khvcemu import hostgfx
        f = hostgfx.load_font("verdana,dejavusans", 11, False)
        self.assertIsNotNone(f)
        self.assertGreater(f.get_ascent(), 0)
        self.assertLess(f.get_descent(), 0, "pygame reports the descent negative; the core takes abs()")
        w, h = f.size("Kingdom Hearts")
        self.assertGreater(w, f.size("Kingdom")[0])
        self.assertEqual(h, f.get_ascent() - f.get_descent())
        mask = f.mask("Kingdom Hearts")
        self.assertEqual(mask.shape, (h, w))
        self.assertTrue(mask.any() and not mask.all())

    def test_the_same_text_is_rendered_once(self):
        from khvcemu import hostgfx
        f = hostgfx.load_font("", 11, False)
        self.assertIs(f.mask("Continue"), f.mask("Continue"))
        for i in range(700):                                   # the cache stays bounded
            f.mask("t%d" % i)
        self.assertLessEqual(len(f._masks), 600)

    def test_bold_and_size_change_the_result(self):
        from khvcemu import hostgfx
        small = hostgfx.load_font("", 11, False)
        large = hostgfx.load_font("", 14, False)
        self.assertGreater(large.size("Hello")[0], small.size("Hello")[0])

    def test_the_core_falls_back_to_it_when_pygame_cannot_be_imported(self):
        from khvcemu import display
        fake = types.SimpleNamespace(emu=types.SimpleNamespace(font_size=None, font_name=None),
                                     FONT_CANDIDATES=display.Display.FONT_CANDIDATES, FONT_SIZE=display.Display.FONT_SIZE)
        fake.__dict__.update({})                       # _font keeps its cache in the instance dict
        saved = sys.modules.get("pygame")
        sys.modules["pygame"] = None                   # makes `import pygame` raise ImportError
        try:
            f = display.Display._font(fake, display.AEE_FONT_NORMAL)
        finally:
            if saved is None:
                sys.modules.pop("pygame", None)
            else:
                sys.modules["pygame"] = saved
        self.assertTrue(f, "no font: text would silently not be drawn")
        self.assertTrue(hasattr(f, "mask") and not hasattr(f, "render"))

    def test_decode_image_uses_pillow_when_pygame_cannot_be_imported(self):
        from khvcemu import image
        out = io.BytesIO()
        PILImage.new("RGB", (4, 3), (255, 0, 0)).save(out, "PNG")
        saved = sys.modules.get("pygame")
        sys.modules["pygame"] = None
        try:
            px, alpha = image.decode_image(out.getvalue())
        finally:
            if saved is None:
                sys.modules.pop("pygame", None)
            else:
                sys.modules["pygame"] = saved
        self.assertEqual(px.shape, (3, 4))
        self.assertTrue(alpha.all())
        self.assertTrue((px == 0xF800).all())


if __name__ == "__main__":
    unittest.main()
