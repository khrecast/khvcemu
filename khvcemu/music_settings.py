"""Adjustable settings of the built-in music synth (the launcher's Sound tab, and --music).

Every setting is a multiplier on the sound the synth was tuned to, so 1.0 everywhere is the
default sound, sample for sample. Standard library only: the launcher shows the sliders before
numpy is installed.

    python -m khvcemu <dump> --music "piano=0.8,bass_cut=1.5"
"""

from __future__ import annotations

from collections import namedtuple

Setting = namedtuple("Setting", "key label low high help")

# How loud each family of instruments is (0 = silent, 1 = as tuned, 2 = twice as loud)
VOLUMES = [
    Setting("master", "Music volume", 0.0, 2.0, "all music (sound effects are not affected)"),
    Setting("piano", "Piano", 0.0, 2.0, ""),
    Setting("strings", "Strings and choir", 0.0, 2.0, ""),
    Setting("brass", "Brass and horns", 0.0, 2.0, ""),
    Setting("harp", "Harp and guitar", 0.0, 2.0, "also koto and other plucked strings"),
    Setting("bells", "Bells and celesta", 0.0, 2.0, ""),
    Setting("winds", "Flutes and reeds", 0.0, 2.0, ""),
    Setting("pads", "Pads and organ", 0.0, 2.0, "the soft held chords"),
    Setting("bass", "Bass", 0.0, 2.0, "the bass guitar / synth bass parts"),
    Setting("drums", "Drums and timpani", 0.0, 2.0, ""),
]
# How the instruments sound
CHARACTER = [
    Setting("hammer", "Piano hammer", 0.0, 3.0, "the bright tick at the start of each piano note"),
    Setting("piano_tail", "Piano tail", 0.25, 3.0, "how long a piano note rings after the key is let go"),
    Setting("horn_length", "Horn note length", 0.25, 4.0, "short and punchy, or longer and softer"),
    Setting("bass_cut", "Bass cut", 0.0, 3.0, "how much lighter low piano and harp notes are"),
    Setting("high_soft", "High-note softening", 0.0, 2.5, "how much quieter the piano's top octave is"),
]
ALL = {s.key: s for s in VOLUMES + CHARACTER}
DEFAULTS = {k: 1.0 for k in ALL}

# Which volume slider each of the synth's voice models answers to (midi_synth._timbre)
GROUP_OF_KIND = {
    "piano": "piano", "organ": "pads", "bell": "bells", "pluck": "harp", "bass": "bass",
    "bowed": "strings", "ensemble": "strings", "choir": "strings", "brass": "brass",
    "reed": "winds", "flute": "winds", "lead": "pads", "pad": "pads", "timpani": "drums",
}


def clean(settings) -> dict:
    """Every setting, from whatever was given: unknown keys are dropped, values are clamped to
    each slider's range, and anything missing or unreadable is the default."""
    out = dict(DEFAULTS)
    for k, v in (settings or {}).items():
        s = ALL.get(k)
        if s is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v != v:                                   # NaN
            continue
        out[k] = min(s.high, max(s.low, v))
    return out


def changed(settings) -> dict:
    """Only the settings that differ from the default (what is worth saving or passing on)."""
    return {k: v for k, v in clean(settings).items() if abs(v - DEFAULTS[k]) > 1e-9}


def parse(text: str, strict: bool = True) -> dict:
    """'piano=0.8, bass_cut=1.5' -> {'piano': 0.8, 'bass_cut': 1.5}. Out-of-range values are
    clamped. strict: an unknown name or a value that is not a number raises ValueError (for
    the command line); otherwise it is skipped (for saved settings, which may come from
    another version)."""
    got = {}
    if not isinstance(text, str):
        if strict and text is not None:
            raise ValueError(f"music settings must be text, not {type(text).__name__}")
        text = ""
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, val = part.partition("=")
        key = key.strip().lower().replace("-", "_")
        if not sep or key not in ALL:
            if strict:
                raise ValueError(f"unknown music setting {part!r} (known: {', '.join(ALL)})")
            continue
        try:
            got[key] = float(val)
        except ValueError:
            if strict:
                raise ValueError(f"{key} needs a number, not {val.strip()!r}") from None
    return changed(got)


def to_text(settings) -> str:
    """The changed settings as 'key=value,...' (the --music format); '' when all are default."""
    return ",".join(f"{k}={round(v, 3):g}" for k, v in sorted(changed(settings).items()))


# Ready-made mixes for the Sound tab, in the order it lists them: only what differs from 1.0
PRESETS = {
    "As tuned": {},
    "More bass": {"bass": 1.6, "drums": 1.3, "bass_cut": 0.3},
    "Bright and crisp": {"hammer": 1.6, "high_soft": 0.6, "bells": 1.2, "piano_tail": 0.8},
    "Big brass": {"brass": 1.4, "drums": 1.3, "horn_length": 0.7},
    "Soft and warm": {"hammer": 0.4, "high_soft": 1.6, "brass": 0.8, "drums": 0.7, "pads": 1.3,
                      "piano_tail": 1.4},
    "Quiet background": {"master": 0.5},
}


def preset(name: str) -> dict:
    """Every setting for a ready-made mix (KeyError for an unknown name)."""
    return clean(PRESETS[name])


def parse_music_files(files, volumes=()) -> dict:
    """--music-file NAME=PATH and --music-file-volume NAME=GAIN (both repeatable) ->
    {name: {"path": PATH, "gain": GAIN}}. NAME is the game's tune file, e.g. training.mid.
    Raises ValueError on a malformed entry."""
    out = {}
    for item in files or ():
        name, sep, path = str(item).partition("=")
        name = name.strip().lower()
        if not sep or not name or not path.strip():
            raise ValueError(f"--music-file wants NAME=PATH, for example training.mid=title.flac, not {item!r}")
        out[name] = {"path": path.strip(), "gain": 1.0}
    for item in volumes or ():
        name, sep, val = str(item).partition("=")
        name = name.strip().lower()
        try:
            gain = float(val)
        except ValueError:
            gain = -1.0
        if not sep or name not in out or not (0.0 <= gain <= 4.0):
            raise ValueError(f"--music-file-volume wants NAME=GAIN (0 to 4) for a NAME given to --music-file, not {item!r}")
        out[name]["gain"] = gain
    return out
