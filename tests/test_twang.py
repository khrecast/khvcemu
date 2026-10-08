"""The banjo/koto/shamisen/sitar voice (GM 104 to 107): Agrabah's rhythm part is a koto and has to be heard."""
import os
import struct
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import midi_synth, music_settings  # noqa: E402

R = midi_synth.RATE


def one_note(program: int, note: int = 66, vel: int = 90, length: float = 0.3) -> bytes:
    """A format 0 MIDI file: one note on channel 0 with the given GM program (120 bpm, 480 ticks a beat)."""
    def vlq(n):
        out = [n & 0x7F]
        while n >> 7:
            n >>= 7
            out.append((n & 0x7F) | 0x80)
        return bytes(reversed(out))
    ticks = int(length * 960)
    track = (b"\x00\xFF\x51\x03\x07\xA1\x20" + b"\x00\xC0" + bytes([program]) + b"\x00\x90" + bytes([note, vel])
             + vlq(ticks) + b"\x80" + bytes([note, 0]) + b"\x00\xFF\x2F\x00")
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track


def centroid(pcm: np.ndarray) -> float:
    sp = np.abs(np.fft.rfft(pcm.astype(np.float64)))
    f = np.fft.rfftfreq(len(pcm), 1 / R)
    return float((sp * f).sum() / sp.sum())


class TwangTests(unittest.TestCase):
    def test_the_picked_instruments_have_their_own_voice_and_the_harp_keeps_its_own(self):
        for program in (104, 105, 106, 107):
            self.assertEqual(midi_synth._timbre(program), "twang", program)
        for program in (24, 30, 45, 46):
            self.assertEqual(midi_synth._timbre(program), "pluck", program)
        self.assertEqual(music_settings.GROUP_OF_KIND["twang"], "harp", "it answers to the Harp / plucked slider")

    def test_a_koto_note_is_brighter_and_stronger_than_a_harp_note(self):
        quiet = {"harp": 0.05}          # a single note at full strength is peak-normalised: compare them unnormalised
        koto = midi_synth.render_midi(one_note(107), quiet)
        harp = midi_synth.render_midi(one_note(46), quiet)
        self.assertGreater(centroid(koto), 1.8 * centroid(harp), "bright: this is the twang")
        self.assertGreater(int(np.abs(koto).max()), 1.5 * int(np.abs(harp).max()), "and it comes forward in a mix")
        self.assertTrue(np.array_equal(koto, midi_synth.render_midi(one_note(107), quiet)), "the pick noise is repeatable")

    def test_the_note_is_short_and_dry(self):
        pcm = midi_synth.render_midi(one_note(107, length=0.5)).astype(np.float64)
        early = np.abs(pcm[: R // 10]).max()
        late = np.abs(pcm[int(0.9 * R):]).max() if len(pcm) > int(0.9 * R) else 0
        self.assertLess(late, 0.1 * early, "it has died away well before a second")


if __name__ == "__main__":
    unittest.main()
