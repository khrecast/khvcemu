"""khvcemu - a single-game emulator for Kingdom Hearts V CAST (Verizon, 2005).

    python -m khvcemu <dump-dir> [--start island|agrabah|castle] [options]

<dump-dir> is the folder holding mif/ and mod/ (the phone's BREW layout),
e.g. mif/11839.mif + mod/11839/kh.mod for the game and mif/14957.mif +
mod/14957/swv21brew.mod for Superscape's Swerve 3D engine.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import music_settings, swerve_patch
from .paths import default_screenshot_dir, get_launcher_option, set_launcher_option


def default_data_dir(root: str, log=None) -> str:
    from .paths import game_data_dir
    return game_data_dir(root, log=log)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="khvcemu", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump", help="folder with the game's mif/ and mod/ directories")
    ap.add_argument("--start", metavar="WORLD",
                    help="seed savegame.dat from the dump's savegame(WORLD).dat "
                         "(island, agrabah, castle), then pick Load Game")
    ap.add_argument("--scale", type=int, default=0,
                    help="window size as a multiple of the 176x220 screen (default: the largest that "
                         "fits your desktop, up to 2: the game looks best small); the window can also "
                         "be resized or maximised")
    ap.add_argument("--mute", action="store_true", help="no audio output")
    ap.add_argument("--soundfont", metavar="SF2",
                    help="render MIDI music with fluidsynth + this SoundFont instead of the built-in synth")
    ap.add_argument("--music", metavar="SETTINGS", default="",
                    help="adjust the built-in music synth, e.g. \"piano=0.8,bass_cut=1.5\" "
                         "(the launcher's Sound tab writes this; 1 = as tuned). Names: "
                         + ", ".join(music_settings.ALL))
    ap.add_argument("--music-file", metavar="NAME=PATH", action="append", default=[],
                    help="play your own recording of a tune instead of the game's MIDI, e.g. "
                         "\"training.mid=C:/music/title.flac\" (repeat for more tunes; needs ffmpeg). It is "
                         "fitted to the MIDI's length, so the game's timing is unchanged")
    ap.add_argument("--music-file-volume", metavar="NAME=GAIN", action="append", default=[],
                    help="volume for a --music-file recording, e.g. training.mid=0.8 (1 = as recorded)")
    ap.add_argument("--wonderland-volume", type=float, default=1.0, metavar="X",
                    help="volume of the Wonderland theme on the Wonderland screen, 0 to 2 (default 1)")
    ap.add_argument("--data", metavar="DIR", help="where saves/settings go (default ~/.khvcemu/<dump name>)")
    ap.add_argument("--keep-wonderland", action="store_true",
                    help="don't reroute the lost Wonderland episode to Agrabah after the Island")
    ap.add_argument("--screen", default="176x220", help="screen size WxH (default 176x220, LG VX8000)")
    ap.add_argument("--font-size", type=int, default=11,
                    help="text size in phone pixels (default 11; try 10 for smaller, 12 for bigger)")
    ap.add_argument("--font", metavar="NAME",
                    help="host font for game text (default: Verdana, else DejaVu Sans/Tahoma/Arial)")
    ap.add_argument("--filter", choices=("nearest", "smooth", "sharp", "scale2x"), default="nearest",
                    help="how the picture is enlarged: nearest (crisp pixels, the default), smooth, "
                         "sharp (crisp but even), scale2x (rounded edges); F11 cycles them in game")
    ap.add_argument("--hires-text", action="store_true",
                    help="experimental: redraw text smooth at window resolution "
                         "(default: text is drawn at the phone's 176x220 and scaled with the picture)")
    ap.add_argument("--leaderboard", metavar="URL", default="",
                    help="share high scores with a leaderboard server (see server/README.md); "
                         "scores are always kept offline too, and nothing identifying is sent")
    ap.add_argument("--dark-screen", action="store_true",
                    help="black out the rest of the screen (the monitor the game window is on) behind the window")
    ap.add_argument("--screenshots", metavar="DIR", default="",
                    help="where F12 saves screenshots (default: Pictures/khvcemu in your home folder)")
    ap.add_argument("--no-quit-prompt", action="store_true",
                    help="quit at once on Esc or the window's X, without asking \"Quit the game?\" first "
                         "(in the prompt, D = quit and don't ask again, which is saved in the launcher's settings "
                         "and then also applies to games started without the launcher)")
    ap.add_argument("--no-focus-pause", action="store_true",
                    help="keep playing when the window loses focus (by default the game pauses, and "
                         "time away is not counted as play time)")
    ap.add_argument("--no-autosave", action="store_true",
                    help="don't write autosave states at all; F8 toggles in game")
    ap.add_argument("--autosave-every", type=float, default=5.0, metavar="MINUTES",
                    help="minutes of play between timed autosaves (default 5; 0 turns the timed ones off; at most 1440)")
    ap.add_argument("--no-autosave-on-quit", action="store_true",
                    help="don't write one more autosave when the window is closed mid-game")
    ap.add_argument("--no-autosave-on-loading", action="store_true",
                    help="don't write an autosave a few seconds after each Loading screen")
    ap.add_argument("--load-state", metavar="SLOT",
                    help="resume a save state: 1-9, auto (newest autosave), auto2 or auto3")
    ap.add_argument("--no-speed-patch", nargs="?", const="all", default="", metavar="NAMES",
                    help="turn off the 3D engine speed patches (they give the same picture, faster): all of them, or "
                         "a comma separated list of: " + ", ".join(swerve_patch.NAMES) +
                         ". Write --no-speed-patch=NAMES, or put a bare --no-speed-patch after the game folder")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every BREW call category")
    args = ap.parse_args(argv)
    try:
        music = music_settings.parse(args.music)
        music_files = music_settings.parse_music_files(args.music_file, args.music_file_volume)
    except ValueError as e:
        ap.error(str(e))
    from .paths import protect_output, use_bundled_tools
    use_bundled_tools()
    protect_output()
    if args.load_state and args.start:
        ap.error("--load-state and --start can't be combined")

    from .runtime import Emulator
    from .chapters import install_save, find_save_files
    from .frontend import HELP, run_window

    if not os.path.isdir(os.path.join(args.dump, "mif")):
        ap.error(f"{args.dump} has no mif/ folder - point at the folder that contains mif/ and mod/")
    w, h = (int(x) for x in args.screen.lower().split("x"))
    notes: list = []
    data = args.data or default_data_dir(args.dump, log=notes.append)
    off = {x.strip() for x in args.no_speed_patch.split(",") if x.strip()}
    if "all" in off:
        off = set(swerve_patch.NAMES)
    unknown = off - set(swerve_patch.NAMES)
    if unknown:
        ap.error(f"--no-speed-patch: unknown patch {', '.join(sorted(unknown))} (known: {', '.join(swerve_patch.NAMES)})")
    speed_patches = [n for n in swerve_patch.NAMES if n not in off]
    emu = Emulator(args.dump, data, screen=(w, h), verbose=args.verbose, realtime=True,
                   audio=not args.mute, soundfont=args.soundfont,
                   skip_wonderland=not args.keep_wonderland, music=music, music_files=music_files,
                   wonderland_volume=args.wonderland_volume, speed_patches=speed_patches)
    emu.leaderboard_url = args.leaderboard.strip()
    emu.font_size = args.font_size
    emu.font_name = args.font
    emu.hires_text = args.hires_text
    if args.start:
        install_save(emu, args.start)
        emu.log("[khvcemu] choose 'Load Game' on the title screen to continue from that world")
    saves = find_save_files(args.dump)
    if saves and not args.start:
        emu.log(f"[khvcemu] chapter saves found: {', '.join(sorted(saves))} (use --start WORLD)")
    for note in notes:
        emu.log(note)
    from .music_preview import TUNES      # standard library only
    known = {t for t, _n in TUNES}
    for name, f in music_files.items():
        state = "" if os.path.isfile(f["path"]) else " (not found: the game's own music plays)"
        if name not in known:
            state += f" (but the game has no tune called {name}; its tunes are {', '.join(sorted(known))})"
        emu.log(f"[khvcemu] {name}: playing {f['path']} at volume {f['gain']:g} instead{state}")
    emu.log(f"[khvcemu] saves/settings in {data}")
    print(HELP, file=sys.stderr)
    if args.load_state:
        from .savestate import StateError, StateSlots
        slots = StateSlots(emu)
        try:
            slot = StateSlots.parse(args.load_state)
            path = slots.path(slot)
            if not os.path.isfile(path):
                ap.error(f"{StateSlots.label(slot)} is empty ({path})")
            emu.load_state(path)
        except (ValueError, StateError) as e:
            ap.error(str(e))
        emu.log(f"[khvcemu] resumed {StateSlots.label(slot)} from {path}")
    else:
        emu.start()
    # the launcher's saved choice (also set by D in the quit question) counts for every start
    ask_quit = not args.no_quit_prompt and get_launcher_option("ask_before_quit", True) is not False
    try:
        run_window(emu, scale=args.scale, shots_dir=args.screenshots or default_screenshot_dir(), filt=args.filter,
                   slot=slot if args.load_state and isinstance(slot, int) else 1,
                   autosave=not args.no_autosave, pause_on_focus_loss=not args.no_focus_pause,
                   autosave_minutes=args.autosave_every, autosave_on_quit=not args.no_autosave_on_quit,
                   autosave_on_loading=not args.no_autosave_on_loading,
                   dark_screen=args.dark_screen, ask_before_quit=ask_quit,
                   remember_no_quit_prompt=lambda: set_launcher_option("ask_before_quit", False))
    finally:
        emu.playtime.save()


if __name__ == "__main__":
    main()
