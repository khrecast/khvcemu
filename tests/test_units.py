"""Unit tests that don't need the game files:  python -m unittest discover -s tests"""

import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu import m3g, midi_synth, pmd  # noqa: E402
from khvcemu.cpu import TRAP_BASE, Cpu  # noqa: E402
from khvcemu.display import fix_text  # noqa: E402
from khvcemu.files import Vfs, canon  # noqa: E402
from khvcemu.heap import Heap  # noqa: E402
from khvcemu.helpers import ArgIter, c_format  # noqa: E402
from khvcemu.resfile import (ResourceFile, mif_applet_classes,  # noqa: E402
                           mif_extension_classes)

CODE = 0x00020000


class HiresTextTests(unittest.TestCase):
    """Display keeps drawn strings so the frontend can redraw them sharply."""

    def setUp(self):
        from khvcemu.display import Display
        self.d = object.__new__(Display)        # bookkeeping only; no emulator needed
        self.bg = np.full((20, 40), 0x1234, np.uint16)

    def draw(self, frame, x, w, fg=0xFFFF):
        mask = np.zeros((8, w), bool)
        mask[2:6, 1:w - 1] = True
        box = (x, 4, x + w, 12)
        reg = frame[4:12, x:x + w]
        self.d._record_text("t", 0x8000, x, 4, box, mask, reg.copy(), fg, (w, 8))
        reg[mask] = fg

    def test_clean_frame_restores_background(self):
        f = self.bg.copy()
        self.draw(f, 5, 10)
        clean, items = self.d.build_overlay(f)
        self.assertEqual(len(items), 1)
        self.assertTrue((clean == self.bg).all())

    def test_overpainted_text_is_dropped(self):
        f = self.bg.copy()
        self.draw(f, 5, 10)
        f[:] = 0                                # game cleared the screen
        self.assertIsNone(self.d.build_overlay(f))
        self.assertEqual(self.d.text_items, [])

    def test_label_redrawn_in_place_replaces_old(self):
        f = self.bg.copy()
        self.draw(f, 5, 10)
        self.draw(f, 5, 14)                     # "Loading." -> "Loading.."
        clean, items = self.d.build_overlay(f)
        self.assertEqual(len(items), 1)
        self.assertTrue((clean == self.bg).all())

    def test_next_screen_in_the_text_colour_is_not_mistaken_for_the_text(self):
        # white "Loading" on a dark screen, then a white page: every glyph pixel
        # is still "white", but the string is gone. Keeping it pasted the old
        # dark background back in glyph shape, a low-res ghost of the text.
        f = self.bg.copy()
        self.draw(f, 5, 10, fg=0xFFFF)
        self.assertIsNotNone(self.d.build_overlay(f))
        f[:] = 0xFFFF                           # the next screen: solid white
        self.assertIsNone(self.d.build_overlay(f))
        self.assertEqual(self.d.text_items, [])

    def test_a_selection_bar_over_old_text_is_not_mistaken_for_the_text(self):
        # the shop: a description line ("restores your") was drawn black on light grey,
        # then the item list came back with a black selection bar across where most of
        # its glyphs were. The glyph pixels are now black (97% "match") and the
        # untouched part of the box still matches the old background (54%), so a test
        # that checked the two separately kept it, drawing the line smooth over the bar.
        bg = np.full((30, 40), 0xEF7D, np.uint16)
        box = (5, 4, 15, 18)                          # 10 x 14
        mask = np.zeros((14, 10), bool)
        mask[7:13, 1:9] = True                        # glyphs sit in the lower half
        reg = bg[4:18, 5:15]
        self.d._record_text("restores your", 0x8000, 5, 4, box, mask, reg.copy(), 0x0000, (10, 14))
        reg[mask] = 0x0000
        f = bg.copy()
        f[4 + 5:4 + 14, 5:15] = 0x0000                # the bar: black from local row 5 down
        glyph_black = (f[4:18, 5:15][mask] == 0x0000).mean()
        around = ~mask
        around_same = (f[4:18, 5:15][around] == bg[4:18, 5:15][around]).mean()
        self.assertGreaterEqual(glyph_black, 0.9)     # each half alone would pass...
        self.assertGreaterEqual(around_same, 0.5)     # ...which is what let it through
        self.assertIsNone(self.d.build_overlay(f))
        self.assertEqual(self.d.text_items, [])

    def test_same_for_dark_text_before_a_dark_screen(self):
        f = np.full((20, 40), 0xFFFF, np.uint16)    # a white page
        self.draw(f, 5, 10, fg=0x0000)              # black text on it
        f[:] = 0x0000                               # then a black scene
        self.assertIsNone(self.d.build_overlay(f))

    def test_text_whose_surroundings_are_untouched_survives_a_change_elsewhere(self):
        f = self.bg.copy()
        self.draw(f, 5, 10)
        f[14:, :] = 0x0F0F                      # the game redraws the bottom of the screen
        clean, items = self.d.build_overlay(f)
        self.assertEqual(len(items), 1)

    def test_newer_text_over_older_text_still_unwinds_both(self):
        f = self.bg.copy()
        self.draw(f, 5, 10, fg=0xF800)          # older label
        self.draw(f, 9, 10, fg=0x07E0)          # newer label overlapping its box
        clean, items = self.d.build_overlay(f)
        self.assertEqual([it["fg"] for it in items], [0xF800, 0x07E0])
        self.assertTrue((clean == self.bg).all(), "no low-res text left behind")


