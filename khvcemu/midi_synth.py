"""Small General-MIDI software synth (no SoundFont needed).

Phone MIDI of this era is short, simple ring-tone style sequencing, so a
handful of additive/subtractive voices per GM family gets recognisably
close. If the `fluidsynth` CLI and a SoundFont are available, audio.py
uses those instead for much better sound.
"""

from __future__ import annotations

import struct

import numpy as np

from . import music_settings

RATE = 22050


def _vlq(d, i):
    v = 0
    while True:
        b = d[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def parse_midi(data: bytes):
    """-> (list of (time_s, ch, kind, a, b), total_seconds)."""
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    hl = struct.unpack(">I", data[4:8])[0]
    fmt, ntrk, div = struct.unpack(">HHH", data[8:14])
    pos = 8 + hl
    raw = []  # (tick, order, event)
    for t in range(ntrk):
        if data[pos:pos + 4] != b"MTrk":
            break
        ln = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        i, end = pos + 8, pos + 8 + ln
        tick, status = 0, 0
        while i < end:
            dt, i = _vlq(data, i)
            tick += dt
            b = data[i]
            if b & 0x80:
                status = b
                i += 1
            if status == 0xFF:
                mt = data[i]
                ml, i = _vlq(data, i + 1)
                if mt == 0x51 and ml == 3:
                    raw.append((tick, len(raw), ("tempo", int.from_bytes(data[i:i + 3], "big"))))
                i += ml
                if mt == 0x2F:
                    break
                continue
            if status in (0xF0, 0xF7):
                sl, i = _vlq(data, i)
                i += sl
                continue
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                a = data[i]
                i += 1
                raw.append((tick, len(raw), (kind, ch, a, 0)))
            else:
                a, b2 = data[i], data[i + 1]
                i += 2
                raw.append((tick, len(raw), (kind, ch, a, b2)))
        pos = end
    raw.sort(key=lambda e: (e[0], e[1]))
    tempo = 500000
    events = []
    last_tick, t_s = 0, 0.0
    for tick, _, ev in raw:
        if div & 0x8000:
            fps = 256 - (div >> 8)
            t_s = tick / (fps * (div & 0xFF))
        else:
            t_s += (tick - last_tick) * tempo / 1e6 / div
        last_tick = tick
        if ev[0] == "tempo":
            tempo = ev[1]
            continue
        events.append((t_s, *ev))
    return events, t_s


def _env(n, attack, decay, sustain, release_at, release):
    t = np.arange(n) / RATE
    env = np.ones(n)
    a = max(1, int(attack * RATE))
    env[:a] = np.linspace(0, 1, a, endpoint=False)[: min(a, n)]
    if decay > 0:
        env[a:] = sustain + (1 - sustain) * np.exp(-(t[a:] - attack) / decay)
    else:
        env[a:] = sustain
    r0 = int(release_at * RATE)
    if r0 < n:
        env[r0:] *= np.exp(-(t[r0:] - release_at) / max(release, 1e-3))
    return env


def _timbre(program: int) -> str:
    """Map a GM program to one of the synth's voice models."""
    if program < 8:
        return "piano"
    if program < 15 or program in (108, 112, 113, 114):
        return "bell"            # celesta, glockenspiel, vibes, tubular bells, kalimba...
    if program < 24:
        return "pluck" if program == 15 else "organ"
    if program < 32 or program in (45, 46) or 104 <= program <= 107:
        return "pluck"           # guitars, pizzicato, harp, sitar, banjo, shamisen, koto
    if program < 40:
        return "bass"
    if program < 45 or program == 110:
        return "bowed"           # solo strings, fiddle
    if program == 47:
        return "timpani"
    if program < 52:
        return "ensemble"
    if program < 55:
        return "choir"
    if program < 64:
        return "brass"           # incl. orchestra hit
    if program < 72 or program in (109, 111):
        return "reed"            # saxes, oboe, clarinet, bagpipe, shanai
    if program < 80:
        return "flute"           # flute, recorder, pan flute, shakuhachi...
    if program < 88:
        return "lead"
    if program < 104:
        return "pad"
    if program < 120:
        return "timpani"         # woodblock, taiko, melodic tom, synth drum
    return "pad"


# Piano voice, upper register. Fitted to a SoundFont render of the title tune, where the melody
# (about 700 to 1,000 Hz) is a smooth, sustained, nearly pure tone that comes forward in the mix,
# while ours clicked: the hammer tick had 10 to 14 dB more bright energy than the recording
# in the first 40 ms of every melody note. These bring the click to within about 1 dB.
PIANO_PURE = 0.3          # above 500 Hz the upper partials fade (x (500/f)^PIANO_PURE per partial): a purer tone
PIANO_STRIKE_FMAX = 2500  # the hammer tick has no partials above this many Hz
PIANO_STRIKE_REG = 1.0    # and is quieter above 500 Hz (x (500/f)^PIANO_STRIKE_REG)
PIANO_MID = 1.4           # a boost, centred on 880 Hz and fading over about an octave each way, for the melody

# Brass and timpani: the Island tune's horn stabs, fitted to a SoundFont render of it. In the
# recording the stabs have about 5 dB more low thump (the timpani under every stab) and 6 dB more
# bite above 2.4 kHz than ours had, which is what made them "punchier".
BRASS_PARTIALS = 20       # how many partials a horn note has: more gives it bite (it had 8, none above 1.5 kHz)
BRASS_TOP_DECAY = 0.85    # each partial above the eighth is this much of the one below
BRASS_BLAT = 0.45         # a short bright burst at the start of every horn note
BRASS_TILT = 0.95         # each partial is this much of the one below it (1 = no roll-off): higher is brighter
TIMPANI_GAIN = 2.0        # the low thump under the stabs
TIMPANI_DECAY = 2.0       # per second: lower rings longer

_RELEASE = {"piano": 0.35, "bell": 0.6, "pluck": 0.25, "bass": 0.12, "organ": 0.08,
            "bowed": 0.2, "ensemble": 0.3, "choir": 0.35, "brass": 0.04, "reed": 0.1,
            "flute": 0.12, "lead": 0.12, "pad": 0.6, "timpani": 0.5}
# voices that ring on their own and ignore how long the key is held
_RINGS = {"bell": 1.6, "pluck": 1.2, "timpani": 1.2}


def _harmonics(ph, freq, weights, decays=None, t=None):
    """Sum of harmonics k*ph (k from 1), skipping any above Nyquist."""
    w = np.zeros_like(ph)
    for k, a in enumerate(weights, 1):
        if a == 0 or k * freq >= RATE / 2:
            continue
        h = a * np.sin(k * ph)
        if decays is not None:
            h *= np.exp(-t * decays[k - 1])
        w += h
    return w


def _voice(program: int, freq: float, dur: float, vel: float, bend=None, s=None):
    """Render one note. dur = how long the key was held (seconds); bend =
    optional per-sample frequency multiplier (pitch bend), applied via the
    phase so slides stay smooth; s = the Sound tab's settings (music_settings),
    all 1.0 for the sound as tuned."""
    s = s or music_settings.DEFAULTS
    kind = _timbre(program)
    release = _RELEASE[kind]
    if kind == "piano":
        release *= s["piano_tail"]
    elif kind == "brass":
        release *= s["horn_length"]
    if kind in _RINGS:
        dur = max(dur, 0.05)
        n = int((min(dur, _RINGS[kind]) + release * 4) * RATE) + 1
    else:
        n = int((dur + release * 4) * RATE) + 1
    t = np.arange(n) / RATE
    mult = np.ones(n)
    if bend is not None:
        m = min(n, len(bend))
        mult[:m] = bend[:m]
        if m < n:
            mult[m:] = bend[m - 1]
    if kind in ("flute", "bowed", "ensemble", "choir", "reed"):
        # gentle delayed vibrato, like a player settling into the note
        mult = mult * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.2) / 0.3, 0, 1))
    ph = 2 * np.pi * np.cumsum(freq * mult) / RATE

    strike = None                # a short transient added after the envelope (piano hammer)
    if kind == "piano":
        # fitted to a SoundFont render of the title tune: a rounder tone (fewer upper partials)
        # that holds on after the strike, and top-octave notes that are much softer (a piano's
        # highest keys are quiet; at full strength the doubled melody pinged on every beat)
        level = 0.6 * (max(freq, 1000.0) / 1000.0) ** (-1.5 * s["high_soft"])   # 0.6: by ear, the piano led the mix
        level *= min(freq / 500.0, 1.0) ** s["bass_cut"]   # and its low notes were boomy next to the SoundFont
        if PIANO_MID != 1.0:
            level *= 1 + (PIANO_MID - 1) * max(0.0, np.cos(min(abs(np.log2(freq / 880.0)) / 1.0, 1.0) * np.pi / 2)) ** 2
        pure = min(1.0, 500.0 / freq) ** PIANO_PURE
        w = _harmonics(ph, freq, [a * (0.7 * pure) ** i for i, a in enumerate([1, 0.45, 0.25, 0.12, 0.08, 0.04])],
                       [0.8, 1.5, 2.5, 3.5, 4.5, 5.5], t) * level
        env = _env(n, 0.01, 1.2, 0.6, dur, release)
        # the hammer: a bright 20 ms tick at the start of every note. Without it a quiet chord
        # right after a loud one was lost in the ringing (the menu tune's "duh duh di" lost its
        # middle note)
        tick = [a if (k + 1) * freq <= PIANO_STRIKE_FMAX else 0 for k, a in enumerate([0.5, 0.6, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2])]
        strike = 0.5 * s["hammer"] * level * min(1.0, 500.0 / freq) ** PIANO_STRIKE_REG * _harmonics(ph, freq, tick, [60.0] * 8, t)
        strike *= np.clip(t / 0.002, 0, 1)
    elif kind == "bell":
        # inharmonic partials ring out regardless of key length
        w = (np.sin(ph) + 0.5 * np.sin(2.76 * ph) * np.exp(-t * 3)
             + 0.25 * np.sin(5.4 * ph) * np.exp(-t * 6) + 0.15 * np.sin(4.0 * ph) * np.exp(-t * 4))
        env = np.exp(-t * 2.2) * np.clip(t / 0.002, 0, 1)
        w *= 0.5                 # a chime among the others, not the loudest thing
    elif kind == "pluck":
        # bright attack, upper harmonics die first (koto, harp, guitar)
        w = _harmonics(ph, freq, [1, 0.6, 0.45, 0.3, 0.2, 0.12, 0.08, 0.05],
                       [2.0 + 2.5 * k for k in range(8)], t)
        env = np.exp(-t * 1.6) * np.clip(t / 0.002, 0, 1)
        w *= min(freq / 500.0, 1.0) ** (0.2 * s["bass_cut"])   # low harp/guitar notes a little lighter
    elif kind == "bass":
        w = _harmonics(ph, freq, [1, 0.5, 0.25, 0.12, 0.06], [1.5, 3, 5, 7, 9], t)
        env = _env(n, 0.004, 0.5, 0.35, dur, release)
    elif kind == "organ":
        w = _harmonics(ph, freq, [1, 0.5, 0.3, 0.2, 0, 0.1, 0, 0.08])
        env = _env(n, 0.01, 0, 0.9, dur, release)
    elif kind in ("bowed", "ensemble"):
        w = _harmonics(ph, freq, [1 / k for k in range(1, 9)])
        if kind == "ensemble":   # slight detuned second section for width
            w = 0.6 * w + 0.4 * _harmonics(ph * 1.004, freq, [1 / k for k in range(1, 7)])
            w *= 1.2             # section strings carry the mix; a quick bow, so stabs stay crisp
        env = _env(n, 0.08 if kind == "bowed" else 0.04, 0, 0.85, dur, release)
    elif kind == "choir":
        w = _harmonics(ph, freq, [1, 0.5, 0.6, 0.25, 0.15, 0.08])
        env = _env(n, 0.15, 0, 0.85, dur, release)
    elif kind == "brass":
        # a punchy blat that settles fast and stops short (release 0.04 s): staccato horn
        # stabs have to stand out from the strings, not trail into the next one
        base = [1, 0.75, 0.6, 0.45, 0.35, 0.25, 0.18, 0.12]
        while len(base) < BRASS_PARTIALS:
            base.append(base[-1] * BRASS_TOP_DECAY)
        w = _harmonics(ph, freq, [a * BRASS_TILT ** i for i, a in enumerate(base)])
        w *= 0.8
        env = _env(n, 0.035, 0.08 * s["horn_length"], 0.75, dur, release)
        if BRASS_BLAT:
            ramp = [min(1.0, k / 6) * 0.9 ** max(0, k - 12) for k in range(BRASS_PARTIALS)]
            strike = BRASS_BLAT * 0.8 * _harmonics(ph, freq, ramp, [45.0] * BRASS_PARTIALS, t) * np.clip(t / 0.004, 0, 1)
    elif kind == "reed":
        w = _harmonics(ph, freq, [1, 0.15, 0.55, 0.1, 0.35, 0.08, 0.2])
        env = _env(n, 0.03, 0.2, 0.8, dur, release)
    elif kind == "flute":
        rng = np.random.default_rng(program)
        breath = np.convolve(rng.standard_normal(n), np.ones(6) / 6, "same")
        w = np.sin(ph) + 0.12 * np.sin(2 * ph) + 0.04 * np.sin(3 * ph)
        w += breath * (0.06 + 0.12 * np.exp(-t * 12))   # chiff on the attack, then soft air
        env = _env(n, 0.05, 0, 0.9, dur, release)
    elif kind == "timpani":
        f = 1 + 0.08 * np.exp(-t * 30)
        ph = 2 * np.pi * np.cumsum(freq * mult * f) / RATE
        w = (np.sin(ph) + 0.3 * np.sin(1.5 * ph) * np.exp(-t * 6)) * TIMPANI_GAIN
        env = np.exp(-t * TIMPANI_DECAY) * np.clip(t / 0.003, 0, 1)
    elif kind == "pad":
        w = 0.25 * (np.sin(ph) + 0.6 * np.sin(ph * 1.005) + 0.2 * np.sin(2 * ph))   # sits under the tune
        env = _env(n, 0.25, 0, 0.8, dur, release)
    else:                        # lead
        w = _harmonics(ph, freq, [1 / k for k in range(1, 7)])
        env = _env(n, 0.01, 0.3, 0.7, dur, release)
    if kind in _RINGS:
        # a held key lets the note ring; an early release damps it
        r0 = int(max(dur, 0.05) * RATE)
        if r0 < n and kind != "bell":
            env[r0:] *= np.exp(-(t[r0:] - t[r0]) / release)
    out = w * env
    if strike is not None:
        out = out + strike
    return (out * vel * 0.6).astype(np.float32)


