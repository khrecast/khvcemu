"""Plays the game's tunes in the launcher's Sound tab: through the built-in synth with the
tab's settings, or a recording chosen for comparison.

pygame and numpy are imported only when something is played, so the launcher still opens
before the requirements are installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .paths import no_window

# The game's music, in the order the Sound tab lists it: (file in mod/<id>/, name shown)
TUNES = [
    ("training.mid", "Title menu and Obstacle Course"),
    ("island.mid", "Swashbuckler's Island"),
    ("agrabah.mid", "Agrabah"),
    ("castle.mid", "Maleficent's Castle"),
    ("death.mid", "Game over"),
    ("keyblade.mid", "Keyblade found (short)"),
    ("good.mid", "Good (short)"),
    ("bad.mid", "Bad (short)"),
    ("magic_alert.mid", "Magic alert (short)"),
]
# The built-in tunes differ in loudness (Swashbuckler's Island renders at an RMS of about 2100,
# the title tune at 3250), and Match used to copy each tune's own level, so a recording of the quiet
# tune stayed quiet next to the others. Match now never aims below this level (16-bit RMS).
MATCH_FLOOR_RMS = 3000.0

RECORDING_TYPES = [("Audio", "*.flac *.wav *.mp3 *.ogg *.m4a *.opus"), ("All files", "*.*")]


def tune_path(dump: str, name: str):
    """Where the game keeps a tune (mod/<app id>/<name>, any letter case), or None."""
    mod = os.path.join(dump, "mod") if dump else ""
    if not mod or not os.path.isdir(mod):
        return None
    for sub in sorted(os.listdir(mod)):
        d = os.path.join(mod, sub)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.lower() == name.lower():
                    return os.path.join(d, fn)
    return None


class MusicPreview:
    """One looping sound at a time. Rendering is done by render_tune()/decode_recording(),
    which are safe to call from a worker thread; play() and stop() belong to the Tk thread."""

    def __init__(self):
        self.pygame = None
        self.rate, self.channels = 22050, 1
        self.sound = None
        self._recordings: dict = {}      # path -> device bytes (decoding a FLAC takes a moment)

    def open(self):
        """Start the audio output (once). Raises an exception with a readable message if it
        cannot: no pygame, no numpy, or no sound device."""
        if self.pygame is not None:
            return
        import numpy  # noqa: F401  (the synth needs it; fail here, with a clear message)
        import pygame
        from .midi_synth import RATE
        try:
            pygame.mixer.init(RATE, -16, 1, 1024, allowedchanges=0)
        except TypeError:
            pygame.mixer.init(RATE, -16, 1, 1024)
        freq, size, chans = pygame.mixer.get_init()
        if size != -16:
            pygame.mixer.quit()
            raise RuntimeError(f"unsupported sound format {size}")
        self.pygame, self.rate, self.channels = pygame, freq, chans

    # ------------------------------------------------------------ rendering (any thread)
    def render_tune(self, path: str, settings: dict) -> bytes:
        from .audio import device_bytes
        from .midi_synth import render_midi
        with open(path, "rb") as f:
            pcm = render_midi(f.read(), settings)
        return device_bytes(pcm, self.rate, self.channels)

    def decode_recording(self, path: str) -> bytes:
        try:
            st = os.stat(path)
            key = (path, st.st_size, st.st_mtime_ns)    # an edited file is decoded again
        except OSError:
            key = (path, None, None)
        raw = self._recordings.get(key)
        if raw is not None:
            return raw
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            r = subprocess.run([ffmpeg, "-nostdin", "-v", "quiet", "-i", path, "-f", "s16le", "-ac", str(self.channels),
                                "-ar", str(self.rate), "pipe:1"], capture_output=True, timeout=120,
                               stdin=subprocess.DEVNULL, **no_window())
            if r.returncode or not r.stdout:
                raise RuntimeError("ffmpeg could not read that file")
            raw = r.stdout
        else:                            # pygame reads WAV and OGG (and often FLAC/MP3) itself
            raw = self.pygame.mixer.Sound(path).get_raw()
        while len(self._recordings) >= 3:             # a few at a time: a long recording is tens of MB
            self._recordings.pop(next(iter(self._recordings)))
        self._recordings[key] = raw
        return raw

    @staticmethod
    def with_gain(raw: bytes, gain: float) -> bytes:
        """Sound bytes at another volume (1 = unchanged), clipped rather than wrapped."""
        if abs(gain - 1.0) < 1e-9:
            return raw
        import numpy as np
        a = np.frombuffer(raw, np.int16).astype(np.float32) * float(gain)
        return np.clip(a, -32768, 32767).astype(np.int16).tobytes()

    @staticmethod
    def match_gain(ours: bytes, recording: bytes) -> float:
        """The volume that makes the recording as loud as our render (but at least as loud as
        MATCH_FLOOR_RMS, so recordings of the built-in tunes that render quietly are not left
        behind), measured over the length of ours (a recording often holds several loops),
        between 5% and 400%."""
        import numpy as np
        a = np.frombuffer(ours, np.int16).astype(np.float64)
        b = np.frombuffer(recording, np.int16).astype(np.float64)[: len(a)]
        ra, rb = np.sqrt((a ** 2).mean()) if len(a) else 0.0, np.sqrt((b ** 2).mean()) if len(b) else 0.0
        if rb <= 0 or ra <= 0:
            return 1.0
        return float(min(4.0, max(0.05, max(ra, MATCH_FLOOR_RMS) / rb)))

    # ------------------------------------------------------------ playback (Tk thread)
    def play(self, raw: bytes):
        self.stop()
        self.sound = self.pygame.mixer.Sound(buffer=raw)
        self.sound.play(loops=-1)

    def stop(self):
        if self.pygame is not None:
            self.pygame.mixer.stop()
        self.sound = None

    def close(self):
        if self.pygame is not None:
            try:
                self.pygame.mixer.quit()
            except Exception:
                pass
            self.pygame = None