class PictureFilterTests(unittest.TestCase):
    """How the 176x220 picture is enlarged to the window."""

    @classmethod
    def setUpClass(cls):
        import pygame
        cls.pg = pygame
        rng = np.random.default_rng(1)
        rgb = rng.integers(0, 256, (176, 220, 3), dtype=np.uint8)
        rgb[40:80, 50:90] = (255, 0, 0)                       # a solid block with hard edges
        cls.src = pygame.surfarray.make_surface(rgb)
        cls.rgb = rgb

    def scale(self, filt, size):
        from khvcemu.frontend import scale_frame
        return scale_frame(self.pg, self.src, *size, filt)

    def arr(self, s):
        return self.pg.surfarray.array3d(s)

    def test_every_filter_fills_the_requested_size(self):
        from khvcemu.frontend import FILTERS
        for filt in FILTERS:
            for size in ((176, 220), (352, 440), (528, 660), (500, 625), (150, 190)):
                with self.subTest(filt=filt, size=size):
                    self.assertEqual(self.scale(filt, size).get_size(), size)

    def test_nearest_is_exact_blocks(self):
        out = self.arr(self.scale("nearest", (528, 660)))
        self.assertTrue((out == np.repeat(np.repeat(self.rgb, 3, 0), 3, 1)).all())

    def test_sharp_at_a_whole_multiple_is_identical_to_nearest(self):
        self.assertTrue((self.arr(self.scale("sharp", (528, 660))) ==
                         self.arr(self.scale("nearest", (528, 660)))).all())

    def test_sharp_keeps_block_interiors_exact_at_odd_sizes(self):
        out = self.arr(self.scale("sharp", (500, 625)))       # 2.84x: blocks 2x, then a soft step
        # the red block (x 40-80, y 50-90) lands at x 114-227, y 142-256: deep inside it
        # nothing may be blurred, while its edges may be
        self.assertTrue((out[125:215, 155:245] == (255, 0, 0)).all())

    def test_smooth_blends_edges(self):
        out = self.arr(self.scale("smooth", (528, 660)))
        self.assertGreater(len(np.unique(out.reshape(-1, 3), axis=0)),
                           len(np.unique(self.rgb.reshape(-1, 3), axis=0)), "new in-between colours")

    def test_scale2x_at_double_size_is_plain_scale2x(self):
        out = self.arr(self.scale("scale2x", (352, 440)))
        self.assertTrue((out == self.arr(self.pg.transform.scale2x(self.src))).all())

    def test_unknown_name_falls_back_to_crisp_pixels(self):
        self.assertTrue((self.arr(self.scale("bogus", (352, 440))) ==
                         self.arr(self.scale("nearest", (352, 440)))).all())

    def test_launcher_and_window_offer_the_same_filters(self):
        from khvcemu.frontend import FILTER_NAMES, FILTERS
        from khvcemu.launcher import PICTURE_FILTERS, build_command
        self.assertEqual(tuple(PICTURE_FILTERS), FILTERS)
        self.assertEqual(PICTURE_FILTERS, FILTER_NAMES)
        self.assertIn("--filter", build_command("dump", {"filter": "sharp"}))
        self.assertNotIn("--filter", build_command("dump", {"filter": "nearest"}),
                         "the default isn't spelled out")


class AutoWindowSizeTests(unittest.TestCase):
    """"Auto" window size: the largest that fits, but no bigger than 2x (the game was made for
    a tiny phone screen and looks best small)."""

    class FakeDisplay:
        def __init__(self, w, h):
            self.size = (w, h)

        def get_desktop_sizes(self):
            return [self.size]

    class FakePygame:
        def __init__(self, w, h):
            self.display = AutoWindowSizeTests.FakeDisplay(w, h)

    def scale(self, w, h):
        from khvcemu.frontend import auto_scale
        return auto_scale(self.FakePygame(w, h), 176, 220)

    def test_a_big_desktop_stops_at_two(self):
        self.assertEqual(self.scale(3840, 2160), 2)
        self.assertEqual(self.scale(2560, 1440), 2)
        self.assertEqual(self.scale(1920, 1080), 2)

    def test_a_small_desktop_still_gets_what_fits(self):
        self.assertEqual(self.scale(1366, 768), 2)     # 768 - 140 = 628: 2 x 220 = 440 fits
        self.assertEqual(self.scale(1024, 600), 2)
        self.assertEqual(self.scale(640, 480), 1)       # 480 - 140 = 340: only 1 x 220 fits

    def test_the_cap_is_two(self):
        from khvcemu.frontend import AUTO_SCALE_MAX
        self.assertEqual(AUTO_SCALE_MAX, 2)


class MuteIconTests(unittest.TestCase):
    """The speaker that flashes in the corner when F10 turns sound off or on."""

    @classmethod
    def setUpClass(cls):
        import pygame
        cls.pg = pygame

    def corner(self, muted, size=(176 * 3, 220 * 3)):
        from khvcemu.frontend import draw_mute_icon
        screen = self.pg.Surface(size)
        screen.fill((40, 90, 60))
        draw_mute_icon(self.pg, screen, muted)
        return self.pg.surfarray.array3d(screen)

    def test_it_draws_in_the_top_right_corner_only(self):
        a = self.corner(True)
        plain = np.zeros_like(a)
        plain[:] = (40, 90, 60)
        changed = np.argwhere((a != plain).any(axis=2))
        self.assertGreater(len(changed), 200, "something is drawn")
        self.assertGreater(changed[:, 0].min(), a.shape[0] * 0.8, "right edge")
        self.assertLess(changed[:, 1].max(), a.shape[1] * 0.25, "top edge")

    def test_muted_and_unmuted_look_different(self):
        on, off = self.corner(False), self.corner(True)
        self.assertFalse(np.array_equal(on, off))
        red = lambda a: int(((a[..., 0] > 200) & (a[..., 1] < 100) & (a[..., 2] < 100)).sum())   # noqa: E731
        self.assertGreater(red(off), 20, "the cross is red")
        self.assertEqual(red(on), 0, "no red when the sound is on")

    def test_it_fits_a_tiny_window_too(self):
        a = self.corner(True, (176, 220))
        self.assertTrue((a != np.array((40, 90, 60))).any())