def _membrane(n, freq, drop, decay, noise_amt, rng):
    t = np.arange(n) / RATE
    f = freq * (1 + drop * np.exp(-t * 40))
    w = np.sin(2 * np.pi * np.cumsum(f) / RATE)
    w += noise_amt * rng.standard_normal(n) * np.exp(-t * 60)   # stick/hand slap
    return w * np.exp(-t * decay)


def _drum(note: int, vel: float):
    rng = np.random.default_rng(note)
    if note in (35, 36):                          # kick: deep body, pitch sweep, beater click
        n = int(0.4 * RATE)
        t = np.arange(n) / RATE
        f = 140 * np.exp(-t * 25) + 50
        w = np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * 8)
        w += 0.35 * rng.standard_normal(n) * np.exp(-t * 300)
        # gentle saturation adds upper harmonics, so the thump is still heard
        # on small speakers that can't play 50 Hz
        w = np.tanh(2.2 * w) / np.tanh(2.2)
        return (w * vel * 1.1).astype(np.float32)
    elif note in (38, 40):                        # snare
        n = int(0.22 * RATE)
        t = np.arange(n) / RATE
        noise = np.diff(rng.standard_normal(n), prepend=0.0) * 0.5
        w = noise * np.exp(-t * 18) + 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)
    elif note == 37:                              # side stick
        n = int(0.06 * RATE)
        t = np.arange(n) / RATE
        w = np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 80)
    elif note == 39:                              # hand clap: a few quick bursts
        n = int(0.2 * RATE)
        t = np.arange(n) / RATE
        bursts = sum(np.exp(-np.clip(t - d, 0, None) * 120) * (t >= d) for d in (0, 0.01, 0.02))
        w = np.diff(rng.standard_normal(n), prepend=0.0) * 0.4 * (bursts + np.exp(-t * 25))
    elif note in (42, 44, 46):                    # hi-hats
        n = int((0.35 if note == 46 else 0.07) * RATE)
        t = np.arange(n) / RATE
        w = np.diff(rng.standard_normal(n), prepend=0.0) * 0.35 * np.exp(-t * (9 if note == 46 else 50))
    elif note in (49, 51, 52, 55, 57, 59):        # cymbals
        n = int(1.0 * RATE)
        t = np.arange(n) / RATE
        w = np.diff(rng.standard_normal(n), prepend=0.0) * 0.3 * np.exp(-t * (2.5 if note != 51 else 5))
    elif note == 54:                              # tambourine: jingles over a short shake
        n = int(0.3 * RATE)
        t = np.arange(n) / RATE
        hiss = np.diff(np.diff(rng.standard_normal(n), prepend=0.0), prepend=0.0) * 0.18
        jingles = sum(np.sin(2 * np.pi * f * t) for f in (5200, 6900, 8100)) * 0.12
        w = (hiss + jingles * rng.uniform(0.6, 1.0, n)) * np.exp(-t * 16)
    elif note == 56:                              # cowbell
        n = int(0.3 * RATE)
        t = np.arange(n) / RATE
        w = (np.sign(np.sin(2 * np.pi * 562 * t)) + np.sign(np.sin(2 * np.pi * 845 * t))) * 0.25 * np.exp(-t * 14)
    elif note in (60, 61):                        # bongos
        n = int(0.25 * RATE)
        w = _membrane(n, 420 if note == 60 else 310, 0.15, 18, 0.25, rng)
    elif note in (62, 63, 64):                    # congas: muted high, open high, low
        n = int(0.4 * RATE)
        freq, decay = {62: (330, 35), 63: (300, 11), 64: (205, 9)}[note]
        w = _membrane(n, freq, 0.12, decay, 0.3 if note == 62 else 0.18, rng)
    elif note in (65, 66):                        # timbales
        n = int(0.4 * RATE)
        w = _membrane(n, 520 if note == 65 else 390, 0.05, 9, 0.3, rng)
    elif note in (67, 68):                        # agogo
        n = int(0.35 * RATE)
        t = np.arange(n) / RATE
        f = 900 if note == 67 else 650
        w = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.7 * t)) * np.exp(-t * 10)
    elif note in (69, 70, 82):                    # cabasa, maracas, shaker
        n = int(0.09 * RATE)
        t = np.arange(n) / RATE
        w = np.diff(rng.standard_normal(n), prepend=0.0) * 0.3 * np.exp(-t * 45)
    elif note in (75, 76, 77):                    # claves, woodblocks
        n = int(0.08 * RATE)
        t = np.arange(n) / RATE
        f = {75: 2500, 76: 1800, 77: 1300}[note]
        w = np.sin(2 * np.pi * f * t) * np.exp(-t * 60)
    else:                                         # toms / anything else: pitched membrane
        n = int(0.45 * RATE)
        f = 440.0 * 2 ** ((note - 69) / 12) * 0.5
        w = _membrane(n, max(60.0, f), 0.2, 8, 0.15, rng)
    return (w * vel * 0.8).astype(np.float32)


