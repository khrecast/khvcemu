"""The Wonderland 'lost media' pages drawn with Pillow (what the Android app shows, since it has no pygame)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import lostmedia  # noqa: E402


class PillowPagesTests(unittest.TestCase):
    def test_two_pages_in_the_core_frame_format(self):
        pages = lostmedia.build_screens_pil()
        self.assertEqual(len(pages), 2)
        for page in pages:
            self.assertEqual(page.shape, (220, 176))
            self.assertEqual(str(page.dtype), "uint16")
            self.assertGreater((page != 0xFFFF).sum(), 3000, "the page is not a blank white sheet")
            self.assertGreater((page == 0xFFFF).sum(), 3000, "the page keeps its white background")
        self.assertFalse((pages[0] == pages[1]).all(), "the two pages differ")

    def test_the_continue_button_is_dark_at_the_bottom_left(self):
        for page in lostmedia.build_screens_pil():
            button = page[199:215, 8:60]
            self.assertLess(int((button == 0xFFFF).mean() * 100), 40, "a dark box with white text, not white")

    def test_no_text_runs_off_the_right_edge(self):
        """Drawn without smoothing, text is wider than the font's own advance says: the pages must still wrap inside."""
        for page in lostmedia.build_screens_pil():
            self.assertTrue((page[:, 172:] == 0xFFFF).all(), "something is drawn in the last four columns")

    def test_a_font_measures_text_the_way_it_is_drawn(self):
        from khvcemu import hostgfx
        f = hostgfx.load_font("", 9, False)
        text = "Sora's adventure through Wonderland"
        self.assertGreaterEqual(f.size(text)[0], f.mask(text).shape[1])
        self.assertTrue(f.mask(text)[:, -1].any() or f.mask(text)[:, -2].any(), "the last letter is not cut off")

    def test_every_png_in_the_assets_is_really_a_png(self):
        """Two of them were WebP files named .png: pygame reads either, but the phone's Pillow has no WebP support."""
        signature = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
        found = 0
        for root, _dirs, files in os.walk(lostmedia.ASSETS):
            for name in files:
                if name.lower().endswith(".png"):
                    found += 1
                    with open(os.path.join(root, name), "rb") as f:
                        self.assertEqual(f.read(8), signature, os.path.join(root, name))
        self.assertGreater(found, 10)

    def test_rgb565_conversion(self):
        from PIL import Image
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 255, 255))
        img.putpixel((1, 0), (255, 0, 0))
        out = lostmedia.to_rgb565(img)
        self.assertEqual([int(v) for v in out[0]], [0xFFFF, 0xF800])


if __name__ == "__main__":
    unittest.main()