class DisclaimerTests(unittest.TestCase):
    def test_launcher_and_web_page_carry_the_same_disclaimer(self):
        import os
        from khvcemu.launcher import DISCLAIMER
        page = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "index.html")
        html = " ".join(open(page, encoding="utf-8").read().split())
        self.assertIn(DISCLAIMER, html)
        for name in ("Disney", "Square Enix", "Superscape", "Verizon"):
            self.assertIn(name, DISCLAIMER)


class ControlsTests(unittest.TestCase):
    def test_the_web_page_lists_the_launchers_controls(self):
        """Every action and key on the launcher's Controls tab is in the website's Controls table."""
        import html
        import os
        import re
        from khvcemu.launcher import CONTROLS
        page = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "index.html")
        with open(page, encoding="utf-8") as f:
            text = f.read()
        start = text.index("<summary>Controls</summary>")
        table = text[start:text.index("</table>", start)]
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<td>(.*?)</td>", table, re.S)]
        rows = list(zip(cells[0::2], cells[1::2]))           # (keys, what it does)
        for act, keys, emu_act, emu_keys in CONTROLS:
            for action, k in ((act, keys), (emu_act, emu_keys)):
                with self.subTest(action=action):
                    match = [r for r in rows if r[1].startswith(action)]
                    self.assertEqual(len(match), 1, f"{action!r} is on the page once")
                    self.assertEqual(match[0][0], k, f"with the launcher's keys for {action!r}")


class ClosedLauncherTests(unittest.TestCase):
    """The launcher reads the game's log through a pipe; closing the launcher must not kill the game."""

    CHILD = """
import sys, time
sys.path.insert(0, {root!r})
from khvcemu.paths import protect_output
{protect}
time.sleep(1.0)
print('[state] Saved to slot 1', file=sys.stderr, flush=True)
print('and again', file=sys.stderr, flush=True)
open({marker!r}, 'w').write('survived')
"""

    def run_child(self, protected: bool) -> int:
        import subprocess
        import tempfile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as d:
            marker = os.path.join(d, "alive.txt")
            code = self.CHILD.format(root=root, marker=marker, protect="protect_output()" if protected else "")
            p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
            p.stdout.close()                     # the launcher window is closed: nobody reads the output
            rc = p.wait(timeout=60)
            self.assertEqual(os.path.exists(marker), protected)
            return rc

    def test_the_game_survives_a_closed_launcher(self):
        self.assertEqual(self.run_child(protected=True), 0)

    def test_without_the_protection_it_really_did_crash(self):
        self.assertNotEqual(self.run_child(protected=False), 0)



class BundledToolsTests(unittest.TestCase):
    def test_bin_folder_next_to_the_package_goes_first_on_path(self):
        import os, tempfile
        from khvcemu import paths
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "khvcemu")); os.makedirs(os.path.join(d, "bin"))
            real_file, real_path = paths.__file__, os.environ["PATH"]
            self.addCleanup(os.environ.__setitem__, "PATH", real_path)
            self.addCleanup(setattr, paths, "__file__", real_file)
            paths.__file__ = os.path.join(d, "khvcemu", "paths.py")
            paths.use_bundled_tools()
            self.assertTrue(os.environ["PATH"].startswith(os.path.join(d, "bin") + os.pathsep))
            os.rmdir(os.path.join(d, "bin"))
            before = os.environ["PATH"]
            paths.use_bundled_tools()
            self.assertEqual(os.environ["PATH"], before, "no bin folder: PATH is left alone")


class LauncherHeroTests(unittest.TestCase):
    def test_newest_state_is_the_most_recently_written_slot(self):
        import os, tempfile, time
        from khvcemu import launcher
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "mif")); os.makedirs(os.path.join(d, "mod"))
            states = os.path.join(d, "data", "states")
            os.makedirs(states)
            real = launcher.data_dir_for
            launcher.data_dir_for = lambda dump, _s=os.path.join(d, "data"): _s
            self.addCleanup(setattr, launcher, "data_dir_for", real)
            self.assertIsNone(launcher.newest_state(d))
            now = time.time()
            for name, age in (("slot1", 500), ("slot4", 100), ("auto1", 900), ("slot2", 300)):
                p = os.path.join(states, name + ".khs")
                open(p, "wb").close()
                os.utime(p, (now - age, now - age))
            self.assertEqual(launcher.newest_state(d)[0], "4")          # slot 4 is the freshest
            self.assertIsNone(launcher.newest_state(os.path.join(d, "mif")), "not a game folder")


def arm(*words):
    return b"".join(struct.pack("<I", w) for w in words)