def _bend_curves(events):
    """Per-channel pitch bend as a list of (time_s, multiplier), honouring the
    RPN 0 bend-range message (default +/-2 semitones)."""
    rng_semi = [2.0] * 16
    rpn = [(127, 127)] * 16
    curves = {}
    for t, kind, ch, a, b in events:
        if kind == 0xB0:
            if a == 101:
                rpn[ch] = (b, rpn[ch][1])
            elif a == 100:
                rpn[ch] = (rpn[ch][0], b)
            elif a == 6 and rpn[ch] == (0, 0):
                rng_semi[ch] = float(b)
        elif kind == 0xE0:
            val = ((b << 7) | a) - 8192
            curves.setdefault(ch, []).append((t, 2 ** (val / 8192 * rng_semi[ch] / 12)))
    return curves


def _bend_for(curve, t0, n):
    """Frequency-multiplier array for a note starting at t0, n samples long."""
    if not curve:
        return None
    times = [c[0] for c in curve]
    j = int(np.searchsorted(times, t0, side="right")) - 1
    start = curve[j][1] if j >= 0 else 1.0
    out = np.full(n, start)
    t1 = t0 + n / RATE
    for t, m in curve[j + 1:]:
        if t >= t1:
            break
        out[int((t - t0) * RATE):] = m
    if np.all(out == 1.0):
        return None
    return out


