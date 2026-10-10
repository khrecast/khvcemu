"""A small software mixer with the part of pygame.mixer's interface that AudioEngine uses, for hosts that pull
audio themselves (the Android app: an AudioTrack asks for the next block of samples).

    mixer = PcmMixer(rate=22050, channels=1)
    sound = mixer.Sound(buffer=pcm_bytes)      # little-endian int16 samples, interleaved when channels > 1
    channel = sound.play(loops=0)              # plays loops + 1 times; -1 plays forever
    channel.set_volume(0.5); channel.pause(); channel.unpause(); channel.stop()
    block = mixer.read(512)                    # 512 frames of mixed int16 audio, as bytes (silence when idle)

The desktop keeps using pygame.mixer; AudioEngine takes either (see its `mixer` argument).
"""

from __future__ import annotations

import threading

import numpy as np


class Channel:
    def __init__(self, pcm: np.ndarray, loops: int):
        self.pcm = pcm                    # int16, shape (frames, channels)
        self.loops = int(loops)           # passes still to repeat after the current one; < 0 means forever
        self.pos = 0
        self.volume = 1.0
        self.paused = False
        self.done = False

    # the calls AudioEngine makes ------------------------------------------------------------
    def set_volume(self, v: float):
        self.volume = max(0.0, float(v))

    def stop(self):
        self.done = True

    def pause(self):
        self.paused = True

    def unpause(self):
        self.paused = False

    def get_busy(self) -> bool:
        return not self.done

    # mixing ---------------------------------------------------------------------------------
    def take(self, frames: int) -> np.ndarray:
        """The next `frames` frames as float32 (zeros past the end), advancing the position."""
        out = np.zeros((frames, self.pcm.shape[1]), np.float32)
        filled = 0
        while filled < frames and not self.done:
            left = len(self.pcm) - self.pos
            if left <= 0:
                if self.loops == 0 or len(self.pcm) == 0:
                    self.done = True
                    break
                if self.loops > 0:
                    self.loops -= 1
                self.pos = 0
                continue
            n = min(frames - filled, left)
            out[filled:filled + n] = self.pcm[self.pos:self.pos + n]
            self.pos += n
            filled += n
        if self.pos >= len(self.pcm) and self.loops == 0:
            self.done = True
        return out


class Sound:
    def __init__(self, mixer: "PcmMixer", buffer: bytes):
        self.mixer = mixer
        self.pcm = np.frombuffer(buffer, dtype="<i2").reshape(-1, mixer.channels)

    def play(self, loops: int = 0):
        ch = Channel(self.pcm, loops)
        self.mixer.add(ch)
        return ch


class PcmMixer:
    def __init__(self, rate: int = 22050, channels: int = 1, max_channels: int = 16):
        self.rate = rate
        self.channels = channels
        self.max_channels = max_channels
        self.active: list = []
        self.lock = threading.Lock()
        self.paused = False               # the whole mixer is held (the app is in the background)

    # pygame.mixer look-alikes ---------------------------------------------------------------
    def get_init(self):
        return self.rate, -16, self.channels

    def Sound(self, buffer: bytes = b"") -> Sound:
        return Sound(self, buffer)

    def add(self, ch: Channel):
        with self.lock:
            self.active = [c for c in self.active if not c.done]
            if len(self.active) >= self.max_channels:     # all busy: the oldest one gives way, as pygame does
                self.active[0].done = True
                self.active.pop(0)
            self.active.append(ch)

    # the host pulls ---------------------------------------------------------------------------
    def read(self, frames: int) -> bytes:
        """`frames` frames of mixed audio as little-endian int16 bytes. Silence while idle or held."""
        if self.paused:
            return bytes(frames * self.channels * 2)
        acc = np.zeros((frames, self.channels), np.float32)
        with self.lock:
            for ch in self.active:
                if ch.paused or ch.done:
                    continue
                acc += ch.take(frames) * ch.volume
            self.active = [c for c in self.active if not c.done]
        return np.clip(acc, -32768, 32767).astype("<i2").tobytes()