class CpuTests(unittest.TestCase):
    def test_call_and_nested_trap(self):
        cpu = Cpu(log=lambda s: None)
        # g(): mov r0,#100 ; bx lr
        cpu.write(CODE + 0x100, arm(0xE3A00064, 0xE12FFF1E))
        trap = cpu.trap("host", lambda c: cpu.call(CODE + 0x100) + c.arg(0))
        # f(): push {lr}; mov r0,#5; ldr r3,[pc,#8]; blx r3; add r0,r0,#1; pop {pc}; .word trap
        cpu.write(CODE, arm(0xE52DE004, 0xE3A00005, 0xE59F3008, 0xE12FFF33, 0xE2800001,
                            0xE49DF004, trap))
        self.assertEqual(cpu.call(CODE), 106)

    def test_stack_arguments(self):
        cpu = Cpu(log=lambda s: None)
        seen = []
        trap = cpu.trap("six", lambda c: seen.append(c.args(6)) or 0)
        # tail-call into the trap, keeping r0-r3 and the stacked args
        cpu.write(CODE, arm(0xE59FC000, 0xE12FFF1C, trap))
        cpu.call(CODE, 1, 2, 3, 4, 5, 6)
        self.assertEqual(seen[0], [1, 2, 3, 4, 5, 6])

    def test_fault_is_reported(self):
        cpu = Cpu(log=lambda s: None)
        cpu.write(CODE, arm(0xE3A00000, 0xE5900000, 0xE12FFF1E))  # ldr r0,[#0]
        with self.assertRaises(Exception):
            cpu.call(CODE)

    def test_exit_pad_is_trap_base(self):
        self.assertEqual(Cpu(log=lambda s: None).exit_addr, TRAP_BASE)


class HeapTests(unittest.TestCase):
    def test_alloc_free_coalesce_and_zeroing(self):
        cpu = Cpu(log=lambda s: None)
        h = Heap(cpu, base=0x10000000, size=0x10000)
        a, b, c = h.malloc(100), h.malloc(100), h.malloc(100)
        self.assertTrue(a < b < c)
        cpu.write(b, b"\xff" * 100)
        h.free(b)
        b2 = h.malloc(100)
        self.assertEqual(b2, b)
        self.assertEqual(cpu.read(b2, 100), b"\0" * 100)
        for p in (a, b2, c):
            h.free(p)
        self.assertEqual(h.free_bytes(), 0x10000)
        self.assertEqual(len(h.free_starts), 1)

    def test_realloc_keeps_data(self):
        cpu = Cpu(log=lambda s: None)
        h = Heap(cpu, base=0x10000000, size=0x10000)
        p = h.malloc(8)
        cpu.write(p, b"ABCDEFGH")
        q = h.realloc(p, 64)
        self.assertEqual(cpu.read(q, 8), b"ABCDEFGH")


class FormatTests(unittest.TestCase):
    def test_c_format(self):
        cpu = Cpu(log=lambda s: None)
        s, t = cpu.hle_cstr("island"), cpu.hle_cstr("ab")
        out = c_format("%s %d/%d %04x %-3s|%%", ArgIter(cpu, [s, 3, 0xFFFFFFFF, 0xBEEF, t], 0), cpu)
        self.assertEqual(out, "island 3/-1 beef ab |%")

    def test_fix_text(self):
        self.assertEqual(fix_text("I\x92m"), "I’m")


def make_resfile(entries, ranges):
    """Build a BREW resource file (.bar/.mif layout)."""
    dir_off = 32
    dir_bytes = b"".join(struct.pack("<4H", *r) for r in ranges)
    tab_off = dir_off + len(dir_bytes)
    data_off = tab_off + 4 * (len(entries) + 1)
    offs, cur = [], data_off
    for e in entries:
        offs.append(cur)
        cur += len(e)
    offs.append(cur)
    head = b"\x11\x00\x01\x00\x01\x00" + struct.pack("<H", len(ranges))
    head += struct.pack("<6I", dir_off, len(dir_bytes), tab_off, len(entries), data_off, cur - data_off)
    return head + dir_bytes + b"".join(struct.pack("<I", o) for o in offs) + b"".join(entries)


class ResFileTests(unittest.TestCase):
    def test_ranges_and_strings(self):
        s1 = b"\xff\xfe" + "Hi".encode("utf-16-le")
        s2 = b"\xff\xfe" + "Yo".encode("utf-16-le")
        rf = ResourceFile.parse(make_resfile([s1, s2], [(1, 100, 1, 0)]))
        self.assertEqual(rf.find(1, 100), s1)
        self.assertEqual(rf.find(1, 101), s2)
        self.assertIsNone(rf.find(1, 102))

    def test_mif_classes(self):
        applet = struct.pack("<5I", 0x01026191, 0, 0x3E8, 0, 0x100000)
        mif = make_resfile([b"name", applet], [(1, 1000, 0, 0), (0x5000, 0, 1, 0)])
        self.assertEqual(mif_applet_classes(mif), [0x01026191])
        ext = make_resfile([struct.pack("<2I", 0x0102BBFC, 0)], [(0x5000, 0, 0, 0)])
        self.assertEqual(mif_extension_classes(ext), [0x0102BBFC])


class M3gTests(unittest.TestCase):
    def build(self, text: bytes, ident=m3g.SWERVE_IDENT):
        raw = b"\x00" * 16 + struct.pack("<I", len(text)) + text
        return m3g.write_sections([(0, b"header"), (1, raw)], ident)

    def test_same_length_patch_roundtrip(self):
        f = self.build(b"23500:summary wonderland\r\n23500:STOP")
        out, n = m3g.replace_text(f, b"summary wonderland", b"summary agrabah   ")
        self.assertEqual(n, 1)
        secs = m3g.read_sections(out)
        self.assertIn(b"summary agrabah   \r\n", secs[1][1])
        self.assertTrue(out.startswith(m3g.SWERVE_IDENT))
        # section checksum is Adler-32 over the section
        comp, total = out[12], struct.unpack_from("<I", out, 13)[0]
        sec = out[12:12 + total]
        self.assertEqual(struct.unpack("<I", sec[-4:])[0], zlib.adler32(sec[:-4]))

    def test_length_change_rejected(self):
        with self.assertRaises(ValueError):
            m3g.replace_text(self.build(b"x"), b"ab", b"abc")