def render_midi(data: bytes, settings=None) -> np.ndarray:
    """MIDI file -> mono int16 at RATE. settings: the Sound tab's sliders (music_settings);
    None means the sound as tuned."""
    s = music_settings.clean(settings)
    group = music_settings.GROUP_OF_KIND
    events, total = parse_midi(data)
    out = np.zeros(int((total + 2.5) * RATE) + 1, np.float32)
    program = [0] * 16
    vol7 = [100 / 127] * 16
    expr = [1.0] * 16
    pedal = [False] * 16
    held = {}                  # (ch, note) -> (t0, vel) while the key is down
    sustained = {}             # (ch, note) -> (t0, vel) released while the pedal is down
    bends = _bend_curves(events)

    def sound(ch, note, t0, vel, t_off):
        v = (vel / 127) * vol7[ch] * expr[ch]
        if ch == 9:
            w = _drum(note, v)
            gain = s["drums"]
        else:
            freq = 440.0 * 2 ** ((note - 69) / 12)
            dur = max(0.02, t_off - t0)
            span = int((dur + 2.5) * RATE)
            w = _voice(program[ch], freq, dur, v, _bend_for(bends.get(ch), t0, span), s)
            gain = s[group[_timbre(program[ch])]]
        if gain != 1.0:
            w = w * np.float32(gain)
        i0 = int(t0 * RATE)
        i1 = min(len(out), i0 + len(w))
        if i1 > i0:
            out[i0:i1] += w[: i1 - i0]

    for t, kind, ch, a, b in events:
        if kind == 0xC0:
            program[ch] = a
        elif kind == 0xB0:
            if a == 7:
                vol7[ch] = b / 127
            elif a == 11:
                expr[ch] = b / 127
            elif a == 64:
                pedal[ch] = b >= 64
                if not pedal[ch]:            # pedal up: release everything it held
                    for key in [k for k in sustained if k[0] == ch]:
                        t0, vel = sustained.pop(key)
                        sound(ch, key[1], t0, vel, t)
        elif kind == 0x90 and b > 0:
            for store in (held, sustained):  # re-striking a note ends the old one
                old = store.pop((ch, a), None)
                if old is not None:
                    sound(ch, a, old[0], old[1], t)
            held[(ch, a)] = (t, b)
        elif kind == 0x80 or (kind == 0x90 and b == 0):
            start = held.pop((ch, a), None)
            if start is None:
                continue
            if pedal[ch] and ch != 9:
                sustained[(ch, a)] = start
            else:
                sound(ch, a, start[0], start[1], t)
    for store in (held, sustained):           # notes never released
        for (ch, a), (t0, vel) in store.items():
            sound(ch, a, t0, vel, max(t0 + 0.1, total))
    # trim trailing silence. Music loops (the game restarts a tune when playback
    # finishes) keep only a short faded tail so the loop has no gap; short
    # jingles keep their ring-out.
    nz = np.nonzero(np.abs(out) > 1e-4)[0]
    end = (nz[-1] + 1) if len(nz) else 1
    cap = int((total + (0.3 if total > 6 else 1.5)) * RATE)
    if end > cap:
        fade0 = int(total * RATE)
        out[fade0:cap] *= np.linspace(1, 0, cap - fade0)
        end = cap
    out = out[:end]
    peak = float(np.max(np.abs(out))) if len(out) else 0
    if peak > 0:
        out *= min(1.0, 0.8 / peak) if peak > 0.8 else 1.0
        out *= 0.5
    if s["master"] != 1.0:
        out *= s["master"]
    return (np.clip(out, -1, 1) * 32767).astype(np.int16)
