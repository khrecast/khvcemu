"""Audio engine: decodes BREW media buffers to PCM and mixes them with pygame.

Formats: MIDI (built-in synth, or fluidsynth + SoundFont when available, or the player's own
recording of that tune: see AudioEngine.music_files),
CMX .pmd (pmd.py), WAV, and anything ffmpeg can decode (QCP, MP3).
Voice completion is tracked on the emulator clock so IMedia "done"
notifications arrive at the right time even when running headless.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import midi_synth, music_settings, pmd
from .paths import no_window

RATE = midi_synth.RATE


def _synth_version() -> str:
    """A fingerprint of the code that turns a tune into sound: when it changes, every cached render
    is stale and a new one is made."""
    h = hashlib.sha1()
    here = os.path.dirname(os.path.abspath(__file__))
    for n in ("midi_synth.py", "music_settings.py"):
        try:
            with open(os.path.join(here, n), "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(n.encode())
    return h.hexdigest()[:12]


SYNTH_VERSION = _synth_version()
CACHE_KEEP = 48                    # rendered tunes kept on disk (one per tune and Sound tab setting)
FIRST_TUNES = ("training.mid", "island.mid", "agrabah.mid", "castle.mid")   # rendered first: the likeliest to play soon


@dataclass(eq=False)          # identity comparison (pcm is an array)
class Voice:
    pcm: np.ndarray
    name: str
    volume: int
    loops: int
    start_ms: int
    on_done: Optional[Callable] = None
    channel: object = None
    paused_at: Optional[int] = None
    done: bool = False

    @property
    def duration_ms(self) -> int:
        return int(len(self.pcm) * 1000 / RATE)


class AudioEngine:
    def __init__(self, emu, enabled=True, soundfont: Optional[str] = None, music: Optional[dict] = None,
                 music_files: Optional[dict] = None, wonderland_volume: float = 1.0):
        self.emu = emu
        self.wonderland_volume = max(0.0, min(2.0, float(wonderland_volume)))   # the Setup tab's slider
        self.enabled = enabled
        self.music = music_settings.clean(music)   # the Sound tab's sliders (all 1.0 = as tuned)
        # the player's own recordings to play instead of a tune: {"training.mid": {"path", "gain"}}
        self.music_files = {str(k).lower(): dict(v) for k, v in (music_files or {}).items()}
        self._file_failed: set = set()     # (path, size, mtime) that could not be used: tried again once edited
        self._midi_length: dict = {}       # sha1 of a MIDI -> samples the built-in synth renders it to
        data_dir = getattr(emu, "data_dir", None)
        self.cache_dir = os.path.join(data_dir, "audio_cache") if data_dir else None   # rendered tunes, kept between runs
        self._key_locks: dict = {}         # one lock per sound, so the background renderer and the game never both render it
        self._key_locks_guard = threading.Lock()
        self.soundfont = soundfont if soundfont and os.path.isfile(soundfont) else None
        self.fluidsynth = shutil.which("fluidsynth") if self.soundfont else None
        self.ffmpeg = shutil.which("ffmpeg")
        self.cache: dict[str, np.ndarray] = {}
        self.voices: list[Voice] = []
        self.mixer = None
        self.master_volume = 1.0
        self.capture: Optional[list] = None      # tests: list of (name, samples)
        self.out_rate, self.out_channels = RATE, 1
        if enabled:
            try:
                import pygame
                pygame.mixer.pre_init(RATE, -16, 1, 512)
                try:     # ask SDL to convert to the device itself...
                    pygame.mixer.init(RATE, -16, 1, 512, allowedchanges=0)
                except TypeError:
                    pygame.mixer.init(RATE, -16, 1, 512)
                pygame.mixer.set_num_channels(16)
                self.mixer = pygame.mixer
                # ...but go by what was actually opened: Windows often gives a stereo
                # mixer, and feeding it mono data played everything an octave high
                # at double speed (half-length music, thin kick drum)
                freq, size, chans = pygame.mixer.get_init()
                if size != -16:
                    raise RuntimeError(f"unsupported mixer sample format {size}")
                self.out_rate, self.out_channels = freq, chans
                emu.logv(f"[audio] mixer {freq} Hz, {chans} channel(s)")
            except Exception as e:
                self.mixer = None
                emu.log(f"[audio] no audio output ({e}); continuing silently")

    # --------------------------------------------------------------- decode
    def decode(self, data: bytes, name: str = "") -> np.ndarray:
        # the music settings are part of the key: a tune rendered with other settings is another sound
        key = hashlib.sha1(data).hexdigest() + "|" + music_settings.to_text(self.music)
        wl = self.wonderland_volume if self.is_wonderland(name) else 1.0
        if wl != 1.0:
            key += f"|wonderland{wl:g}"
        over = self._music_file(data, name)
        if over is not None:                      # another file, gain or edit is another sound
            try:
                st = os.stat(over["path"])
                key += f"|{over['path']}|{over.get('gain', 1.0)}|{st.st_size}|{st.st_mtime_ns}"
            except OSError:
                key += "|missing:" + over["path"]
        pcm = self.cache.get(key)
        if pcm is not None:
            return pcm
        with self._key_lock(key):
            pcm = self.cache.get(key)          # the background renderer may have just finished it
            if pcm is not None:
                return pcm
            try:
                pcm = self._decode(data, name)
            except Exception as e:
                self.emu.log(f"[audio] could not decode {name or 'buffer'} ({len(data)} bytes): {e}")
                pcm = np.zeros(RATE // 10, np.int16)
            if wl != 1.0:
                pcm = np.clip(pcm.astype(np.float32) * wl, -32768, 32767).astype(np.int16)
            self.cache[key] = pcm
            return pcm

    def _key_lock(self, key: str):
        with self._key_locks_guard:
            return self._key_locks.setdefault(key, threading.Lock())

    # ------------------------------------------------------- rendered tunes: ahead of time, and kept on disk
    def start_prewarm(self, game_root: str):
        """Render the game's tunes in the background, so the first time one plays the game does not stop
        while the synth works (about a second for each long tune). Returns the thread, or None."""
        tunes = self._game_tunes(game_root)
        if not tunes:
            return None
        t = threading.Thread(target=self._prewarm, args=(tunes,), name="khvcemu-prewarm", daemon=True)
        t.start()
        return t

    @staticmethod
    def _game_tunes(game_root: str) -> list:
        found = {}
        mod = os.path.join(game_root or "", "mod")
        try:
            for sub in sorted(os.listdir(mod)):
                d = os.path.join(mod, sub)
                if os.path.isdir(d):
                    for fn in os.listdir(d):
                        if fn.lower().endswith(".mid"):
                            found.setdefault(fn.lower(), os.path.join(d, fn))
        except OSError:
            return []
        order = [n for n in FIRST_TUNES if n in found] + sorted(n for n in found if n not in FIRST_TUNES)
        return [(n, found[n]) for n in order]

    def _prewarm(self, tunes: list):
        for name, path in tunes:
            try:
                with open(path, "rb") as f:
                    self.decode(f.read(), name)
            except Exception as e:                      # a background helper must never hurt the game
                self.emu.logv(f"[audio] could not pre-render {name}: {e}")

    def _cache_file(self, data: bytes):
        if not self.cache_dir:
            return None
        tune = hashlib.sha1(data).hexdigest()[:20]
        how = hashlib.sha1((SYNTH_VERSION + "|" + music_settings.to_text(self.music)).encode()).hexdigest()[:12]
        return os.path.join(self.cache_dir, f"{tune}-{how}.npy")

    def _render_synth(self, data: bytes) -> np.ndarray:
        """The built-in synth's rendering of a MIDI: from the disk cache if this exact tune, synth code and
        Sound tab setting was rendered before, otherwise rendered now and kept."""
        path = self._cache_file(data)
        if path:
            try:
                pcm = np.load(path, allow_pickle=False)
                if pcm.dtype == np.int16 and pcm.ndim == 1 and len(pcm):
                    try:
                        os.utime(path)                  # used just now: pruning keeps the tunes still in use
                    except OSError:
                        pass
                    return pcm
            except Exception:
                pass                                    # missing, empty or damaged (any way numpy can fail): render again
        pcm = midi_synth.render_midi(data, self.music)
        if path:
            self._store_cache(path, pcm)
        return pcm

    def _store_cache(self, path: str, pcm: np.ndarray):
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(tmp, "wb") as f:
                np.save(f, pcm, allow_pickle=False)
            os.replace(tmp, path)                       # whole file or nothing
            files = [os.path.join(self.cache_dir, n) for n in os.listdir(self.cache_dir) if n.endswith(".npy")]
            if len(files) > CACHE_KEEP:
                files.sort(key=os.path.getmtime)
                for old in files[: len(files) - CACHE_KEEP]:
                    if old != path:
                        os.remove(old)
        except OSError as e:
            self.emu.logv(f"[audio] could not keep the rendered tune ({e})")
            try:
                os.remove(tmp)                          # a full or read-only disk leaves nothing behind
            except OSError:
                pass

    @staticmethod
    def is_wonderland(name: str) -> bool:
        """The lost chapter's theme: the stand-in's splash asks the game for wonderland.mid."""
        return re.split(r"[\\/:]", name or "")[-1].lower() == "wonderland.mid"

    def _decode(self, data: bytes, name: str) -> np.ndarray:
        if data[:4] == b"MThd":
            over = self._music_file(data, name)
            stamp = self._file_stamp(over) if over is not None else None
            if over is not None and stamp not in self._file_failed:
                try:
                    return self._recording_for(data, over)
                except Exception as e:
                    self._file_failed.add(stamp)
                    self.emu.log(f"[audio] could not use {over['path']} for {name} ({e}); playing the game's music")
            if self.fluidsynth:      # a SoundFont has its own instruments: only the volume applies
                pcm = self._fluidsynth(data)
                if self.music["master"] != 1.0:
                    pcm = np.clip(pcm.astype(np.float32) * self.music["master"], -32768, 32767).astype(np.int16)
                return pcm
            return self._render_synth(data)
        if data[:4] == b"cmid":
            pcm = pmd.decode(data, RATE, ffmpeg=self.ffmpeg)
            return (pcm.astype(np.int32) * 7 // 10).astype(np.int16)   # SFX a bit under the music
        if data[:4] == b"RIFF":
            return self._wav(data)
        return self._ffmpeg(data)

    def _music_file(self, data: bytes, name: str):
        """The player's recording that replaces this tune, if one was given for its file name."""
        if not self.music_files or data[:4] != b"MThd":
            return None
        base = re.split(r"[\\/:]", name or "")[-1].lower()
        return self.music_files.get(base)

    def _recording_for(self, data: bytes, over: dict) -> np.ndarray:
        """The player's recording of a tune, fitted to the game's own MIDI. It is cut (with a
        short fade) or padded to the length the built-in synth renders the MIDI to, so
        everything the game times by the tune (when it ends, when the game restarts it to loop,
        save states) is as with the MIDI, whatever the Sound tab's sliders are. A looping tune
        is cut at the MIDI's own end, not its 0.3 s overlap tail: a recording that keeps playing
        would otherwise let the start of its next loop be heard before the game restarts it.
        A recording made from the same MIDI that starts at the same moment loops seamlessly. It
        is decoded to the game's 22.05 kHz mono. Its own gain and the Music volume apply."""
        pcm = self._ffmpeg_file(over["path"]).astype(np.float32)
        if not len(pcm):
            raise ValueError("no audio in it")
        n = self.midi_length(data)
        total = midi_synth.parse_midi(data)[1]
        if total > 6:                             # a loop (as in render_midi): stop where the music does
            n = min(n, int(total * RATE))
        out = np.zeros(n, np.float32)
        m = min(n, len(pcm))
        out[:m] = pcm[:m]
        if len(pcm) > n:                          # cut: fade the last 20 ms so it does not click
            fade = min(m, int(0.02 * RATE))
            out[m - fade:m] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
        out *= float(over.get("gain", 1.0)) * self.music["master"]
        return np.clip(out, -32768, 32767).astype(np.int16)

    @staticmethod
    def _file_stamp(over: dict):
        try:
            st = os.stat(over["path"])
            return over["path"], st.st_size, st.st_mtime_ns
        except OSError:
            return over["path"], None, None

    def midi_length(self, data: bytes) -> int:
        """Samples the built-in synth renders this MIDI to with its default settings (the
        sliders change how long a note rings, so they must not change a recording's length)."""
        key = hashlib.sha1(data).hexdigest()
        if key not in self._midi_length:
            self._midi_length[key] = len(midi_synth.render_midi(data))
        return self._midi_length[key]

    def _ffmpeg_file(self, path: str) -> np.ndarray:
        """A file on disk, read by ffmpeg itself (some formats, such as .m4a, cannot be read
        from a pipe), as mono 16-bit at RATE."""
        if not self.ffmpeg:
            raise ValueError("ffmpeg is not installed")
        r = subprocess.run([self.ffmpeg, "-nostdin", "-v", "quiet", "-i", path, "-f", "s16le", "-ac", "1",
                            "-ar", str(RATE), "pipe:1"], capture_output=True, timeout=120,
                           stdin=subprocess.DEVNULL, **no_window())
        if r.returncode or not r.stdout:
            raise ValueError("ffmpeg could not read it")
        return np.frombuffer(r.stdout, "<i2").copy()

    def _render_midi_events(self, midi_bytes: bytes) -> np.ndarray:
        return midi_synth.render_midi(midi_bytes, self.music)

    def _wav(self, data: bytes) -> np.ndarray:
        with wave.open(io.BytesIO(data)) as w:
            ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
        if sw == 1:
            a = (np.frombuffer(raw, np.uint8).astype(np.int16) - 128) << 8
        else:
            a = np.frombuffer(raw, "<i2")
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
        return resample(a, rate, RATE)

    def _ffmpeg(self, data: bytes) -> np.ndarray:
        if not self.ffmpeg:
            raise ValueError("unknown format and ffmpeg is not installed")
        r = subprocess.run([self.ffmpeg, "-v", "quiet", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                            "-ar", str(RATE), "pipe:1"], input=data, capture_output=True, timeout=30,
                           **no_window())
        if r.returncode or not r.stdout:
            raise ValueError("ffmpeg could not decode it")
        return np.frombuffer(r.stdout, "<i2").copy()

    def _fluidsynth(self, data: bytes) -> np.ndarray:
        with tempfile.TemporaryDirectory() as d:
            mid, out = os.path.join(d, "a.mid"), os.path.join(d, "a.wav")
            open(mid, "wb").write(data)
            subprocess.run([self.fluidsynth, "-ni", "-g", "0.6", "-r", str(RATE), "-F", out,
                            self.soundfont, mid], capture_output=True, timeout=60,
                           **no_window())
            return self._wav(open(out, "rb").read())

    # --------------------------------------------------------------- playback
    def play(self, data: bytes, name: str, volume: int, loops: int, on_done=None,
             start_ms: Optional[int] = None, paused_at: Optional[int] = None) -> Voice:
        """Start a voice. start_ms/paused_at resume one restored from a save
        state: playback picks up where it was, and completion still fires at
        the original time on the emulator clock."""
        pcm = self.decode(data, name)
        resumed = start_ms is not None
        v = Voice(pcm, name, volume, loops, start_ms if resumed else self.emu.clock_ms(), on_done)
        self.emu.logv(f"[audio] {'resume' if resumed else 'play'} {name} ({v.duration_ms} ms, loops={loops})")
        if self.capture is not None and not resumed:
            self.capture.append((name, pcm))
        buf, play_loops = pcm, loops
        if resumed and len(pcm):
            elapsed = (paused_at if paused_at is not None else self.emu.clock_ms()) - v.start_ms
            off = int(max(0, elapsed) * RATE / 1000)
            if loops < 0:                                   # endless: rotate the loop
                buf = np.roll(pcm, -(off % len(pcm)))
            else:                                           # rest of this pass + remaining passes
                passes_done, off = divmod(off, len(pcm))
                left = loops - passes_done
                buf = np.concatenate([pcm[off:]] + [pcm] * max(0, left)) if left >= 0 else pcm[:0]
                play_loops = 0
        if self.mixer is not None and len(buf):
            snd = self.mixer.Sound(buffer=self._device_bytes(buf))
            # volume lives on the channel only (set_volume() changes it later);
            # pygame multiplies Sound and Channel volume, so setting both would
            # apply it twice (a replay at volume 40 came out at 16%)
            v.channel = snd.play(loops=play_loops)
            if v.channel is not None:
                v.channel.set_volume(self.master_volume * max(0, min(100, volume)) / 100)
        self.voices.append(v)
        if paused_at is not None:
            v.paused_at = paused_at
            if v.channel is not None:
                v.channel.pause()
        return v

    def _device_bytes(self, pcm: np.ndarray) -> bytes:
        return device_bytes(pcm, self.out_rate, self.out_channels)

    def stop(self, v: Voice):
        v.done = True
        if v.channel is not None:
            v.channel.stop()
        if v in self.voices:
            self.voices.remove(v)

    def pause(self, v: Voice, paused: bool):
        if v.channel is not None:
            (v.channel.pause if paused else v.channel.unpause)()
        now = self.emu.clock_ms()
        if paused and v.paused_at is None:
            v.paused_at = now
        elif not paused and v.paused_at is not None:
            v.start_ms += now - v.paused_at
            v.paused_at = None

    def set_volume(self, v: Voice, volume: int):
        v.volume = volume
        if v.channel is not None and hasattr(v.channel, "set_volume"):
            v.channel.set_volume(self.master_volume * max(0, min(100, volume)) / 100)

    def stop_all(self):
        for v in list(self.voices):
            self.stop(v)

    def tick(self):
        now = self.emu.clock_ms()
        for v in list(self.voices):
            if v.done or v.paused_at is not None or v.loops < 0:
                continue
            if now - v.start_ms >= v.duration_ms * (v.loops + 1):
                v.done = True
                self.voices.remove(v)
                if v.on_done:
                    v.on_done(v)


def device_bytes(pcm: np.ndarray, out_rate: int, out_channels: int) -> bytes:
    """Mono int16 at RATE -> the mixer's real rate and channel count."""
    out = pcm if out_rate == RATE else resample(pcm, RATE, out_rate)
    if out_channels > 1:
        out = np.repeat(out, out_channels)                # interleave L R (L R ...)
    return np.ascontiguousarray(out, dtype=np.int16).tobytes()


def resample(a: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(a) == 0:
        return a.astype(np.int16)
    n = int(len(a) * dst / src)
    x = np.linspace(0, len(a) - 1, n)
    return np.interp(x, np.arange(len(a)), a.astype(np.float32)).astype(np.int16)