class AudioTests(unittest.TestCase):
    def test_pmd_to_qcp(self):
        pkt = bytes([4]) + bytes(34)
        block = bytes(7) + pkt * 3
        trac = b"\x00\xff\xc3\x7d" + b"\xff\xf1" + struct.pack(">H", len(block)) + block + b"\xff\xdf\x00"
        hdr = b"\x02\x02\x01" + b"vers" + struct.pack(">H", 4) + b"0520"
        body = struct.pack(">H", len(hdr)) + hdr + b"trac" + struct.pack(">I", len(trac)) + trac
        cmid = b"cmid" + struct.pack(">I", len(body)) + body
        qcp = pmd.to_qcp(cmid)
        self.assertTrue(qcp.startswith(b"RIFF") and qcp[8:12] == b"QLCM")
        self.assertIn(b"data" + struct.pack("<I", 105) + pkt, qcp)

    def test_midi_synth_timing(self):
        # one quarter note at 120 bpm, 480 ticks/quarter -> ~0.5 s of sound
        trk = bytes([0, 0x90, 60, 100]) + bytes([0x83, 0x60, 0x80, 60, 0]) + bytes([0, 0xFF, 0x2F, 0])
        mid = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(trk)) + trk
        events, total = midi_synth.parse_midi(mid)
        self.assertAlmostEqual(total, 0.5, places=3)
        pcm = midi_synth.render_midi(mid)
        self.assertGreater(len(pcm), midi_synth.RATE * 0.5)
        self.assertGreater(np.abs(pcm).max(), 1000)

    @staticmethod
    def _one_note(program, note, ticks):
        """A one-note MIDI file on channel 1 (480 ticks = half a second at 120 bpm)."""
        trk = (bytes([0, 0xC1, program, 0, 0x91, note, 110])
               + _vlq_bytes(ticks) + bytes([0x81, note, 0, 0, 0xFF, 0x2F, 0]))
        return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(trk)) + trk

    def test_a_short_horn_stab_stops_short(self):
        # a 60 ms stab (Brass Section) must not trail into the next one; the old 0.12 s release did
        pcm = midi_synth.render_midi(self._one_note(61, 55, 58)).astype(float) / 32768
        r = midi_synth.RATE
        peak = np.abs(pcm[: r // 5]).max()
        self.assertGreater(peak, 0.01)
        tail = pcm[int(0.32 * r):]                      # (trailing silence is trimmed, so may be empty)
        self.assertLess(np.abs(tail).max() if len(tail) else 0.0, peak / 20, "the stab rings on")

    def test_the_top_octave_of_the_piano_is_much_softer(self):
        # the title tune doubles its melody an octave up; at equal strength those notes pinged on
        # every beat. A SoundFont render has them at a fraction of the melody's level.
        r = midi_synth.RATE
        level = lambda note: float(np.abs(midi_synth.render_midi(self._one_note(0, note, 240))[: r // 2]).max())   # noqa: E731
        self.assertLess(level(95), 0.5 * level(83))            # B6 against B5

    def test_low_piano_notes_are_lighter(self):
        # the menu tune's accompaniment (E3-B3) was boomy next to a SoundFont render
        r = midi_synth.RATE
        level = lambda note: float(np.abs(midi_synth.render_midi(self._one_note(0, note, 240))[: r // 2]).max())   # noqa: E731
        self.assertLess(level(52), 0.6 * level(72))            # E3 against C5

    def test_a_piano_note_starts_with_a_hammer_strike(self):
        # without a bright tick at the start, a quiet chord right after a loud one was lost in
        # the ringing (the menu tune's "duh duh di" came out as "duh di")
        r = midi_synth.RATE
        pcm = midi_synth.render_midi(self._one_note(0, 60, 480)).astype(float) / 32768
        f0 = 440.0 * 2 ** ((60 - 69) / 12)

        def upper(a, b):        # energy above the third harmonic in a 20 ms window
            seg = pcm[int(a * r):int(b * r)]
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 4096)) ** 2
            return float(spec[np.fft.rfftfreq(4096, 1 / r) > 3.5 * f0].sum())
        self.assertGreater(upper(0.0, 0.02), 3 * upper(0.10, 0.12))

    def test_horn_stabs_have_bite_and_the_timpani_a_thump(self):
        # against the Swashbuckler's Island recording the stabs had no bite (the horn had only
        # eight partials, none above 1.5 kHz) and 5 dB too little thump from the timpani
        r = midi_synth.RATE
        horn = midi_synth.render_midi(self._one_note(61, 55, 240)).astype(float) / 32768      # G3, Brass Section
        seg = horn[: int(0.06 * r)] * np.hanning(int(0.06 * r))
        spec = np.abs(np.fft.rfft(seg, 2048)) ** 2
        bite = spec[np.fft.rfftfreq(2048, 1 / r) > 2400].sum() / spec.sum()
        self.assertGreater(bite, 0.02, "some of a horn's first 60 ms is above 2.4 kHz")
        thump = np.abs(midi_synth.render_midi(self._one_note(47, 43, 240))).max() / 32768    # G2 timpani
        self.assertGreater(thump, 0.3, "was 0.24")

    def test_a_melody_note_does_not_click(self):
        # the title tune's melody (about 1 kHz) is smooth in the recording; our hammer tick
        # made every note pop. The bright energy at the very start, against the body of the
        # note, must stay small (it was about 17 dB higher before).
        r = midi_synth.RATE
        pcm = midi_synth.render_midi(self._one_note(0, 83, 480)).astype(float) / 32768   # B5
        freq = np.fft.rfftfreq(4096, 1 / r)

        def power(a, b, lo, hi):
            seg = pcm[int(a * r):int(b * r)]
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 4096)) ** 2
            return float(spec[(freq >= lo) & (freq < hi)].sum())
        click_db = 10 * np.log10((power(0.0, 0.04, 3000, 10000) + 1e-9) / (power(0.06, 0.4, 600, 2000) + 1e-9))
        self.assertLess(click_db, -30, f"the first 40 ms are {click_db:.1f} dB under the body above 3 kHz")

    def test_the_melody_register_is_pushed_forward(self):
        r = midi_synth.RATE
        level = lambda note: float(np.abs(midi_synth.render_midi(self._one_note(0, note, 240))[: r // 2]).max())   # noqa: E731
        self.assertGreater(level(83), 1.3 * level(60) * 0.6, "B5 is not left behind the low notes")

    def test_section_strings_are_up_to_full_level_quickly(self):
        # String Ensemble: a 0.15 s attack let the strings swell in behind the horns; they now
        # reach full level within 0.05 s
        pcm = midi_synth.render_midi(self._one_note(48, 60, 480)).astype(float) / 32768
        r = midi_synth.RATE
        rms = lambda a, b: float(np.sqrt((pcm[int(a * r):int(b * r)] ** 2).mean()))     # noqa: E731
        self.assertGreater(rms(0.05, 0.09), 1.2 * rms(0.30, 0.34))   # the bow's first push, then it settles


def _vlq_bytes(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


class VfsTests(unittest.TestCase):
    def test_overlay_case_insensitive_and_protected(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as ov:
            open(os.path.join(base, "Island.m3g"), "wb").write(b"base")
            v = Vfs([base], ov, log=lambda s: None)
            self.assertEqual(v.read_file("fs:/~/island.M3G"), b"base")
            v.write_file("savegame.dat", b"s1")
            self.assertEqual(v.read_file("SAVEGAME.DAT"), b"s1")
            self.assertTrue(v.remove("savegame.dat"))
            self.assertIsNone(v.read_file("savegame.dat"))
            v.remove("island.m3g")                      # dump files are protected
            self.assertEqual(v.read_file("island.m3g"), b"base")
            v.patchers["island.m3g"] = lambda d: d + b"!"
            self.assertEqual(v.read_file("island.m3g"), b"base!")

    def test_canon(self):
        self.assertEqual(canon("fs:/~/./a//b.dat"), "a/b.dat")


class DataHomeTests(unittest.TestCase):
    def test_old_folder_is_copied_once_and_kept(self):
        from khvcemu import paths
        with tempfile.TemporaryDirectory() as home:
            old = os.path.join(home, paths.LEGACY_APP_DIR, "game", "files")
            os.makedirs(old)
            with open(os.path.join(old, "savegame.dat"), "wb") as f:
                f.write(b"progress")
            new = paths.data_home(home)
            self.assertEqual(new, os.path.join(home, paths.APP_DIR))
            with open(os.path.join(new, "game", "files", "savegame.dat"), "rb") as f:
                self.assertEqual(f.read(), b"progress")
            self.assertTrue(os.path.isdir(old), "the old folder is left alone")
            with open(os.path.join(new, "game", "files", "savegame.dat"), "wb") as f:
                f.write(b"newer")                       # a second call must not copy over it
            paths.data_home(home)
            with open(os.path.join(new, "game", "files", "savegame.dat"), "rb") as f:
                self.assertEqual(f.read(), b"newer")

    def test_failed_copy_falls_back_to_old_folder(self):
        from unittest import mock
        from khvcemu import paths
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, paths.LEGACY_APP_DIR, "x"))
            with mock.patch("shutil.copytree", side_effect=OSError("locked")):
                got = paths.data_home(home)
            self.assertEqual(got, os.path.join(home, paths.LEGACY_APP_DIR))
            self.assertFalse(os.path.exists(os.path.join(home, paths.APP_DIR)), "no half-made target")
            self.assertEqual(paths.data_home(home), os.path.join(home, paths.APP_DIR), "retried next time")


class GameDataDirTests(unittest.TestCase):
    """The data folder is named after the game folder, so renaming or moving that
    folder must not look like the saves were lost."""

    def setUp(self):
        from khvcemu import paths
        self.paths = paths
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.base = os.path.join(self.home, paths.APP_DIR)
        os.makedirs(self.base)
        self.notes = []

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, kind="save"):
        """A data folder holding real progress."""
        if kind == "save":
            d = os.path.join(self.base, name, "files")
            f = "savegame.dat"
        elif kind == "state":
            d, f = os.path.join(self.base, name, "states"), "slot1.khs"
        else:
            d, f = os.path.join(self.base, name, "save_backups"), "savegame.dat.1.bak"
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f), "wb") as fh:
            fh.write(b"x")
        return os.path.join(self.base, name)

    def ask(self, game_folder_name):
        return self.paths.game_data_dir(os.path.join(self.home, game_folder_name),
                                        home=self.home, log=self.notes.append)

    def test_matching_folder_is_used(self):
        want = self.make("khvcemu")
        self.assertEqual(self.ask("khvcemu"), want)
        self.assertEqual(self.notes, [])

    def test_renamed_game_folder_finds_the_one_existing_save_folder(self):
        old = self.make("khemu")                      # saves made before the rename
        self.assertEqual(self.ask("khvcemu"), old)
        self.assertTrue(any("khemu" in n for n in self.notes), self.notes)

    def test_a_state_or_a_backup_counts_as_progress(self):
        for kind, name in (("state", "by_state"), ("backup", "by_backup")):
            with self.subTest(kind=kind):
                self.tearDown()
                self.setUp()
                made = self.make(name, kind)
                self.assertEqual(self.ask("new"), made)

    def test_empty_folders_are_not_mistaken_for_saves(self):
        os.makedirs(os.path.join(self.base, "probe", "files"))     # a run that saved nothing
        os.makedirs(os.path.join(self.base, "rt_test", "states"))
        real = self.make("khemu")
        self.assertEqual(self.ask("khvcemu"), real)

    def test_several_candidates_are_never_guessed_between(self):
        self.make("one")
        self.make("two")
        got = self.ask("khvcemu")
        self.assertEqual(got, os.path.join(self.base, "khvcemu"), "keeps its own folder")
        self.assertTrue(any("'one'" in n and "'two'" in n for n in self.notes), self.notes)

    def test_nothing_is_moved_copied_or_deleted(self):
        old = self.make("khemu")
        before = sorted(os.listdir(self.base))
        self.ask("khvcemu")
        self.assertEqual(sorted(os.listdir(self.base)), before, "no folder appears or vanishes")
        self.assertTrue(os.path.isfile(os.path.join(old, "files", "savegame.dat")))

    def test_pointing_back_at_the_old_name_still_works(self):
        old = self.make("khemu")
        self.assertEqual(self.ask("khvcemu"), old)
        self.assertEqual(self.ask("khemu"), old, "the original name still resolves")

    def test_a_fresh_install_gets_its_own_folder(self):
        self.assertEqual(self.ask("khvcemu"), os.path.join(self.base, "khvcemu"))
        self.assertEqual(self.notes, [])

    def test_odd_characters_in_the_folder_name(self):
        self.assertEqual(self.paths.folder_name("/a/b/KH V CAST (dump)!"), "KH_V_CAST_dump_")
        self.assertEqual(self.paths.folder_name("/"), "game")


class AudioFormatTests(unittest.TestCase):
    def test_mono_pcm_is_converted_for_a_stereo_mixer(self):
        # Windows often opens a stereo mixer; mono data fed to it played at
        # double speed, an octave high
        from khvcemu.audio import RATE, AudioEngine

        class E:
            def log(self, m): pass
            logv = log
        eng = AudioEngine(E(), enabled=False)
        pcm = np.array([1, 2, 3], np.int16)
        eng.out_rate, eng.out_channels = RATE, 2
        self.assertEqual(list(np.frombuffer(eng._device_bytes(pcm), np.int16)), [1, 1, 2, 2, 3, 3])
        eng.out_rate, eng.out_channels = RATE * 2, 1
        self.assertEqual(len(np.frombuffer(eng._device_bytes(np.zeros(100, np.int16)), np.int16)), 200)


class SaveStateUnitTests(unittest.TestCase):
    def test_memory_pages_round_trip(self):
        from khvcemu import savestate
        cpu = Cpu(log=lambda s: None)
        base = 0x10000000
        cpu.write(base + 5, b"hello")
        cpu.write(base + 3 * savestate.PAGE, b"\x01" * 10)
        cpu.write(base + 4 * savestate.PAGE - 1, b"\x02")
        idx, pages = savestate._dump_region(cpu.uc, base, 8 * savestate.PAGE)
        self.assertEqual(list(np.frombuffer(idx, np.uint32)), [0, 3])   # only non-zero pages kept
        cpu.write(base + 6 * savestate.PAGE, b"junk")                     # must be wiped on restore
        cpu.write(base + 5, b"HELLO")
        savestate._restore_region(cpu.uc, base, 8 * savestate.PAGE, idx, pages)
        self.assertEqual(cpu.read(base + 5, 5), b"hello")
        self.assertEqual(cpu.read(base + 4 * savestate.PAGE - 1, 1), b"\x02")
        self.assertEqual(cpu.read(base + 6 * savestate.PAGE, 4), b"\0\0\0\0")

    def test_area_autosave_timing_and_manual_saves_do_not_reset_the_timer(self):
        from khvcemu import savestate
        from khvcemu.savestate import StateSlots

        class Emu:
            applet_ptr = 1
            data_dir = "."
            last_loading_ms = None
            now = 0

            def clock_ms(self):
                return self.now

            def save_state(self, path, thumbnail=True):
                self.saved = path
        emu = Emu()
        slots = StateSlots(emu, folder=".")
        self.assertFalse(slots.area_save_due(), "no Loading screen seen")
        emu.now, emu.last_loading_ms = 100000, 100000
        self.assertFalse(slots.area_save_due(), "still on the Loading screen")
        emu.now = 100000 + savestate.AREA_SAVE_DELAY_MS - 1
        self.assertFalse(slots.area_save_due())
        emu.now = 100000 + savestate.AREA_SAVE_DELAY_MS
        self.assertTrue(slots.area_save_due(), "about 3 seconds after the last Loading frame")
        slots.autosave_enabled = False
        self.assertFalse(slots.area_save_due(), "F8 / --no-autosave also turns these off")
        slots.autosave_enabled = True
        emu.applet_ptr = 0
        self.assertFalse(slots.area_save_due())
        emu.applet_ptr = 1
        self.assertTrue(slots.area_save_allowed(), "the first area after the window opened saves at once")
        slots.last_autosave_ms = emu.now - 1000
        self.assertFalse(slots.area_save_allowed(), "not twice within the gap")
        slots.last_autosave_ms = emu.now - savestate.AREA_SAVE_MIN_GAP_MS
        self.assertTrue(slots.area_save_allowed())
        # saving by hand does not push the 5-minute autosave back
        slots.last_auto_ms = 0
        emu.now = 400000                      # past the 5-minute mark
        slots.save(1)
        self.assertEqual(slots.last_auto_ms, 0)
        self.assertTrue(slots.autosave_due())

    def test_slot_names(self):
        from khvcemu.savestate import StateSlots
        self.assertEqual(StateSlots.parse("3"), 3)
        self.assertEqual(StateSlots.parse("auto"), 0)
        self.assertEqual(StateSlots.parse("AUTO2"), "auto2")
        with self.assertRaises(ValueError):
            StateSlots.parse("auto9")


class SaveBackupTests(unittest.TestCase):
    def _backups(self, data_dir, name="savegame.dat"):
        d = os.path.join(data_dir, "save_backups")
        return sorted(f for f in os.listdir(d) if f.startswith(name)) if os.path.isdir(d) else []

    def test_vfs_backs_up_before_overwrite_and_delete(self):
        with tempfile.TemporaryDirectory() as data:
            ov = os.path.join(data, "files")
            v = Vfs([], ov, log=lambda s: None)
            v.write_file("savegame.dat", b"first")           # nothing to back up yet
            self.assertEqual(self._backups(data), [])
            v.write_file("savegame.dat", b"second")          # keeps "first"
            v.write_file("savegame.dat", b"second")          # unchanged: no new copy needed
            v.write_file("settings.dat", b"a")
            v.write_file("settings.dat", b"b")               # not a progress file
            self.assertEqual(len(self._backups(data)), 1)
            self.assertEqual(self._backups(data, "settings.dat"), [])
            v.remove("savegame.dat")                         # keeps "second"
            kept = [open(os.path.join(data, "save_backups", f), "rb").read() for f in self._backups(data)]
            self.assertEqual(sorted(kept), [b"first", b"second"])
            self.assertIsNone(v.read_file("savegame.dat"))

    def test_install_save_protects_real_progress(self):
        from khvcemu import chapters

        class FakeEmu:
            def __init__(self, root, data):
                self.game_root, self.data_dir, self.logs = root, data, []
            def log(self, m):
                self.logs.append(m)

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as data:
            open(os.path.join(root, "savegame(agrabah).dat"), "wb").write(b"STOCK-AGRABAH")
            open(os.path.join(root, "savegame(island).dat"), "wb").write(b"STOCK-ISLAND")
            emu = FakeEmu(root, data)
            target = os.path.join(data, "files", "savegame.dat")
            chapters.install_save(emu, "agrabah")            # fresh: just seeds
            self.assertEqual(open(target, "rb").read(), b"STOCK-AGRABAH")
            chapters.install_save(emu, "island")             # replacing a stock save: no backup
            self.assertEqual(self._backups(data), [])
            open(target, "wb").write(b"REAL-PROGRESS")       # the game saved for real
            chapters.install_save(emu, "agrabah")
            self.assertEqual(open(target, "rb").read(), b"STOCK-AGRABAH")
            kept = self._backups(data)
            self.assertEqual(len(kept), 1)
            self.assertEqual(open(os.path.join(data, "save_backups", kept[0]), "rb").read(), b"REAL-PROGRESS")
            self.assertTrue(any("WARNING" in m for m in emu.logs))


class LeaderboardTests(unittest.TestCase):
    """The offline score table answers in the format kh.mod's parser expects."""

    BASE = "http://swervenet.superscape.com/disney/"

    def setUp(self):
        from khvcemu.leaderboard import Leaderboard
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "leaderboard.db")
        self.lb = Leaderboard(self.path)

    def tearDown(self):
        self.lb.db.close()
        self.tmp.cleanup()

    def post(self, score, uid="", lid="island"):
        url = f"{self.BASE}rank.php?uid={uid}&aid=KH&lid={lid}&s={score}&t=55&u1=1&u2="
        return self.lb.handle(url)

    def test_post_assigns_uid_and_ranks_against_every_run(self):
        self.assertEqual(self.post(1500), (200, b"*r|ok|local~|island~1"))
        self.assertEqual(self.post(900, uid="local"), (200, b"*r|ok|local~|island~2"))
        self.assertEqual(self.post(2000, uid="rival"), (200, b"*r|ok|rival~|island~1"))
        # equal scores share a place: only 1500 and 2000 beat this 900
        self.assertEqual(self.post(900, uid="local"), (200, b"*r|ok|local~|island~3"))

    def test_ties_share_a_place_and_levels_are_separate(self):
        self.post(500)
        self.assertEqual(self.post(500), (200, b"*r|ok|local~|island~1"))
        self.assertEqual(self.post(10, lid="agrabah"), (200, b"*r|ok|local~|agrabah~1"))

    def test_rankex_ranks_the_games_own_table_and_skips_unposted_levels(self):
        self.post(1500)
        self.post(2000, uid="rival")
        url = f"{self.BASE}rankex.php?uid=&aid=KH&lid=wonderland,island&s=1,1500&t=12&u1=1"
        self.assertEqual(self.lb.handle(url), (200, b"*r|ok|local~|island~2"))
        none = f"{self.BASE}rankex.php?uid=&aid=KH&lid=wonderland&s=1&t=12&u1=1"
        self.assertEqual(self.lb.handle(none), (200, b"*r|ok|local~"))

    def test_bad_requests(self):
        self.assertEqual(self.post("abc"), (200, b"*r|invalidentry"))
        self.assertEqual(self.post(-5), (200, b"*r|invalidentry"))
        self.assertEqual(self.post(5, lid=""), (200, b"*r|invalidentry"))
        # not ours: web.py turns this into a 404 and the game shows its own error
        self.assertIsNone(self.lb.handle(self.BASE + "download.php?f=wonderland.dat"))

    def test_reply_separators_cannot_be_injected(self):
        reply = self.post(7, uid="a|b~c", lid="x|y~z")[1].decode()
        self.assertEqual(reply, "*r|ok|a_b_c~|x_y_z~1")

    def test_scores_survive_a_restart(self):
        from khvcemu.leaderboard import Leaderboard
        self.post(1500)
        self.lb.db.close()
        self.lb = Leaderboard(self.path)
        self.assertEqual(self.post(900), (200, b"*r|ok|local~|island~2"))


if __name__ == "__main__":
    unittest.main()
