"""The software mixer used where the host pulls audio (Android), and AudioEngine playing through it."""
import io
import os
import sys
import types
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu import audio  # noqa: E402
from khvcemu.pcmmixer import PcmMixer  # noqa: E402

RATE = 22050


def pcm_bytes(samples):
    return np.asarray(samples, "<i2").tobytes()


def read_all(mixer, frames):
    return np.frombuffer(mixer.read(frames), "<i2")


class MixerTests(unittest.TestCase):
    def setUp(self):
        self.m = PcmMixer(RATE, 1)

    def test_it_looks_like_a_mixer_to_audio_engine(self):
        self.assertEqual(self.m.get_init(), (RATE, -16, 1))

    def test_silence_when_idle(self):
        self.assertEqual(self.m.read(64), bytes(128))

    def test_a_sound_plays_once_then_ends(self):
        ch = self.m.Sound(buffer=pcm_bytes(range(1, 11))).play()
        a = read_all(self.m, 6)
        b = read_all(self.m, 6)
        self.assertEqual(list(a), [1, 2, 3, 4, 5, 6])
        self.assertEqual(list(b), [7, 8, 9, 10, 0, 0])
        self.assertTrue(ch.done)
        self.assertEqual(self.m.read(4), bytes(8), "nothing left to play")

    def test_loops_means_that_many_more_plays(self):
        self.m.Sound(buffer=pcm_bytes([1, 2, 3])).play(loops=2)         # 3 passes in all
        self.assertEqual(list(read_all(self.m, 12)), [1, 2, 3, 1, 2, 3, 1, 2, 3, 0, 0, 0])

    def test_minus_one_plays_forever(self):
        ch = self.m.Sound(buffer=pcm_bytes([5, 6])).play(loops=-1)
        out = read_all(self.m, 4001)
        self.assertEqual(list(out[:6]), [5, 6, 5, 6, 5, 6])
        self.assertFalse(ch.done)

    def test_volume_scales_and_two_sounds_add_and_clip(self):
        a = self.m.Sound(buffer=pcm_bytes([1000, 1000, 1000])).play()
        a.set_volume(0.5)
        self.assertEqual(list(read_all(self.m, 3)), [500, 500, 500])
        self.m.Sound(buffer=pcm_bytes([30000, 30000])).play()
        self.m.Sound(buffer=pcm_bytes([30000, 30000])).play()
        self.assertEqual(list(read_all(self.m, 2)), [32767, 32767], "the sum is clipped, not wrapped")

    def test_pause_holds_the_position_and_stop_ends_it(self):
        ch = self.m.Sound(buffer=pcm_bytes([1, 2, 3, 4])).play()
        self.assertEqual(list(read_all(self.m, 2)), [1, 2])
        ch.pause()
        self.assertEqual(list(read_all(self.m, 2)), [0, 0])
        ch.unpause()
        self.assertEqual(list(read_all(self.m, 2)), [3, 4])
        ch2 = self.m.Sound(buffer=pcm_bytes([9, 9, 9])).play()
        ch2.stop()
        self.assertEqual(list(read_all(self.m, 3)), [0, 0, 0])

    def test_the_whole_mixer_can_be_held(self):
        self.m.Sound(buffer=pcm_bytes([7, 7, 7, 7])).play()
        self.m.paused = True
        self.assertEqual(list(read_all(self.m, 2)), [0, 0])
        self.m.paused = False
        self.assertEqual(list(read_all(self.m, 4)), [7, 7, 7, 7], "the sound did not advance while held")

    def test_too_many_sounds_drop_the_oldest(self):
        m = PcmMixer(RATE, 1, max_channels=2)
        first = m.Sound(buffer=pcm_bytes([1] * 10)).play(loops=-1)
        m.Sound(buffer=pcm_bytes([2] * 10)).play(loops=-1)
        m.Sound(buffer=pcm_bytes([4] * 10)).play(loops=-1)
        self.assertTrue(first.done)
        self.assertEqual(set(np.frombuffer(m.read(4), "<i2")), {6})

    def test_stereo_frames_stay_interleaved(self):
        m = PcmMixer(RATE, 2)
        m.Sound(buffer=pcm_bytes([1, 2, 3, 4])).play()
        self.assertEqual(list(np.frombuffer(m.read(2), "<i2")), [1, 2, 3, 4])


def wav_bytes(samples):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm_bytes(samples))
    return out.getvalue()


class EngineThroughTheMixerTests(unittest.TestCase):
    def make(self):
        emu = types.SimpleNamespace(logv=lambda *_: None, log=lambda *_: None, clock_ms=lambda: 0, data_dir=None)
        mixer = PcmMixer(RATE, 1)
        return audio.AudioEngine(emu, enabled=True, mixer=mixer), mixer

    def test_the_engine_uses_the_host_mixer_without_pygame(self):
        eng, mixer = self.make()
        self.assertIs(eng.mixer, mixer)
        self.assertEqual((eng.out_rate, eng.out_channels), (RATE, 1))

    def test_a_played_sound_comes_out_of_the_mixer(self):
        eng, mixer = self.make()
        tone = (np.sin(np.arange(2205) * 0.3) * 10000).astype(np.int16)
        v = eng.play(wav_bytes(tone), "tone.wav", volume=100, loops=0)
        out = read_all(mixer, 2205)
        self.assertGreater(np.abs(out).max(), 5000)
        self.assertEqual(len(out), 2205)
        eng.set_volume(v, 0)
        self.assertEqual(int(np.abs(read_all(mixer, 100)).max()), 0, "volume 0 is silent")

    def test_stopping_a_voice_silences_it(self):
        eng, mixer = self.make()
        v = eng.play(wav_bytes([8000] * 4000), "a.wav", volume=100, loops=-1)
        self.assertGreater(np.abs(read_all(mixer, 100)).max(), 0)
        eng.stop(v)
        self.assertEqual(int(np.abs(read_all(mixer, 100)).max()), 0)


if __name__ == "__main__":
    unittest.main()
