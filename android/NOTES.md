# Android port: running notes

A log of what was tried, measured and decided, so no session redoes it. Newest entries first in each
section. Spike results and the first app run on the phone are in section 6 and Chunk 3.

## Status (updated 2026-10-10: chunks 1 to 7 done; the game is playable on the phone at 25 fps with sound; next is saves and the file picker)

- Toolchain installed under C:\Android (Chunk 2). The test phone is connected over adb. Spike 0 passed on it
  (section 6) and a probe APK at target SDK 36 runs Unicorn on it (Chunk 3).
- Desktop baseline measured (below). The cost is the guest's own ARM code (the Swerve renderer)
  running in Unicorn, not the Python HLE layer.
- Recommendation: keep the Python core, run it on Android with Chaquopy, Unicorn as a native library,
  Kotlin front end. Chunk 4 proved it: the core boots to the title inside the app on the phone at about 1.7 to 1.8x real time.
  Chunks 5 to 7 draw the frames, take touch input, give the game its text, images and sound and fix its frame rate; next is saves and a file picker (chunk 8).

**What comes next is planned in `android/PLAN_launcher_parity.md`** (chunks 8 to 17, with the decisions already made).

## Decisions (2026-10-09, the user's answers to the up-front questions)

- Test phone: a **Samsung Galaxy S23 Ultra** (Snapdragon 8 Gen 2 for Galaxy: 1 x 3.36 GHz Cortex-X3, 2 x 2.8 GHz
  A715, 2 x 2.8 GHz A710, 3 x 2.0 GHz A510, arm64-v8a only, 8 or 12 GB RAM depending on the unit, Android 13 at launch). It is among the fastest
  phone cores of its generation, so its numbers are a best case: a pass here does NOT mean a mid-range phone
  passes. Samsung's Auto Blocker (Settings, Security) can refuse sideloaded apps and USB installs: switch it off
  for testing if an install is refused (not verified on this phone).
- First stretch: **Spike 0 in Termux, then the toolchain** (Spike 1), the toolchain only after the Termux
  numbers are in and are marginal or better.
- The toolchain install is **approved, under `C:\Android`** (JDK 17, SDK, NDK 28.2, CMake 3.31, Gradle via the
  wrapper; section 7). Environment variables per command only. The SDK licenses are the user's to accept.
- Goal: a **playable app** (boots the game, draws it, touch controls, sound, saves, a file picker for the game
  files). Save states, the Sound tab and leaderboard sharing come after that.
- Working method: the khvcemu-workflow skill, section 10 (chunks; commits on this branch only).

## Chunk 1: Spike 0 kit (2026-10-09)

Goal: get the phone's own speed numbers with no toolchain. Files: `android/spike/make_spike_zip.py` (PC: packs
the core, the benchmark, the script and the user's game files into `build/spike/recast_spike.zip`, ignored by
git), `android/spike/termux_spike.sh` (phone: installs Termux packages, builds Unicorn for ARM from source,
runs `bench_headless.py boot`, `world`, `audio`, writes `~/spike_results.txt`).
Checked on the PC: the zip unpacks and `bench_headless.py boot` reaches the title from the unpacked folder
(1.548x, 275 frames, 0 faults). **Not run on a phone**; the script's Unicorn steps (tag `2.1.4`, `-DUNICORN_ARCH=arm`,
the binding used from the source tree with `LIBUNICORN_PATH`) come from the docs; they were untried when written and have since run on the phone (section 6).

On the phone, in order: (1) install **Termux from F-Droid or its GitHub releases** (the Play Store copy is
outdated); (2) on the PC run `python android/spike/make_spike_zip.py` and copy `build/spike/recast_spike.zip` to
the phone's Downloads (USB cable, cloud drive, or a messaging app to yourself); (3) in Termux: `termux-setup-storage`
(allow), then `cp ~/storage/downloads/recast_spike.zip ~ && cd ~ && unzip -o recast_spike.zip && cd recast_spike &&
sh android/spike/termux_spike.sh`; (4) keep the screen on, the phone cool and charged, other apps closed; takes
several minutes (the Unicorn build is the long part); (5) send back `cat ~/spike_results.txt`.
Pass/fail numbers are in section 5. The zip holds the game files: it is for that phone only, never share it.

First phone attempt (2026-10-10): stopped at step 2 with `CANNOT LINK EXECUTABLE "cmake": cannot locate symbol _ZNSt6__ndk113__hash_memoryEPKvm` (Termux had 72 packages not upgraded, so cmake and libc++ did not match). Fix: `pkg upgrade -y`, restart Termux, rerun; the script now upgrades first.

## Chunk 2: the toolchain (2026-10-10, done)

Installed under `C:\Android` (3.3 GB on disk, outside the repo; the user accepted the SDK licenses): Temurin JDK
17.0.20.1, command-line tools 23.0.0, platform-tools 37.0.1 (adb), `platforms;android-36`, `build-tools;36.0.0`,
`ndk;28.2.13676358` (clang 19.0.1), `cmake;3.31.6` (with Ninja 1.12.1). Gradle comes with the wrapper later.
Checked: `clang`, `cmake`, `ninja`, `adb`, `javac` all run; `android.jar` and `aapt2.exe` are present.
`android/env.ps1` sets JAVA_HOME, ANDROID_HOME, ANDROID_NDK_HOME and PATH for one PowerShell session
(`. .\android\env.ps1`); nothing is system-wide.
Gotcha: `sdkmanager.bat` splits a package name like `platforms;android-36` at the semicolon when given on the
command line (even quoted, from bash or PowerShell), so it reports "Package platforms not found". Use
`--package_file=<file with one package per line>`.
`adb devices` showed `emulator-5554 offline`: some Android emulator is running or was left registered on this PC
(not started by us); it is not the phone. The phone is not connected over USB yet.

## Chunk 3: Unicorn inside an app, at target SDK 36 (2026-10-10, done)

Goal: show that an APK can load Unicorn and run ARM code on the phone (the `execmem` question of section 3).

- **Test phone, as the PC sees it over adb:** SM-S918U (Galaxy S23 Ultra), Android 16 (SDK 36), SM8550, arm64-v8a
  (also armeabi-v7a), 4 KB pages, 7.2 GB RAM (the 8 GB model). The phone's serial is passed with `adb -s`: an
  offline `emulator-5554` entry is also listed, so plain `adb` commands fail with "more than one device".
- **Unicorn for Android: the NDK cross-build from Windows does not work.** Unicorn's CMake runs QEMU's own
  `configure` shell script while configuring. Without `sh` (PowerShell) the generated `config-host.h` is empty and
  the build fails (`config-target.h` missing, then `CONFIG_INT128` and `CONFIG_POSIX` undefined). With Git's `sh` on
  PATH, `configure` still stops: it guesses the host from `uname` and compile probes (a Windows host, an Android
  target) and builds test programs it then cannot run. Not pursued further. Options if a reproducible build is needed:
  a Linux build (WSL2 or Docker with the Linux NDK, or a CI job), or Termux again. For now the library is the one
  built **on the phone** in Termux (Unicorn 2.1.4, `-DUNICORN_ARCH=arm`, clang 21, SHA-256
  7CDDE399...CA72, 1,602,808 bytes). It needs only libc, libm and libdl, its segments are 16 KB aligned (so it is
  ready for 16 KB-page phones), and it carries a harmless RUNPATH into Termux's folder. It is copied to
  `C:\Android\libs\arm64-v8a\libunicorn.so` and is NOT committed; `android/fetch_unicorn.ps1` puts it into
  `app/src/main/jniLibs/` (ignored by git). Unicorn's own README and COPYING say GPLv2 (the COPYING is the plain version 2 text; no "or later" wording was
  seen), and this project is GPL-3.0: shipping it in an app is a licence point to settle before any release (the
  desktop installers already ship it).
- **The project (`android/`):** Gradle 9.6.0 wrapper, Android Gradle Plugin 9.4.1, compile/target SDK 36, min SDK 26,
  NDK 28.2.13676358, CMake 3.31.6, arm64-v8a only, Java 17. `app/src/main/cpp/unicorn_probe.c` loads
  `libunicorn.so` with `dlopen`, runs `mov r0,#6; mov r1,#7; mul r0,r0,r1` and a 65,536-iteration loop, and the
  activity shows the result and logs it (tag `recast`). Debug APK 894 KB without the library, 2,339,135 bytes (2.3 MB) with it (measured).
- **Result on the phone (`adb install`, then `am start`):** `Unicorn 2.1 loaded. ARM 6 x 7 = 42 (expected 42): PASS.
  Loop 65536 iterations in 0.3 ms: PASS` (that loop is 196,608 guest instructions, so the translator is running;
  the figure is only an order of magnitude, one run). **No `avc:` lines at all** in `adb logcat -d` after `adb logcat -c`, a
  force-stop and a fresh launch (checked twice; 1,892 log lines the second time): on this phone, an app at target
  SDK 36 on Android 16 can use Unicorn's JIT. That answers the `execmem` question of section 3 for this one
  device and Android version; other makers' phones and versions are untested.
- **Gotchas found:** a PowerShell script that writes `"No $Source: ..."` fails to parse (`$Source:` reads as a
  drive); use `${Source}`. The first APK was built without the library because that script had failed silently
  inside a larger command: check that `jniLibs` exists before building.
- Not done: an x86_64 build for the emulator (no x86_64 Unicorn library yet); 16 KB-page device or emulator test;
  Python (Chaquopy) inside the app, the next chunk.

## Chunk 4: the Python core inside the app (2026-10-10, done)

Goal: boot the unmodified `khvcemu/` core to the title screen inside the APK, on the phone, with the real stack
(Chaquopy, its numpy, the NDK app, native Unicorn).

- **Versions:** Chaquopy 17.0.0 (its changelog lists Android Gradle Plugin 9.0 to 9.2, so the project went down from
  AGP 9.4.1 to **9.2.1**; Gradle 9.6.0 is fine), Python **3.12.12**, **numpy 1.26.2** (Chaquopy's own wheel; the core
  needs numpy >= 1.22). Python 3.13 and 3.14 have few wheels; numpy 2.x has no Android wheel (section 3).
- **Build Python:** Chaquopy needs a Python 3.12 on the PC to fetch packages. Gradle did not find the `py` launcher, so
  the path is given on the command line and kept out of the repo:
  `.\gradlew.bat assembleDebug --no-daemon "-Precast.buildPython=<path to a Python 3.12 python.exe>"`.
  Order of a clean build: `. .\android\env.ps1`, `.\android\fetch_unicorn.ps1`, then the Gradle command.
- **How the code gets in:** a Gradle copy task (`stagePython`) stages the repository's `khvcemu/` package and
  `android/spike/bench_headless.py` into `app/build/python-stage` (no duplicate in git, audio recordings excluded);
  `fetch_unicorn.ps1` also copies Unicorn's pure-Python binding into `app/src/main/python/unicorn/` (ignored by git);
  `extractPackages("unicorn", "khvcemu")` unpacks both at startup; `useLegacyPackaging = true` installs
  `libunicorn.so` as a real file (the binding loads it by path). `app/src/main/python/recast_app.py` is the app's own
  glue: it runs `bench_headless.py <mode>` and returns its output (also copied to logcat as it is produced).
- **Two things that had to be worked around:** (1) the Unicorn binding calls `importlib.resources.files("unicorn")`
  and wraps it in `pathlib.Path`, which fails on Chaquopy's `AssetPath`; `recast_app._prepare_unicorn` answers
  that one question with a real folder (the vendored binding is not edited). (2) Gradle needs the explicit dependency
  from Chaquopy's `*PythonSources` tasks on `stagePython`.
- **Game files** go into the app's private storage only: `adb push` mif/, mod/ and `savegame(island).dat` to
  `/data/local/tmp/recast_game`, then `adb shell "run-as com.khrecast.recast sh -c 'mkdir -p files/game; cp -r
  /data/local/tmp/recast_game/. files/game/'"` (the debug APK allows `run-as`), then delete the temporary folder.
  The files are never in the repo or the APK. If a run stalls for 40 s the app writes the Python thread stacks to
  `files/stall_<mode>.txt` (read with `run-as`; an empty file means no stall).
- **The stall that was not a bug:** an early run sat idle at 0% CPU for minutes. The phone's screen was off and
  locked, the activity was stopped (`WindowStopped`, display state dozing), and Android froze the backgrounded app.
  Keep the phone unlocked with the screen on (Developer options, Stay awake) while a benchmark runs. A real player
  keeps the game in the foreground; pausing when the screen turns off is the right behavior and must be designed in.

Results (first run), Galaxy S23 Ultra, Android 16, same device and benchmark as Spike 0:

| Measure | In the app (Chaquopy, Python 3.12, numpy 1.26.2) | Termux (Python 3.14, numpy 2.4.4) | Pass bar |
| --- | --- | --- | --- |
| Boot to title | 1.80x real time (6.1 s for 11 s of game; 1.73x on a second run), 0 faults | 1.39x | >= 1.0x |
| 3D scene, loading (scene a) | 1.004x | 0.876x | |
| 3D scene, steady (scene b) | 1.058x (37.8 ms per frame, 26 fps capacity) | 0.92x | >= 0.6x |
| Nine tunes rendered | 6.4 s (peak 204 MB process RSS) | 12.0 s | < 60 s |
| Memory after the run | 164.7 MB PSS in total (45 MB of it the window's graphics buffers) | | < 300 MB |
| Debug APK | 26.9 MB (26,923,466 bytes): Python, numpy, Unicorn, the core | | < 60 MB |
| Python start | 0.3 to 2 s | | |

A second run of the final build (after the stall-file fix) gave boot 1.73x, loading scene 0.85x, steady 3D 1.04x,
tunes 6.4 s (peak RSS 190 MB) and the same two frame fingerprints: the loading scene varies by about 15 percent
from run to run, the others by a few percent.
The frame fingerprints equal Termux's (boot `250a782cb28866d9`, 3D scene `a138121676d59659`): the same pixels
on a different Python, numpy and packaging. That is evidence the core behaves identically here, within what these
two scenes exercise. The app is faster than Termux most likely because of Python 3.12 against 3.14 and
Chaquopy's builds (not investigated). `ResourceWarning: unclosed file` lines appear for the core's `open(...).read()`
calls: harmless, but Chaquopy turns warnings on.

Not done (next chunks): the picture is not drawn (the benchmark runs headless), no touch input, no sound, no saves or
file picker, no pause on leaving the app; heat over a long session; the Agrabah lava scene; an x86_64 build for an
emulator; a 16 KB-page device (Chaquopy 17 supports them, but this numpy wheel may not load there: use Python 3.13
if needed); a release build and signing; the Unicorn library still comes from Termux.

## Chunk 5: the game on screen, touch controls, pause (2026-10-10, done; text and images are the next chunk)

Goal: play the real game in real time on the phone: see the picture, press keys by touch, hold the game still when the
app leaves the foreground.

- **Python side (`recast_app.py`):** `start_game` builds an `Emulator` (real-time clock, audio off) and runs the same loop
  as the desktop front end, in a reduced form, on a thread: `emu.start()`, then `run_due()` and a short sleep until the
  next timer. It ends when the game asks to exit (`emu.exit_requested`) or the app is closed for good; it has no autosave,
  no Wonderland pages (`skip_wonderland` is on, so the stand-in is probably not reached) and no quit prompt.
  Small calls for the Java side: `frame_count()`, `frame_bytes()` (the 176x220 RGB565 frame, little endian: the format
  of Android's RGB_565 bitmap), `key(name, down)` (names from `khvcemu.keys.AVK`), `pause()`, `resume()`, `status()`.
  Pausing is done by the core's own thread, like the desktop's focus-loss pause: it lets go of every key and shifts the
  game clock (`emu._t0`) by the time held.
- **Android side:** `MainActivity` (the game; the old speed spike is `BenchActivity`, started with `adb shell am start -n
  com.khrecast.recast/.BenchActivity`), `GameView` (draws the frame with nearest-pixel scaling, and the controls),
  a frame-pump thread polling `frame_count()`, a single input thread for key calls. Portrait only. The controls: a
  direction pad (diagonals work), Action (SELECT), Magic (STAR), Status (0), the two softkeys and Back (CLR); several
  fingers at once. `onPause` releases all keys and pauses the core; `onResume` resumes it.
- **Seen on the phone** (screenshots taken with `adb shell screencap`; they show the game's art, so they are not kept
  in the repo): the title screen is drawn (Sora, the logo, the yellow menu frames), the menu highlight moves when the
  Down button is tapped, Action starts a new game and the intro page appears. Status line: `running frames 248 faults 0`.
- **Pause, checked from the core's log:** `paused ... game clock 11179 ms`, then 8.1 s later `resumed after 8.1 s; game
  clock 11179 ms`: no game time was lost. Leaving the app 1 s after launch, while the game was still starting, also
  paused it (`game clock 281 ms`, resumed 12.2 s later with the clock unchanged). The foreground flag is applied through
  the single input thread and read when each task runs, so the last state wins.
- **When the game ends:** if the game asks to exit, the core loop ends and the app closes; a crash of the core stays
  on screen in the status line (`ERROR ...`). Reopening the app starts a fresh core (after waiting up to 5 s for a core that was told to stop). Key events come from the input
  thread while the core thread runs: they only append to the core's event list and its held-key set, which is fine
  under the interpreter lock, but it is new compared with the single-threaded desktop front end.
- **What was missing in chunk 5, fixed in chunk 6:** every word and every host-decoded image was blank. The core asks pygame to
  draw text (`display.py`) and to decode the game's PNG/BMP images (`image.py`), and there is no pygame on Android:
  the log fills with `[image] decode failed: No module named 'pygame'`. So the menu entries have no labels, and the
  intro page is a white screen with an empty softkey bar. The picture the game draws itself (the 3D, its sprites)
  is fine. The fix is a host backend for text and images behind the core (pygame stays the default on the desktop),
  e.g. Pillow with a bundled free font, or Android's own drawing through Java; that touches `khvcemu/` and needs the
  full desktop test suite.
- **Checked only with `adb shell input tap`:** single taps on the pad and Action. Multi-finger play, diagonals and how
  the controls feel under real thumbs are unverified.
- **Not done (text and images were fixed in chunk 6):** sound, save states and game saves (the data folder `files/data` is used, but
  there is no way to see or back it up), the file picker for the game files, landscape, the lava scene, heat.
  The status line is drawn at the very bottom, over the area of the navigation bar (cosmetic).

## Chunk 6: the game's text and images on the phone (2026-10-10, done)

Goal: give the core what pygame gives it on the desktop (it draws the game's text and decodes its images) without
pygame. This changed `khvcemu/`: the desktop path is untouched, the new code runs only where `import pygame` fails.

- **New module `khvcemu/hostgfx.py`:** `decode_image(raw)` (Pillow: PNG and BMP to the core's RGB565 plus an alpha mask),
  and `load_font(names, size, bold)` returning a `PilFont` with the few font methods the core uses (`get_ascent`,
  `get_descent`, `size`) plus `mask(text)`, the text as a 1-bit coverage array (glyphs not anti-aliased, like
  pygame's `render(text, False, ...)`). Fonts come from system folders by family name; on Android that is
  `/system/fonts/DroidSans.ttf` (and `DroidSans-Bold.ttf`), then Roboto and Noto Sans.
- **Three small hooks, each only on `ImportError`:** `image.decode_image`, `Display._font` and `Display.DrawText`
  (`display.py`; hi-res text overlay returns nothing without pygame), and the save-state thumbnail (`savestate.py`,
  Pillow writes the PNG). `Display._font` used to swallow the missing pygame and return "no font", which is why text
  silently never appeared.
- **Tests (`tests/test_hostgfx.py`, 9, skipped without Pillow or pygame):** the Pillow decoder equals the pygame
  decoder on synthetic RGBA, RGB, transparent-palette and BMP images and on all 6 of the game's own PNGs (colors
  where visible, alpha everywhere); the font gives sensible metrics and masks; the core picks the Pillow font and the
  Pillow decoder when `import pygame` is made to fail.
- **App:** `pip { install("Pillow==11.0.0") }` (Chaquopy's arm64 wheel for Python 3.12). Debug APK now 39.5 MB
  (was 26.9 MB): 39,470,460 bytes, still under the 60 MB bar.
- **Seen on the phone:** the title menu shows New Game, Load Game, Options, Score, Quit; New Game shows Jiminy's journal page
  with his picture and the story text and a Continue softkey. Faults 0. The text is DroidSans where the desktop uses
  Verdana: letter shapes and line breaks differ from the desktop's (the number of journal pages can differ too).
- **Not done:** sound; save states and game saves are not reachable (no menu for them); the file picker for the game
  files; the Wonderland lost-media pages (`lostmedia.py`, pygame) are not wired, so after the Island the stand-in's
  pages would fail (untested: the Island has not been played to its end on the phone); landscape; settings screen;
  smooth hi-res text; the hi-res Pillow path; heat; a slower phone.

## Chunk 7: sound, and the frame rate (2026-10-10, done)

Goal: sound on the phone, and find out why the game ran at 10 fps with the CPU nearly idle.

- **Sound:** the core mixes through a pygame.mixer look-alike it did not have before, `khvcemu/pcmmixer.py`
  (`PcmMixer`: `Sound(buffer=...)`, `play(loops)`, per-channel volume/pause/stop, and `read(frames)` which the host
  pulls). `AudioEngine` and `Emulator` take it as an optional argument (`mixer=`, `audio_mixer=`); pygame.mixer stays
  the default. The app (`recast_app.audio_read`, `MainActivity.pumpSound`) feeds an `AudioTrack` (22,050 Hz, mono,
  16-bit, USAGE_GAME) with blocks of 1,024 frames; it stops while the app is in the background and the mixer is held
  with the game clock. The tunes are rendered in the background by the core's own prewarm thread.
  Tests: `tests/test_pcmmixer.py` (13: playing once, loops, forever, volume, clipping, pause, stop, the channel limit,
  the engine playing a WAV through it). **Measured, not heard** (nobody can listen from here): Python hands out audible
  samples (loudest 4,400 to 5,300 of 32,767 while the title tune plays) and Android's `AudioTrack` counted 0 underruns
  over more than 800 blocks (about 37 s) and again over a later 3D session. Whether it sounds right through the phone's
  speaker is the user's to listen to.
- **Why 10 fps (found with a profile on the phone, then reproduced on the desktop):** the game re-arms its frame timer
  at the END of each frame (`SetTimer(30..40 ms)` as its last act), so on a real clock the time a frame takes is added to
  the delay: frame period = work + 30 ms. The phone's title screen: about 33 ms of work + 30 = 63 ms, 10 to 16 fps
  although the CPU was only 63% busy. The virtual-clock benchmarks never saw this: guest code takes no virtual time
  there, the game sees 0 ms elapsed and asks for exactly 40 ms (25 fps). **The desktop has the same effect:** its title
  screen in real-time play ran at 16.1 fps (median interval 62 ms) on a PC that can do 33.
  Raising the core thread's priority made no difference (tried, removed).
- **The fix, `Emulator(frame_locked_clock=True)`:** while a callback into the game runs, the clock the game sees is held
  still (as the virtual clock already does), and it runs in real time between callbacks. The frame period is then
  max(40 ms, work time). Safe for this game because the virtual-clock runs, which the whole test suite and the
  benchmarks use, are exactly this behavior and never hang on a clock inside a callback. Off by default; the app turns
  it on. Tests: `tests/test_frame_pacing.py` (6 unit tests with a hand-moved clock, and one that runs the real title
  screen for 14 s and expects a 40 ms median interval).
  Results: **desktop title screen 16.1 fps -> 24.6 fps; Galaxy S23 Ultra title screen 10 -> 25 fps**, journal page
  18 to 19 -> 25, and the 3D Obstacle Course (Sora walking, sound on) a steady 25 fps with 0 faults and 0 underruns.
  **Decided 2026-10-10: the desktop uses it too, on by default** (`--no-frame-lock` and a switch in the launcher's
  Speed enhancements window turn it off). Real-time desktop frames per second, without and with it (speed-ups on):
  title 15.8 to 24.6, Obstacle Course 15.5 to 24.6, Castle room 16.6 to 24.9, fight 11.2 to 18.5, lava cave 11.9 to
  19.0; with the speed-ups off: Obstacle Course 15.3 to 24.7, fight 9.8 to 16.3, lava cave 11.2 to 17.2
  (`tools/bench_realtime.py`; an earlier version of the tool called the Obstacle Course scene "island", because its
  Load Game keypresses did not land in real time and the game started a New Game: the numbers were the course's).
  **The game's speed does not depend on the frame rate** (measured): walking forward in the Obstacle Course for 6 s of
  real time at 24.7 fps (steady clock), 14.5 fps (steady clock, plus 35 ms of delay per frame) and 15.7 fps (old clock)
  ends in the same place: the final pictures differ in 0.1 to 0.6% of pixels, against 54% from the start picture.
  Play time is unaffected: the clock loses no time, it only holds still during a frame, and the pause logic changes
  the clock's origin outside any callback. Not yet checked on the phone with the clock off in 3D (the title and the
  intro pages were: 10 and 18 to 19 fps before, 25 after). Two limits to remember then: `GetTimeMS` and
  `GetSeconds` (time of day) use the wall clock and are not frozen (the 25 fps result says the game does not time
  its frames with them), and `load_state` must not run from inside a game callback while the clock is frozen (it
  resets the clock, and the game would keep seeing the old value until the callback ended; no such path exists today).
- **Text drawing cost:** `PilFont.mask` now caches the rendered mask per string (a screen redraws the same strings every
  frame); the journal page went from 18 to 19 fps to 25 with the pacing fix and the cache together.
- **Diagnostics left in:** the status line shows fps; `files/profile_flag` (create it with `run-as`) makes the core
  thread profile itself from 20 to 35 s after the start and print the busiest functions to logcat; the sound pump logs
  its loudest sample and the `AudioTrack` underrun count every ~5 s.
- **Played on the phone through `adb shell input` taps and long presses:** title menu, New Game, Jiminy's journal pages
  (the left softkey is Continue; Action does nothing there), the in-game pause screen, and walking in the Obstacle
  Course. Not played: a full session, fighting, saving, the later worlds, heat over time.
- **Not done:** save states and the game's own saves are not reachable from the UI; the file picker for the game files;
  the Wonderland lost-media pages (`lostmedia.py`, pygame); landscape; a settings screen; smooth hi-res text;
  mute and volume controls (the phone's own volume keys work); a release build and signing.

## Chunk 8: controls inside the safe area, and tapping the game's own buttons (2026-10-10, done)

- **Layout** (`GameView.java`): reads the window insets, keeps the pad, buttons and status line inside the safe area
  (above the navigation bar), and caps the picture at 60% of the free height so the controls stay on screen. The Action,
  Magic and Status buttons keep the earlier size, are spaced so they do not touch, and hit-test as circles. Checked on the
  S23 Ultra (screenshots in `C:\Android\shots`, outside the repo).
- **Tapping the picture** (`khvcemu/tapmap.py`, core, pure and tested): a tap on the game's picture becomes keys. A label in
  a bottom corner is a softkey (Soft 1 left, Soft 2 right), only where the game drew a label. A run of at least three
  strings at a regular spacing is a menu: the highlighted entry is the one whose text color and background differ, tapping
  another entry sends Up or Down as many times as needed, tapping the highlighted one sends Action. Anything unclear
  (a paragraph, a list of two) does nothing rather than guess.
- **Plumbing:** `MainActivity` passes a short, still touch to `recast_app.tap(x, y)` in game pixels; the core thread
  resolves it against `Display.text_items` (`_Game._handle_taps`) and presses the keys 0.16 s apart. The log line is
  `[core] tap (x, y) -> keys`.
- **Verified on the phone (adb taps):** title menu (two taps on Options open it; "Help" sent Down x3), Options, the right
  "Back" bar returned to the title. Not tried by hand with a finger; shops and the Save screens not tried.
- Tests: `tests/test_tapmap.py` (11, one against the real game's title, intro, pause and Options screens).

## Chunk 9: the first-run flow, game files without adb (2026-10-10, done)

- `SetupActivity` is now the app's front door: it explains what is needed, opens Android's folder picker
  (`ACTION_OPEN_DOCUMENT_TREE`), and when the game files are installed it goes straight on to the game. "Remove the game
  files" deletes the copy (saves and settings are kept). Open it with the game installed from adb:
  `adb shell am start -n com.khrecast.recast/.SetupActivity --ez auto false`.
- `GameInstaller` looks for the folder holding `mif` and `mod` (the picked folder or up to 3 levels below it), copies
  `mif/`, `mod/` and any `savegame(*).dat` next to them through `ContentResolver` into `files/game_new`, runs
  `khvcemu/gamefiles.py` (`problems`, tested on the desktop) on the copy, then swaps it in as `files/game` and writes the
  marker `files/game/.installed`. A wrong folder leaves nothing behind and names what is wrong. Off the main thread.
- `MainActivity` sends you to Setup when there are no game files (a copy made with adb before this chunk still plays).
- Verified on the S23 Ultra through the real picker: from no game files, a wrong folder ("This is not the game folder: it
  has no mif and mod folders inside"), then the folder one level above the game: copied, checked, "The game files are
  installed", Play ran at 23 to 26 fps with 0 faults; Remove deleted the copy.
- Hardening after review: names from the picker that could leave the folder (`..`, a path, a NUL, empty) are skipped; the
  old copy is kept as `game_old` until the new one is in place and the marker is written, then restored if that fails;
  `.mif`/`.mod`/`.sig` file names are lower-cased (the module scan is case-sensitive); the Setup screen survives
  dark-mode and language changes mid-copy (`configChanges`).
- **Setup can only be reopened with adb once the game is installed** (the command above), until chunk 10's home screen
  adds the route. "Remove the game files" runs on the main thread (a few MB: fine for now).
- Android 11+ will not let an app pick the root or the Download folder itself ("Can't use this folder"), only folders
  inside them; the screen says so. There is no progress bar yet (a text line counts files); that comes with the Compose
  screens in chunk 10. Not tried: a very large folder, a phone with an SD card, a picker other than Samsung's.

## Chunk 10, part 1: the app icon (2026-10-10, done; the rest of chunk 10 is not started)

- The launcher icon is the Re:Cast heart (`khvcemu/assets/recast_icon.png`) on dark navy, as an adaptive icon (heart in the
  middle 56%, so no mask clips it): `res/mipmap-*/ic_launcher_foreground.png` (made with Pillow at the five densities),
  `mipmap-anydpi-v26/ic_launcher.xml`, `values/ic_launcher_background.xml`. The app label was already "Re:Cast".
  Checked in the built APK (`aapt2 dump badging`: label Re:Cast, adaptive icon) and as a rendered preview; not looked at
  on the phone's own launcher. APK 39.5 MB, unchanged.
- **Held back: the Home screen, the shared settings module and Compose.** A Home screen has nothing to show until saves
  and options exist, so saves (chunk 11) come first, and the screens stay plain `View`s for now (no Compose: it would add to
  the APK for no gain yet; revisit when there are enough screens to justify it). The settings JSON and the move of the
  option defaults out of `launcher.py` touch the desktop launcher, so they wait for chunk 12 where the options are used.

## The app icon, slightly pixelated, thinner line, taller (2026-10-12, built and installed; not looked at on the phone's launcher)

- **The owner's requests, in order:** "rough up the icon logo a little, make it slightly pixelated"; then "too rough, slightly pixelated, not missing pieces" (the random edge nudges looked like
  missing pieces: removed); then "make the heart a little thinner and slightly longer", clarified as "the line thinner, and the size taller". `android/tools/make_icon_pixelated.py [cells] [rough]` (new; the first icon
  was made with an unsaved script) now **draws the heart itself** from the same outline formula as the window icon (`tools/make_icon.py`: the heart curve with a smaller one cut out), so the line's thickness and the height can be set:
  `INNER` 0.70 (the hole's size against the heart's; the window icon has 0.52, so a bigger hole is a thinner line), `DROP` -0.75 (the hole sits a little below the middle, which makes the line even all round
  instead of thick at the bottom and thin at the lobes) and `STRETCH` 1.12 (taller for its width; it was 1.25, which the owner found too tall: "squish it down a bit, centered on the icon"). It is cut into **40 cells across**, each heart or not (hard edges), the gradient is six flat color bands
  (light top-left to deep bottom-right), no random nudges and no edge pixels (both remain options: a `rough` share such as 0.07, and `edges=True`). Written to `res/mipmap-*/ic_launcher_foreground.png` at the five densities
  (heart 52 percent of the canvas wide and about 51 percent tall, centered by its visible shape to within half a pixel at all five sizes (an empty grid row under the thin tip had left it a few pixels high), inside the adaptive icon's 66 percent safe zone; cells about 5.5 px at xxxhdpi, scaled with hard edges); the background color is unchanged.
- **Only the app's launcher icon.** The desktop window icon and installer icon (`recast_icon.png`/`.ico`), the Re:Cast logo picture on the Home screen and the website are unchanged.

## Chunk 11: saves (2026-10-10, done in part; the Saves screen is plain, export and import are not done)

- **The game's menu.** The system Back button or the back swipe opens it (Android 13+ through
  `OnBackInvokedCallback`, because the old `onBackPressed` is not called at target SDK 36; older phones keep
  `onBackPressed`). Items: Resume, Quick save (slot 1), Quick load (slot 1), Save to a slot, Load a saved game, Game
  files (the Setup screen), Quit and go to the Re:Cast menu. The game and its sound are held while the menu is up.
- **Core** (`recast_app.py`, on the core thread): `request_state(op, slot)` runs `StateSlots.save/load`; the clock is held
  while a file is written (as `frontend.py` does); a failed save or load says "Failed: ..." and never ends the game.
  Autosaves follow the desktop's rules (every 5 min of play, a few seconds after a loading screen, one more on quit),
  and only when something was played since the last save or load. New: one autosave when the app goes to the
  background (not for the menu), at most every 30 s, so a killed app keeps the session.
- **Saves screen** (`SavesActivity`): slots 1 to 9 and the three autosaves with the picture and date from the same
  `.khs` and `.png` files the desktop writes; tap to save or load (asks before replacing), press and hold to delete.
  There is no world name yet (it is not in the file header).
- **Verified on the S23 Ultra:** quick save at the title, move to Options, quick load: back at the title. Home press
  wrote an autosave; the app was force-stopped; reopened, "The autosave" was listed with its picture and loaded
  (Options screen). **A state made on the phone loads on the desktop** (0 faults, ran 1 s after). **A state made on the
  desktop loads on the phone** (the highlight on Load Game as saved, 25 fps, 0 faults), after one fix: the desktop's
  numpy 2 writes `numpy._core` names that numpy 1.26 on the phone does not have; `savestate._CompatUnpickler` now maps
  them, and an unreadable state raises `StateError` instead of killing the game (core change, test in
  `tests/test_savestate_compat.py`).
- **Known limit:** Home pressed while the Saves or Setup screen is in front leaves the game held without an autosave
  (the game screen gets no callback then); the autosave from opening the menu and the timed ones still apply.
- **Not done:** "Start at world" (with the backup of the current save), export and import of saves to the Downloads
  folder, the autosave switches (chunk 12's Options), a Continue card (chunk 10's Home), a state made with the speed
  patches on loaded with them off (and the reverse), a long play session, the thumbnail's world name.

## Chunk 12, part 1: Options (picture size, mute, autosave switches) (2026-10-10, done in part)

- **Options screen** (`OptionsActivity`, from the game's menu; `Settings.java` keeps the choices in SharedPreferences
  "recast"; every change is saved at once and the game picks it up when it resumes): **Picture size** (Fit the screen,
  default; Sharp = the largest whole-number scale that fits; or exactly 6x, 5x ... 1x, with 1x the original 176 x 220
  pixels), **Mute the game** (the core keeps running; the app writes silence), **Autosave** (master switch, at loading
  screens, when leaving the game, and every 0/2/5/10/15 minutes of play), and Restore the default settings.
- **Core:** `recast_app.configure(autosave, minutes, on_loading, on_quit)` sets the `StateSlots` fields.
- **Picture size in `GameView`:** whole-number sizes are clamped to what fits (60% of the free height, the full width), the
  picture is centered, the controls take the room that is left, and taps use the picture's actual rectangle.
- **Verified on the S23 Ultra:** the screen opens from the menu; 1x shows the picture at 176 x 220 pixels; Sharp gave 5x
  (880 x 1100); Fit was restored; the settings file holds the choice. **Not verified:** mute (nobody here can hear), the
  autosave switches changing behavior or the minutes-to-milliseconds conversion in `configure` (read and checked, not exercised on the phone), the other whole-number sizes, landscape.
- **Not done in chunk 12:** picture filters (smooth, Scale2x), text size and hi-res text, screenshots, "Back button asks
  before quitting", sharing scores (and the INTERNET permission), the Speed enhancements window and its frame lock, the
  Sound tab (chunk 13). The settings are not yet in one JSON file shared with the desktop launcher (chunk 10).

## Chunk 14, part 1: landscape (2026-10-10, done; the controls editor and game controllers are not started)

- **Layout** (`GameView.layoutLandscape`, used when the view is wider than tall): the picture in the middle at the full
  height (93% of the free height, so the status line fits under it; the Options picture sizes apply), the pad with Soft 1
  and Back at its left, Soft 2, Action, Magic and Status at its right, all inside the system-bar insets. The same
  `dst` rectangle serves taps and drawing.
- **Orientation:** the activities no longer lock portrait: they follow the phone's auto-rotate setting. `MainActivity` and
  `SetupActivity` handle orientation changes themselves (`configChanges`), so turning the phone does not restart the game.
- **Verified on the S23 Ultra** (rotation forced with `settings put system user_rotation`, then put back to auto-rotate on
  and portrait): the game runs at 25 fps in landscape, a tap on the picture's Options entry sends Down, Down, then Select and
  opens the game's Options menu, and rotating back to portrait restores the portrait layout with the game running.
- Also: `MainActivity` now handles `uiMode`, `locale`, `density`, `fontScale` and `layoutDirection` changes itself (a
  dark-mode or font-size change used to recreate it and would have started a second game); the Saves and Options
  screens are recreated on rotation (their state is in the intent and in Settings, so nothing is lost; an open confirm
  dialog closes); the Options size list is based on the narrow side of the screen.
- **Not verified:** the in-game menu, Saves, Options and Setup screens in landscape (plain scrolling views, so they should
  work), a phone with a camera cutout on the side, the reverse landscape (rotation 3), tablets, the 1x and whole-number
  sizes in landscape, a finger instead of adb taps.
- **Not done:** the controls editor (move and resize the pad and buttons), game controllers.

## Chunk 10, part 2: the home screen (2026-10-10, done; the shared settings JSON and Compose are not done)

- **`HomeActivity` is the launcher screen.** With game files installed: a Continue card (the picture, slot name and date of
  the newest save, autosaves included; one tap loads it and starts the game), "Play from the title screen", "Saved games",
  "Options", "Game files", and a line saying that Back opens the game's menu. Without game files it asks for them and
  offers "Set up the game files". Plain `View`s, no Compose (see the part 1 note).
- **`SaveSlots` reads the save slots in Java** (file names, the `.png`, and the date from the state's own JSON header), so
  the home screen and the Saves screen work without starting the game or Python. The Python `states_json` and
  `delete_state` were removed. Saves and Home share the slot names the core takes ("1".."9", "auto", "auto2", "auto3").
- **Loading from Home:** `MainActivity` takes an extra (`HomeActivity.EXTRA_LOAD`) and queues the load as soon as the game is
  up. "Quit and go to the Re:Cast menu" in the game's menu returns to Home.
- **Setup changed:** it is opened from Home or the game's menu, no longer forwards to the game by itself, finishes (back to
  Home) after a successful install, and has "Done" instead of "Play".
- **Verified on the S23 Ultra:** Home shows the Continue card for the real autosave left by playing earlier today (the
  Obstacle Course); tapping it loaded that autosave into the game at 25 fps; "Quit and go to the Re:Cast menu" returned to Home; Game files,
  Remove, Home asking for the files, picking the folder again, and Home coming back with the Continue card (the saves
  survive removing the game files).
- After review: the load request is removed from the intent once queued (a recreated activity must not load it again);
  the Continue card loads the newest save at the moment of the tap; the game's own stop flag is set synchronously when
  the game screen closes; "Game files" was taken out of the in-game menu (replacing the files under a running game is
  not safe), it lives on Home only. Known: the Continue card can briefly show the previous newest save right after a quit,
  until the exit autosave lands; the card's date comes from the state file's own header.
- Second review: `recast_app.start_game` returns a session number and `stop(session)` only stops that game, so a late
  `onDestroy` of a closed game screen cannot end the game that replaced it; Quit also stops the game at once instead of
  waiting for `onDestroy`. Known and left: a very fast Continue can pick an older slot before the exit autosave lands;
  the load request can repeat if Android kills and restores the whole process.
- The home screen shows the project logo (`khvcemu/assets/recast_logo_lowres_hardpixels.png`, wordmark included) instead of the
  heart icon and a text title. `android/app/src/main/res/drawable-nodpi/recast_logo.png` is a byte copy of it (a test,
  `tests/test_android_assets.py`, fails if the two drift apart); its height is capped (30% of the screen, at most 260 dp) so
  landscape still shows the buttons. Seen on the phone in portrait; landscape not looked at.
- **Not done:** the shared settings JSON for the desktop launcher and the app, Compose, a "Start at world" entry, a world
  name on the card, a progress bar while the files are copied, the home screen in landscape (it scrolls; not looked at).

## Chunk 11, part 2: export and import of state files (2026-10-10, written and built, NOT exercised on the phone)

- **Saved games screen:** an "Import a state file..." button (Android's file picker) copies a `.khs` into slot 1 to 9, which
  the player chooses (filled slots say "replace"); the file is checked first (the `KHVCEMU\x01` magic and a sane header
  length) and written through a temporary file. A press and hold on a filled slot now offers **Export to a file...** (Android's
  "create file" picker; the name defaults to `recast_slotN.khs`) and Delete.
- **Same format as the desktop,** so a state moves both ways between the PC's `states` folder and the phone. A state made with
  other game files, other speed patches or another screen size is refused by the game when loaded, with its message.
- After review: Import is offered only when the Saved games screen is opened from Home (the running game owns the
  slots), the copy is made once into a temporary file, capped at 256 MB, checked there and moved over the slot with
  `Files.move(REPLACE_EXISTING)` (the temporary file is deleted on any failure), export truncates (`"wt"`), the slot chosen for
  export survives the screen being recreated, and the desktop's older `KHEMUSS` state files are refused.
- **Why not tested:** the pickers list the phone's Download and Recent files, which are personal, so they were not driven
  through screenshots. The copy code is plain stream copying and the magic check is the one `Home` already uses for dates.
  Worth one manual try: export a slot, import it into another, load it.
- **Not done:** the game's own saves (the in-game Save / Load Game files), "Start at world", exporting all slots at once.

## The opening notice (2026-10-10, done)

- **`DisclaimerActivity` is what the app opens on, every time:** the logo, the same notice as the desktop launcher and the
  website (an unofficial, free, non-profit fan project; the rights belong to their holders; not affiliated with Disney,
  Square Enix, Superscape, Verizon, Qualcomm; never to be sold), a line that the app contains no game files and the player
  brings their own copy, and an "I understand" button that goes on to the home screen (and finishes, so Back from Home
  leaves the app). Back on the notice leaves the app.
- **One wording in four places:** `tests.test_units.DisclaimerTests` now also checks that `DisclaimerActivity.java` holds
  `DISCLAIMER` from `khvcemu/launcher.py` exactly (the website test already did for the launcher).
- Shown on every launch (a cold start of the app); when Android restores the app after killing it, the screen that was
  open comes back instead, without the notice. Seen on the S23 Ultra in portrait; landscape and the "I understand" tap
  were exercised, the notice in landscape was not looked at.

## The menu font on the app's menus (2026-10-10, done)

- The Home screen's buttons and Continue card, the screen headings (Options, Saved games, Game files) and the notice's
  "I understand" button are small pictures of their names in the KHMenu font, the same look as the desktop launcher's tab
  names. `tools/make_tab_labels.py` draws them (it now also writes `khvcemu/assets/menu/*.png`, and copies each to
  `android/app/src/main/res/drawable-nodpi/menu_*.png`); the font file itself stays out of the repository, as before, and
  `tests/test_android_assets.py` fails if the Android copies drift from the originals. Televo's credit (README,
  `docs/CREDITS.md`) now says the app's menu names too; the website's credit said so too once the app was public (2026-11-02).
- `Labels.java` scales a label by a whole number (about 20 to 26 dp tall) with no smoothing, so the pixels stay crisp; a
  picture button is a normal Button with the picture on top (the button is raised, so the picture has a higher elevation).
- **Buttons restyled (same day):** the picture labels are bigger (a whole-number scale of 3, about 30 dp tall, up from 2) and
  the buttons use the launcher's palette and the logo's blue: the main button is a bright blue gradient with a silver
  outline (like the selected tab), the others dark navy with a blue-silver outline, all brighter while pressed
  (`Labels.buttonBackground`); the Continue card has the same outlined panel; the plain text buttons on the Game files,
  Saved games and Options screens got the same look (`Labels.theme`). The Home logo is capped (20% of the screen height) so
  all four buttons and the hint fit on the S23's screen without scrolling. Seen on the S23 Ultra in portrait only.
- **Still plain text:** the in-game menu (a system list dialog), the text on the Setup, Saves and Options screens and the
  toggles (the buttons on those screens are themed but show text, not pictures). Seen on the S23 Ultra in portrait only.

## Screenshots (2026-10-10, done)

- **"Take a screenshot" in the game's menu** saves the game's current picture as a PNG: the game's own 176 x 220 pixels
  enlarged four times with hard edges (704 x 880), named `Re-Cast_<date>_<time>.png`, into the phone's gallery under
  `Pictures/Re-Cast` through MediaStore (no permission needed on Android 10 and later; on older phones into the app's own
  Pictures folder, which the gallery does not show). The folder is "Re-Cast" because Android folder names cannot hold a colon (the macOS app has the same
  spelling). A toast says where it went. `Screenshots.java`, `GameView.snapshot()`.
- **Verified on the S23 Ultra:** one screenshot taken at the title screen: the file landed in `Pictures/Re-Cast` as 704 x 880
  with crisp pixels. The test picture was deleted afterwards. Not done: a list of screenshots inside the app with preview,
  share and delete (the gallery does that), a screenshot button on the controls, the hi-res text overlay in the picture.

## Start at a world (2026-10-10, done)

- **Home has "Start at a world"** when the game folder came with starting saves (`savegame(world).dat`, which the folder
  picker copies next to `mif` and `mod`). It lists the worlds that have one (Swashbuckler's Island, Agrabah, Maleficent's
  Castle on this phone's files; the files spell the castle "maleficient", which is mapped as on the desktop), asks the same
  question as the desktop ("this replaces your current game save with the starting save, then choose Load Game; your current
  save is backed up first") and starts the game with the world seeded.
- **Core:** `recast_app.start_game(..., start_world)` calls the desktop's `chapters.install_save` before the game starts, so
  the backup rules are the desktop's (a real save with progress is copied into `save_backups`, a stock one is not).
- Home now puts Options and Game files side by side so five rows still fit on the S23's screen.
- Known and left (rare, logged only, no message to the player): if "Start at a world" is chosen while an earlier game is still
  running or closing, or the seeding fails, the game starts with the old save. One-time requests (this and Continue) are
  applied only on a fresh start of the game screen, not after Android restores it.
- **Verified on the S23 Ultra:** the list, the confirmation, and Start at Agrabah: the log says `savegame.dat seeded from
  savegame(agrabah).dat (world: agrabah)` and the file then held `0101agrabah`; the game ran at 25 fps. There was no earlier
  game save on the phone, so the backup path was not exercised here (it is the desktop's code, tested there). The test
  save was deleted again afterwards. Not tried: choosing Load Game after it (the same game code as the desktop).

## Speed switches, and the button shape (2026-10-10, done)

- **Options has a Speed section:** Steady frame rate, Faster blended fill (`span`) and Matrix cache (`matinv`), all on by
  default, each with a short explanation (the launcher's Speed enhancements window, in the app's words). They are read when
  the game starts (`Settings.speedOff`, `Settings.frameLock` into `recast_app.start_game(..., speed_off, frame_lock)` and
  `Emulator(speed_patches=..., frame_locked_clock=...)`), so a change applies the next time the game is started from Home (a game still alive in the background keeps the
  old values; the core logs that).
  **Verified on the S23 Ultra:** with the steady frame rate off (and the matrix cache off) the title screen ran at 12 fps
  instead of 25; the settings were put back afterwards. The speed patches' own effect was not measured separately.
- **Action, Magic and Status** keep the sizes and positions the layout was designed with; Magic and Status are slid along
  their own line to Action's centre until each just touches Action, so the three read as one group like a round head with two
  ears (`GameView.placeButtons`). An earlier try that moved the ears to 45 and 60 degrees was dropped: the player liked the
  original size and angle and wanted only the touching.

## The Sound screen: mixes and sliders (2026-10-10, done in part)

- **Options > "Music mix and sliders..."** opens `SoundActivity`: a Mix picker (the six ready-made mixes of
  `khvcemu/music_settings.PRESETS`, plus Custom) and the 15 sliders of the launcher's Sound tab (how loud each family is, and
  how the piano, horns and bass sound), with a reset to "as tuned". `SoundSettings.java` mirrors the module's sliders, ranges and
  mixes, and `tests/test_android_assets.py` fails if they ever differ from the Python (checked by breaking one value).
  The choice is stored as the module's own text (`piano=0.8,bass_cut=1.5`, `Settings.music`), passed to
  `recast_app.start_game(..., music)` and parsed by `music_settings.parse(strict=False)` into `Emulator(music=...)`.
- **Heard the next time the game starts.** Fixed on the way: a slider has finite steps, so 1.0 could come back as 1.005 and a
  chosen mix was re-saved slightly off; a chosen mix is now saved as written, values within one step of 1.0 snap to 1.0,
  and the sliders have 600 steps.
- **Verified on the S23 Ultra:** the screen opens, shows "As tuned" with every slider at 1.00; choosing "More bass" moved
  Bass to 1.60, Drums to 1.30 and Bass cut to 0.30 and saved exactly `bass=1.6,drums=1.3,bass_cut=0.3`; starting the game then
  made a second set of music files in `audio_cache` (the setting is part of the cache key) and the game ran at 25 fps with
  sound being produced. **Not heard** (nobody here can), and the time to make the music on the phone was not measured.
- **Not done:** saved custom mixes with favorites, the tune player and its comparison with a recording, "use a recording
  in the game" (needs a decoder for FLAC and MP3 without ffmpeg: Android's `MediaCodec`), the SoundFont option and clearing the
  music cache.

## The Sound screen plays the tunes (2026-10-10, done; sound not heard)

- **"Try the music" at the top of the Sound screen:** a list of the game's nine tunes (`SoundSettings.TUNES`, the launcher's list; a
  test keeps it equal to `music_preview.TUNES`) and a Play / Stop button. Play asks Python for the tune made with the saved
  slider text (`recast_app.render_tune`: `music_preview.tune_path` finds the file in the game's `mod` folder, `midi_synth.render_midi`
  makes it, mono 16-bit at 22,050 Hz) on a worker thread, and plays it in a loop with a static `AudioTrack`. Moving a slider or picking
  a mix makes it again 0.7 s after the last change; picking another tune changes over; leaving the screen stops it.
- **Verified on the S23 Ultra:** Play on the title tune said "Playing" within about two seconds, and the system listed an AudioTrack
  of the app (22,050 Hz, mono, usage game, started, not muted); dragging the Piano slider to 1.60 showed "Making the music..." and the
  Mix list changed to Custom; Stop said "Stopped." and no started track was left. **Not heard** (nobody here can), the render times
  were not measured (only that the title tune was ready in about two seconds), and the other tunes were not tried on the phone.
  Rendering `keyblade.mid` took 0.4 s on the desktop.
- **One tune is made at a time** (a change that arrives meanwhile makes it again afterwards). Python is shared with the game, so a
  game running behind (the Sound screen can be opened from the game's menu) may run slower while a tune is made; not measured.
- **Still not done here:** the comparison with a recording and "use a recording in the game" (a decoder for FLAC and MP3).

## Recordings, favorite mixes and clearing the music (2026-10-11, done; sound not heard)

- **A recording per tune (Sound screen, "A recording of this tune"):** Choose a file (the system picker; a copy is kept in the app's
  `files/recordings`, since the picker gives access only once), Remove it, **Play the recording** (to compare with the built-in
  version, same loop player), a recording volume 0 to 400 percent, **Match its loudness** (`recast_app.match_gain`, the launcher's
  `MusicPreview.match_gain`: aims at the built-in tune's level, never below the floor of 3000 RMS) and **Use the recording in the
  game**. Choosing a file also matches its level once. The game gets the ones with the switch on as JSON
  (`Settings.musicFilesJson` -> `start_game(..., music_files)` -> `Emulator(music_files=...)`): the core's existing replacement (cut or
  padded to the MIDI's length, with a short fade; the Music volume and the recording volume apply, the sliders do not).
- **The decoder:** `RecordingDecoder.java` reads FLAC, MP3, AAC/M4A, OGG and WAV with Android's own `MediaExtractor`/`MediaCodec` to mono 16-bit at
  22,050 Hz (linear resampling with a little smoothing) into a `.22050.pcm` file next to the recording, kept until the recording changes.
  The core reads it through the new `audio.FILE_DECODER` hook (commit `5b7f456`; used only when there is no ffmpeg).
- **Limits and care:** a recording longer than ten minutes is cut there when decoded; a decode that gets no answer from the codec for
  about five seconds gives up; two decodes of one file take turns; a new file is copied beside the old one, test-decoded, and only then
  takes its place (a file that cannot be read leaves the old recording as it was); moving a Mix slider does not restart a playing
  recording. "Restore the default settings" keeps the chosen recordings (they are the player's own files), like the mixes and stars.
- **Favorite mixes:** "Star this mix" / "Unstar" for any mix (a star shows in the list; the order does not change); "Rename this mix..."
  for the player's own; both are kept by "Restore the default settings". **Clear the made music** deletes the music the game made and kept
  (`files/data/audio_cache`, shown in MB) after asking.
- **Verified on the S23 Ultra:** a 1.7 MB FLAC (the reference "Obstacle Course" recording, copied into the app's folder by adb) decoded to
  64.6 s of samples; Play the recording started an AudioTrack (listed as started by the system); Match loudness set 337 percent; with
  "Use in game" on, the game started and its audio showed a different peak (about 6,400 against 5,200 for the built-in tune) with no
  "could not use" line. **A bug the test found:** the class and its methods had to be `public` for Python to see them (the game had quietly
  played the built-in tune). Star / Unstar and the star in the list, and Clear the made music (6.6 MB to none, after asking), also worked.
- **Not tried:** the system file picker itself (the copy step after it: only reached by adb in this test), renaming a mix, a recording in MP3 or M4A, the
  game's timing with a recording over a long play, and nothing could be heard.
- **Not possible here:** a SoundFont. It needs `fluidsynth`, a program that does not run inside an app; the built-in synth and recordings
  are the two ways to change the sound on the phone.

## The menu font on the rest of the app (2026-10-11, done; seen on the S23)

- **What changed:** the section headings and the buttons that always say the same thing are now pictures in the KHMenu font (Televo's, via
  `tools/make_tab_labels.py`, which now makes 46 app labels; the font file itself stays in the gitignored `reference/`): the Options and
  Sound headings, the first-run question (its title and both choices), Options' four buttons, the Saves import button, and on the
  Sound screen Play / Stop, Play / Stop the recording, Choose a file, Remove it, Match its loudness, Save / Delete / Rename / Star / Unstar this
  mix, Reset (the sliders back to as tuned), and Clear the made music (with "No made music is kept" when there is none; the size is in
  the note under it). A button that changes what it says swaps its picture (`Labels.setFace`); a greyed button dims its picture
  (`Labels.enable`); `Labels.heading` is the heading. The font has no usable "..." (it draws an underscore), so those labels lost their dots.
- **Left as plain text on purpose:** switches and radio buttons (the system draws them), the notes, the mix and tune lists, slider names,
  dialogs, the Setup screen's buttons and the text that changes with the player's data (a recording's name, a mix name).
- **Verified on the S23 Ultra:** the question screen, the Options screen top to bottom, and the Sound screen (headings, greyed and
  active picture buttons, Play changing to Stop and back). **Not looked at:** the Saves import button, the Setup screen, landscape.

## Sharp text (2026-10-11, done; seen on the S23)

- **Options > "Sharp text"** (off by default; applies at the next game start). The core already remembers every string the game draws on the
  screen (`Display._record_text`, `build_overlay`, used by the desktop's high-resolution text); with it on, `recast_app.frame_bytes()` hands
  the app the picture with those glyphs taken out and `frame_text()` the strings (JSON: text, font id, where, the size it took, RGB565
  color, the box that shows), both from the same overlay. `GameView` draws each string again at the screen's scale with the phone's font
  (bold for the game's bold and large fonts), stretched to the box the game gave it (kept to its own shape when the phone's font
  differs by more than a quarter), clipped to the visible box. A string the game paints over falls back to the plain picture, as on the desktop.
- **Verified on the S23 Ultra:** with it on, the title menu and the game's Options screen show crisp text over the pixel picture, the
  strings follow changes (Sound Medium to High to Off and back to Medium) with no ghost of the old text, 25 fps and no faults.
  **Not tried:** in-world dialogue and menus, the flip phone layout, and the screenshot with text on.
- **Screenshots** with sharp text on are taken at four times the size with the text drawn on them (`GameView.snapshot`).
- **No core change.** Not done: the Wonderland pages and the Re:Cast pages (they are pictures), the flip phone layout draws through the same code and was not looked at.

## Nicer touch controls, and button names that follow the game (2026-10-11, done; the Action words Open, Attack, Grab and Talk seen on the S23)

- **Look (`ControlSkin.java`):** round glass-like buttons with a bright rim, a soft shadow and a highlight (Action blue, Magic violet, Status gold),
  a d-pad on a dark disc with a cross and arrows, and navy softkey pills; a held control brightens and glows (a controller's presses light them
  too). Their names are menu-font pictures (`c_*` labels from `tools/make_tab_labels.py`), fitted to the control. The gradients are made once
  and moved with a matrix, so no Java objects are made while drawing. The flip phone has its own look and is unchanged.
- **Button names follow the game:** Options > Controls > "Button names follow the game" (on by default; applies at the next game start). The
  core's remembered strings (as for sharp text, which is not needed) at the bottom of the game's screen name the keys: a string whose box
  starts at game row 195 or lower (the real softkey words are drawn at row 199; the title menu's own "Quit" entry starts near 190 and was wrongly taken for a softkey word before), in the left 45 percent of the width, is Soft 1's word, in the right 45 percent Soft 2's. They are drawn on
  the pills in the system font; with no word there, the pill stays blank. The picture is sent unchanged unless Sharp text is also on (the core still remembers the strings every frame, the same work as for sharp text). Only short words (14 characters or fewer, in a box under 45 percent of the width) count.
- **Action says what it will do (checked with a temporary log of the strings the game draws, played by the owner):** the game slides a text
  banner in at the top of its screen ("Open" at a chest, "Attack" at an enemy, "Grab"; the y of the string runs from about minus 12 to 2 as it
  slides). `GameView.actionWord()` takes a single word of 3 to 10 letters drawn at y from minus 19 to 8 (the banner slides in from about minus 11 and rests at 6, its box ending at row 20), whose visible box ends within the top 22 rows (the other banners, "Munny = 11",
  "Game Saved", "Obtained Gem 1 of 4", have digits or spaces) on the action banner's pink or red background (the owner says the information banners are yellow; a log showed the text itself is dark on all of
  them: maroon (41, 4, 32) for the action words on a salmon-pink banner (255, 141, 123), brown (115, 64, 0) for Munny, blue (0, 76, 123) for the level-up lines; `recast_app._items_json` sends the
  median color behind each string): red at least 140 and green at most 70 percent of red and the Action button shows it instead of "Action": a menu-font picture for
  Open, Attack, Grab, Jump, Talk, Interact and Use (the first three were seen, the rest are guesses), the system font for any other word. When the banner
  goes, the button says Action again. A banner for Jump was not seen (it may not exist). The option is now called "Button names follow the game". **Seen on the S23 (owner's play):** Open, Attack, Grab and Talk (Talk at the parrot) show on the Action button while the banner is up
  and it goes back afterwards; yellow banners (Munny) do not change it. The banner rests at y 6 (a first version that stopped at y 4 lost it after
  a second). With no banner the button reads "Action/" up and to the left and "Jump" just below and to the right, since the key jumps then (the
  owner's request); the banner-word pictures are drawn with one extra pixel between letters because the font draws l and k touching.
  Not tried: a pink or red word on other screens, the system-font fallback for an unknown word, Jump or Interact banners (not seen yet).
- **Verified on the S23 Ultra:** the new look at rest and with Action held; the title screen showed Quit on the right pill, and the opening
  dialogue showed Continue on the left. **Not tried:** the other screens' words (Select, Back and so on), the pills with Sharp text on,
  landscape, and Magic or Status held.

## Softkey words in the menu font, and bigger controls sideways (2026-10-11, done; seen on the S23)

- **Menu font for the softkey words:** the words the game puts on its softkeys ("Save", "Shop", "Continue"...) were drawn in the phone's system
  font on the pills. They now use the menu font: `tools/make_tab_labels.py` also makes `khvcemu/assets/menu/font_atlas.png` (76 characters, bright
  silver like the labels; the letters, digits and `.,:;!?'-/+&%()`) and `font_atlas.txt` (the picture's height, then each character's cell start
  and width), copied to `res/drawable-nodpi/menu_font_atlas.png` and `res/raw/menu_font_atlas.txt` (the menu-label test keeps the picture's copy equal, another test the text file's, and checks the cells lie inside the picture and do not overlap). `MenuFont.java` draws any text from it, a whole-number scale with hard edges when that is nearly exact and
  smoothed otherwise, and says so when it lacks a letter for any character of a word (then the whole word is drawn in the system font as before). The Action button's fallback for an
  unknown banner word uses it too. Seen on the S23: "Continue" on the left pill in the menu font.
- **Sideways (landscape) buttons:** the Action, Magic and Status cluster is now a tighter "mouse head" (Magic and Status about 37 degrees either side
  of straight up from Action, all touching) so the buttons can be larger: the size is `min(0.255 x the right side's width, 0.285 x the free height)`
  against `min(0.2 x width, 0.27 x height)` before, so about a quarter bigger on the S23 Ultra (a cluster 3.7 `big` wide and 3.4 `big` tall, where Action's radius is 1.15 `big`). Seen on the S23 in landscape (the cluster fits beside the picture); the controls editor
  still moves and resizes them as before.

## Switching between flip phone and smartphone in the game menu, and more colors (2026-10-11, done; seen on the S23)

- **The in-game menu (Back) starts with "Switch to flip phone mode" or "Switch to smartphone mode"** (whichever is not on). Choosing flip phone
  closes the menu and opens a **Flip phone** pop-up over the game, which stays held: the body color (a list) and "Small bezel (a bigger
  picture)". Both apply at once; "Done" closes it and the game goes on. In landscape the pop-up says the flip phone shows when the phone is upright.
  Smartphone mode switches back without a pop-up. The menu always has the same ten items in the same places. The second one depends on the mode: **"Move the controls"** on the smartphone look (the flip phone has fixed keys, so it is not there) and **"Flip phone color and bezel..."** in flip phone mode (the same pop-up, without leaving the mode, so colors can be tried one after another). "Move the controls" no longer sits near the bottom. In the flip phone the old "turn it off in Options to move the controls" toast is gone, since the item is not offered. The item follows the mode setting, not the screen's turn: with flip phone mode on and the phone sideways (where the usual controls show), Move the controls is not offered either; switch to smartphone mode first. Seen on the S23: ten items in both modes; in flip phone mode the second opens the pop-up (colors changed live); after switching to smartphone mode it reads Move the controls. The other menu items moved down one place; the code uses their position.
- **Colors (`Settings.FLIP_COLORS`, `FlipPhone.setColor`):** Silver, Graphite, Sky blue, Rose pink and Champagne gold. The three new ones tint the
  silver's light and shade between a dark and a light end of the color (`TINT_DARK`, `TINT_LIGHT`), so the shell, hinge, ring and keys all follow; Call
  and End stay green and red, and the screen's frame stays dark. A throwaway Python mock-up of the five bodies (not kept) looked right; the app was only built.
  The color is stored as `flip_color` (an older build's `flip_graphite` is read as Graphite until a color is chosen). The same list is in Options
  ("Flip phone color", replacing the Graphite switch) and in the first-run question.
- **Two more colors (same day):** **Red**, a deep cherry red like the glossy red LG Chocolate, a Verizon V CAST phone (the owner's reference picture; the
  keys are red too, with pale pink print), and **Re:Cast blue**, a deep blue close to the logo's. Both are dark bodies like Graphite (`dark()`: pale key print
  and arrows, `FlipPhone.dark()` and `pale()`). The list is now Silver, Graphite, Sky blue, Rose pink, Champagne gold, Red, Re:Cast blue; judged only
  from a Python mock-up, not on the phone.
- **Verified on the S23 Ultra:** the menu's first item ("Switch to flip phone mode"), the Flip phone pop-up over the held game ("paused 0 fps" behind it)
  with the seven colors and the small bezel box; choosing Rose pink and the small bezel changed the phone live, Done resumed the game at 25 fps, and the
  settings were stored (`flip_color` 3, `flip_small_bezel`); Red and Re:Cast blue were also drawn on the real phone and look right (End stands out on Red).
  The Red follows the owner's reference photo of a red LG phone.
- **Not tried:** switching back to smartphone mode from the menu, the other colors on the phone (Silver, Graphite, Sky blue, Champagne gold seen only as mock-ups
  or earlier), the old setting's migration. The rest of the earlier list: the menu item, the pop-up's look and its live changes, the new colors on the real shape (End is a brighter orange-red on the Red body so it stands out), the held state of
  the game behind the pop-up, and the migration of an old setting.

## Restoring the defaults no longer asks about sharing scores again (2026-10-11)

- "Restore the default settings" wiped the answer to the sharing question, so the game asked again at its next start. It now keeps the question answered
  and sets sharing to off (the default). If the player was never asked, they still are asked once. The first-run style answer was already kept.
  (The repeated questions the owner saw were mostly from the developer's test runs resetting the app's settings on the phone, not from the app.)

## The game's sound effects (2026-10-11, done; the owner heard them)

- **The bug:** the sword, jump and hit sounds (the game's ".pmd" effects, CMX files holding QCELP speech-codec audio) were silent on the phone: the core
  decodes QCELP with ffmpeg, which the phone does not have, and logged "PMD sound effects need ffmpeg" (found by a temporary log of every sound the game
  started: music and jingles played, every effect failed). The owner noticed "missing sound during fight".
- **The fix:** `pmd.QCELP_DECODER` (a hook in the core, used only when there is no ffmpeg; tests in `tests/test_music_mixes.py`) is filled on the phone by
  `QcelpDecoder.java`, which feeds the packets to the phone's own QCELP decoder (`MediaCodec` "audio/qcelp"; Samsung phones have `c2.sec.qcelp.decoder`).
  `recast_app._qcelp_with_android` passes the packets through a temporary file. The log then showed the effects decoding with real lengths (swipe 320 ms,
  jump 140 ms, enemy hit 500 ms), and the owner confirmed they are heard.
- **A later failure, found while the owner heard silence ("sound is still not working sometimes"):** the log showed `could not decode sora_jump.pmd: could not write
  .../p.pcm`, and no sound after it. `QcelpDecoder.decode` deleted its `.part` file in a `finally` that ran before the rename, so the rename failed whenever the decode
  was otherwise fine. It now renames inside the `try` once the streams are closed and deletes the file only after a failure. After the fix a jump made sound (peak
  about 6,000 in the log, no error). Not found: whether the earlier "first start of `sora_hit` with no channel" was the same fault (it probably was).
- **Limits:** `QcelpDecoder.available()` is checked when the game starts (the hook is only set if the phone has the decoder); a phone without one still has no effects (nothing else is decoded for
  it; a pure-Python QCELP decoder would be the answer, not written). One first start of `sora_hit.pmd` showed no mixer channel (it played afterwards);
  not explained.

## Two-thumb controls (2026-10-11, built; seen on the S23, not played with; this is layout B now, and its "on by default" and `Settings.twoThumb` below are superseded by "Three control layouts")

- **Why (the owner's idea):** the game was made for a phone keypad, played with two thumbs (forward and back with one, turning with the other). On the
  smartphone look one thumb on a d-pad has to steer and move, so a precise diagonal is needed and you can end up running in circles; the flip phone
  keypad does not have that problem. "Two-thumb controls" (Options > Controls, now on by default, smartphone look only) splits the d-pad.
- **Layout (the owner's choice: Magic and Status to the left, Action stays on the right):** left column, Magic and Status side by side with the **forward
  and back** keys (two stacked keys) under them; right column, Action with the **turn left and turn right** keys (side by side) under it. Four separate
  keys, so there are no diagonals to aim for and both thumbs can hold at once. They send the same Up, Down, Left and Right keys as the d-pad.
- **Moving and resizing:** each of the four arrow keys is a control of its own (groups 0 forward, 7 back, 8 turn left, 9 turn right; see below), moved and resized in the
  controls editor like the other groups. The two-thumb layout keeps its own saved places (`ctl2_port3_*`, `ctl2_land3_*`, `ctlscale_..._*`), apart from the
  normal layout's; "Put the controls back" clears both. `Settings.controlOffset`/`controlScale` and their setters take a `twoThumb` flag now.
- **The default (the owner's own arrangement, from a screenshot they sent):** two-thumb movement is now on by default (`Settings.twoThumb` defaults to true;
  "Restore the default settings" and a fresh install give it), and in portrait its keys start where the owner put them: the forward and back keys stacked at the
  left, Magic in the middle column with Status small under it, Action at the right with the turn keys under it, pulled a little up and left. These are
  the `TWO_THUMB_PORTRAIT` offsets and scales in `Settings.java`, worked out from the screenshot with the layout's own arithmetic (it reproduced the picture and the softkeys
  to 2 px); a control the player moved keeps their place, and "Put the controls back" returns to this. Sideways has no built-in arrangement yet (the owner sent
  only the portrait one). After the owner said the screenshot was only the rough position and size, the numbers were tidied (up to about 40 px of movement): the forward/back and turn pairs share a bottom edge, Magic and Status
  share a column, Status is level with the turn keys, Action is centered over them and the side margins match; Status is exactly its default size. The exact saved values on the phone were not read (it was disconnected): they may differ by a few pixels. **Effects:** an existing install that never touched the switch moves from the d-pad to
  two-thumb on update (the app is unreleased, so this is only the owner's phone); a player who moved only some groups keeps those and gets the built-in places for the rest; the
  numbers are fractions of the S23 Ultra's size, so other screen shapes may have a control pulled in a little by the keep-inside-the-screen rule (not tried).
- **Each arrow is its own control (the owner's request):** the four arrow keys are groups 0 (forward), 7 (back), 8 (turn left) and 9 (turn right), each moved and resized
  alone in the editor (ten groups now); the two pairs of the first version are gone. Their saved places moved to a new name (`port3`/`land3`), so the places saved with the pairs
  are not read; the built-in default gives each key the place it has in the owner's tidied arrangement (worked out from the old pair offsets with the pair scaling, so the
  look is the same). Seen on the S23: each arrow has its own dashed box in the editor, dragging the Up key moved only the Up key, Action reads Enter on the title menu,
  and the phone's own saved values for the old layout (read from `ctl2_port2_*`) matched the numbers worked out from the screenshot to within 0.0006 of the screen's size.
- **Bigger, and a switch in the editor (the owner's next request):** all the two-thumb buttons are 18 percent bigger than first built (Magic, Status, Action and the
  four arrow keys). In "Move the controls" a second button under "Put the controls back" switches between two-thumb and one-thumb (the d-pad) movement; it
  saves the same setting as the Options switch. The editor's two buttons are kept as wide as the picture and their text shrinks to fit (a review found they could spill over the side columns sideways; seen sideways on the S23 after the fix: both stay over the picture and the text fits). Seen on the S23: the bigger keys in portrait, the editor with the new button, and switching to one thumb (the d-pad
  returns) and back to two thumbs, each with a message.
- **Action says "Enter" on the game's menus (the owner's request; it first said "Select", and the owner found Enter right, working for dialogue pages too):** with no banner word, `GameView.onMenuScreen()` looks at the text the game drew: two or more
  lines of three letters or more across the middle of the screen (rows 25 to 186) is a menu (the title menu, Options, the Status screen), where the key picks the
  highlighted entry, so Action reads **Enter** (a menu-font picture `w_enter`); in the 3D world, which draws only a banner at the top and the softkey words at the
  bottom, it still reads Action/Jump. Seen on the S23 (as Select, before the rename): Select on the title menu and the Status screen, Action/Jump on the loading splash and in the world. The dialogue
  pages also draw several text lines, so they read Enter as well (the owner confirms Enter works there). The owner also saw **Lift** and **Throw** banners and they work
  as Action words; they now have menu-font pictures (`w_lift`, `w_throw`) instead of the system-font fallback (not looked at on screen).
- Sideways with the flip phone mode on (where the usual controls show), the two-thumb layout applies too when its option is on.
- **Seen on the S23:** the layout in portrait and landscape (the keys at the bottom corners of each column, Magic and Status small in portrait) and an Up key lighting
  while held. **Not tried:** playing with it (feel, hit areas, whether Magic and Status are big enough in portrait), the controls editor with the new groups, the saved
  places, and a switch for it in the game menu (it is in Options only).

## Three control layouts, the cross is the default (2026-10-11, built; NOT seen on the phone, it was disconnected)

- **The owner's request:** a screenshot of their own arrangement (Action in the middle, an arrow key on each side, Magic and Status in the bottom corners) "should be the
  default; leave the other ones as b and c options; align these buttons, just giving you the idea of the shape". So there are now three layouts for the smartphone look
  (`Settings.controlLayout`, Options > Control layout, and the layout button in "Move the controls", which cycles A, B, C):
  **A: cross** (default), **B: two thumbs** (the earlier default, kept with its built-in places), **C: one thumb (d-pad)**. Each has its own saved places
  (`ctl2_port4_*` for A, `..._port3_*` for B, none for C); an install that had chosen the d-pad before (`two_thumb` false) keeps it, every other gets A.
- **Layout A's geometry (`GameView.layoutCross`):** worked out from the room under the softkeys, not from stored offsets, so it is the same shape at any picture size or screen: Action's
  radius `ra` is the smaller of a 6.25th of that height and a 6.44th of the width (times 0.98); the four arrow keys are 1.85 `ra` square, 2.2 `ra` from Action's centre
  (above, below, left, right, all alike: the screenshot had them a little uneven); Magic and Status are 0.72 `ra`, 2.5 `ra` to each side, level with the down key. Portrait: centred
  on the screen; sideways: in the right-hand column (nothing is at the left yet). At the default picture size the room is 563 px tall on the S23, so `ra` is 90 px (a bit smaller than in the
  owner's screenshot, which was taken with Picture size 5x: 708 px, `ra` 113 px). A drawing of it at both sizes on the PC looked right; the app was only built.
- **Still true for B:** its places are fractions tuned for the fitted picture and use the fit-based area (the fix below), so a picture size does not move them. Layout A uses the real
  area under the softkeys instead (it is computed from it, so it adapts).

## Controls after a size change (2026-10-11, fixed and checked on the S23)

- **Report:** "controls go out of whack when screen size changes". **What it was:** the **Picture size** option (the owner had it on 5x, not the default fit). A smaller picture left a
  taller area for the controls, which sat higher and were sized from it, while the two-thumb default places are fractions tuned for the fitted picture; Magic ended up over the Up key and
  everything was bigger. **Fix:** `GameView.layoutBase` and `layoutLandscape` lay the controls out for the fitted picture size whatever the picture size is; the picture and the
  softkeys under it follow the chosen size (a gap is left above the controls). Checked on the S23 with Picture size 5x: the controls are where they are at the default size, in
  portrait and landscape. (The default size is unchanged in the code: `ghFit` equals the picture height there.)
- **A real display-size change was tested too** (`wm size 900x1800`, then back): the controls were laid out again each time and came back to where they were, so that is not what
  the report was about. A related hygiene fix (commit `6cddfa5`) stays: `applyOffsets` used to write its fitted positions and sizes back into the stored ones, so a window squeezed for a
  while (split-screen, a pop-up window) could move and shrink the saved controls for good; they are now written back only while the editor is open, and opening the editor lays out once.
  That one was found by reading the code, and the squeeze test above did not exercise it (the screen size returned to the start each time).

## Sharing high scores (2026-10-10, done; no score was posted)

- **First start asks once.** Before the game starts for the first time, a question: "Share your high scores?", saying what is
  sent (the world, the score, the time, the Munny, EXP and level behind it, and since 2026-11-02 that it came from
  Android and the Re:Cast version; no name, account or device ID) and that
  scores are always kept on the phone too. Two answers, "Share my scores" and "Keep scores on this phone"; it cannot be
  dismissed without answering, and nothing is sent or saved before the answer. The default until answered is not to share
  (the desktop launcher's box is ticked by default; here the player was asked to be asked).
- **Options > Online scores** has the switch (applies the next time the game starts) and **Test the connection**, which
  fetches the leaderboard's top list (a read request; nothing is posted) and says in words whether it answered.
- **Core and manifest:** the `INTERNET` permission (the only one the app asks for) was added; `start_game(..., leaderboard)`
  sets `emu.leaderboard_url` like `khvcemu/__main__.py` does, empty when not sharing. The address is
  `Settings.LEADERBOARD_URL`; `tests/test_android_assets.py` keeps it equal to the launcher's.
- **Verified on the S23 Ultra:** the question appears before the game starts and nothing is saved until it is answered;
  answering "Keep scores on this phone" saved `share_scores=false` and the game started at 25 fps; Test the connection
  reached `https://scores.khrecast.com` over HTTPS and got 405 bytes (so the app's Python can use TLS). **Not done, on purpose:**
  posting a score (it would add a real row to the live board). So the full path from finishing a world to a posted score
  on the phone is untested; it is the desktop's `web.py` code, which the desktop tests cover.
- "Restore the default settings" clears the answer too, so the question comes back at the next game start (and the
  switch shows off until answered): no sharing without a fresh yes.
- **To check before release:** the privacy wording here and on the website say the same thing, and the store/install text
  names the `INTERNET` permission.

## Moving the controls (2026-10-10, done in part)

- **The game's menu has "Move the controls".** The d-pad, the Action/Magic/Status group and the three softkey bars can each be
  dragged (dashed outlines show what can be grabbed; the one being dragged turns yellow). Each group stays inside the
  free area, the positions are saved when a group is dropped (a fraction of the screen's width and height from where it
  started, kept apart for portrait and landscape), and Back finishes ("Controls saved"). While editing, nothing presses a key.
  **Options > Controls > "Put the controls back where they started"** clears them.
- `GameView.layoutControls` lays out as before (`layoutBase`) and then moves each group by its offset (`applyOffsets`);
  the touch tests use the moved rectangles, so a moved control is where it is pressed.
- **Verified on the S23 Ultra, portrait:** dragged the d-pad and the buttons; the outlines and the hint showed; both offsets were
  saved (`ctl_port_0`, `ctl_port_1`); the moved layout was still there after a full restart; the Reset button cleared both.
  Each softkey bar is its own group (five groups in all), the game is held while editing, and the drag follows one finger by id.
  **Not shown:** that a key press lands on the moved d-pad (it uses the same rectangles, but the title screen gave no
  visible proof), moving in landscape, a two-finger test by hand, resizing a control, saved layouts, game controllers.

## Controls: separate boxes, pinch to resize, a reset (2026-10-10, pinch NOT tried)

- **Every control is its own group now** (seven: the d-pad, Action, Magic, Status, Soft 1, Back, Soft 2), each with a dashed
  box in "Move the controls". **Action is 15% bigger by default** (Magic and Status keep their size and are placed touching it).
- **Pinch to resize:** with one finger on a control, a second finger anywhere changes its size with the distance between the
  fingers (half to double; never bigger than the free area); letting go of either finger keeps the size, and if the first finger
  lifts the second takes over the drag. Sizes are saved per control and per orientation (`ctlscale_*`; positions moved to
  `ctl2_*` when the groups changed).
- **"Put the controls back" button** on the edit screen (over the top of the picture) resets every control, and the
  Options button does the same.
- **Verified on the S23 Ultra, portrait:** the seven boxes and the bigger Action show; Magic dragged alone (saved on its own);
  the edit-screen reset cleared every saved value. **Not verified:** the pinch itself (`adb` cannot send two fingers: the code
  was only read and reviewed), landscape, and a key press landing on a resized or moved control.

## The Wonderland pages (2026-10-10, done; the real splash not reached)

- **Soft 1 on the Wonderland splash starts khvcemu's two "Wonderland is lost media" pages**, as on the desktop: the game is held
  behind them, Soft 1, Action or a tap on the picture turns a page, the last one hands the game its Continue press, and the
  game's clock skips the time they were up (the time the app spent paused meanwhile is not subtracted twice). The pages are
  drawn with Pillow (`lostmedia.build_screens_pil`, 565 frames; the desktop keeps its pygame version) and shown through
  `frame_bytes`. If they cannot be drawn the game just continues.
- **Found on the phone and fixed:** (1) the two screenshot assets were WebP data in `.png` files, which the phone's Pillow cannot
  read: converted to real PNG, pixel for pixel (a test checks every asset `.png`); (2) text drawn without smoothing is up to
  14% wider than Pillow measures, so wrapped lines ran off the page: `PilFont.size` now reports the drawn width (this also
  changes the width the game's own text path sees on the phone, in the direction of what pygame reports).
- After review: a save or load from the menu is handled while the pages are up (a load ends them); the time a save takes is
  not counted twice; the player's finger lifting right after the last page does not cut short the Continue press the core
  sends; each key flag is cleared where it is read. Known and left: a state made while the pages were up (an autosave on
  leaving) loads with the splash up and no pages, and Soft 1 starts them again; the pause/resume accounting is tested only
  through the pieces (a hand-set `lm_paused`), not by driving the loop; on the phone every new string costs one extra small
  render to measure it (cached).
- **Tests:** `tests/test_android_lostmedia.py` (the state machine with a fake emulator, six cases), `tests/test_lostmedia_pil.py`.
- **Verified on the S23 Ultra** with a diagnostic flag file (`files/lm_test_flag` makes the core act as if the splash were up,
  like `profile_flag`): Soft 1 at the title showed page 1, a tap page 2, another tap ended it; the game was held (0 fps) behind
  the pages and back at 25 fps after; both pages fit the screen. **Not reached:** the real Wonderland splash (it needs a finished
  Island), so the splash flag, the Continue press that follows and the clock catch-up were tested only with the flag.

## The Wonderland theme (2026-10-11, done; the owner heard it)

- **What it is:** the lost Wonderland chapter's music, Aid1043's "Authentic Restoration" rendering of the original MIDI (credited in `docs/CREDITS.md`; the desktop
  installers carry the same file). The core already plays it on the Wonderland splash if `wonderland/Wonderland.flac` sits in the game folder (`chapters.install_patches`
  serves it as `wonderland.mid`, the name the game asks for).
- **On the phone:** (1) `app/build.gradle.kts` packs `../wonderland/Wonderland.flac` into the APK as an asset **only if that file is there when the app is built** (the folder is
  gitignored, as it is for the desktop installers; a build without it simply has no theme; the debug APK grew by 1.4 MB); (2) `MainActivity.installWonderlandTheme` copies it to
  `files/game/wonderland/` at each game start if it is missing (installing the game files again replaces that folder); (3) the core's audio engine now decodes any audio
  buffer through `audio.FILE_DECODER` when there is no ffmpeg (before, only a player's recording went through it), because the theme reaches the engine as the FLAC's bytes.
  A test covers the new path (`tests/test_music_mixes.py`).
- **Verified on the S23 Ultra** with a new diagnostic flag file (`files/wl_test_flag`, next to `lm_test_flag` and `profile_flag`): the core played the theme at start through the
  same path as the splash; no decode error, an AudioTrack was started, and the audio peak in the log was about 9,000 to 13,500 (the other music peaks near 5,000 to 6,000, so
  this recording is louder; the Setup tab's volume slider has no counterpart in the app yet). The theme is replaced when a build carries a file of another size; a theme removed from `wonderland/` also leaves the next build. **Heard by the owner** during that test run (it played at the game's start because of the flag; the flag file was removed afterwards, so normal starts do not play it). **Not reached by
  playing:** the real splash, which needs a finished Island.
- **Not done:** a Wonderland volume setting in the app (`--wonderland-volume`'s counterpart; the file is louder than the other tunes); and the app's notice still says it
  "contains no game files": the theme is a fan rendering of the game's music (same policy as the desktop installers), so the notice or the credits screen may want a line.

## Picture filters and text size (2026-10-10, done)

- **Options > Picture filter** has the desktop's four filters: Pixels (crisp), Smooth (bilinear; the desktop's is bicubic, so
  slightly softer here), Sharp pixels (the largest whole-number size drawn crisp into a reusable bitmap, then one soft step to
  the rest) and Scale2x (EPX done in Java on the 176 x 220 picture: doubled while twice the size still fits, at most twice, then a
  soft step; under 2x it is just smooth. The desktop has no cap on the doublings, so above 8x it differs). They take effect at once; all four ran at 24 to 25 fps on the S23 Ultra.
- **Options > Text size** is the game's own text size, 8 to 16 pixels (11 is the usual), sent to the core
  (`emu.font_size`) when the game starts. Size 15 visibly enlarged the title menu text on the phone.
- **Verified on the S23 Ultra:** the same title screen under each filter (four different looks, compared side by side) and
  text size 15. **Not compared:** the Java EPX against the desktop's pygame `scale2x` pixel by pixel; hi-res text (the
  desktop's smooth text drawn at window resolution) is not built.

## Game controllers (2026-10-10, done with injected events only)

- **A controller (or a keyboard with a D-pad) presses the phone keys:** the D-pad and the left stick (and the hat) move; A is
  Action, B is Back, X is Magic, Y is Status, L1 or L2 is Soft 1, R1 or R2 is Soft 2, **Start opens the game's menu** (inside
  that menu the controller moves the highlight and A picks, through Android's own focus). `GamePad.java` is the mapping;
  `MainActivity.dispatchKeyEvent` and `dispatchGenericMotionEvent` take the events; `GameView.padKey` presses the key and
  remembers which source holds it, so the stick and the D-pad can share a key; leaving the app lets everything go. While the
  controls are being moved a controller does nothing.
- **Verified on the S23 Ultra only with events injected through `adb shell input gamepad`:** two D-pad Down presses moved the
  title highlight from New Game to Options, and Start opened the menu. **No real controller was available**: the stick's dead
  zone (half), the hat, held buttons and repeats, and a Bluetooth pad's button codes are unproven.
- After review: held controller keys and the stick are let go when the menu opens or the app pauses (the dialog takes the
  controller's events, so their releases never arrive); Start does nothing before the game has started or while the controls are
  being moved; a finger and a controller holding the same key do not release it for each other; a controller removed (unplugged or
  switched off) or a window that loses focus lets go of everything the pad holds.
- **Limits:** the analog triggers (axes) are ignored (L2 and R2 work only when the pad sends them as buttons); two controllers
  share one stick state (a second pad sitting at center can let go of the first one's direction).
- **Not done:** remapping the buttons, a controller picker, rumble.

## Saved sound mixes (2026-10-10, done)

- **The Sound screen can keep the player's own mixes:** "Save this mix..." asks for a name (at most 40 characters) and stores the
  current sliders; the saved mixes appear in the Mix list after the ready-made ones; picking one sets the sliders; "Delete
  this mix" (enabled only for the player's own) asks first and leaves the sliders as they are. A name cannot be a ready-made
  mix's name, and settings that equal another mix (ready-made or saved) are refused with the name of that mix, since two mixes
  with the same sliders could not be told apart in the list. Stored in `music_mixes` (name, tab, settings text per line).
- **Verified on the S23 Ultra:** saving "As tuned" is refused with the message; after moving the Piano slider a save kept
  `My piano` (`piano=1.597`), it showed as selected with Delete enabled; the delete asked first and emptied the list.
  "Restore the default settings" keeps saved mixes (they are the player's work, not a setting). Names are compared without regard
  to case (saving "my piano" replaces "My piano") and "Custom" is not allowed. Not done: favorites, renaming, export of mixes to the desktop's `launcher.json` format, recordings and the tune player.

## Signing and building the release (2026-10-12; signed build made, not installed or published)

- **The key:** made on 2026-10-12 at the owner's request (RSA 4096, PKCS12, alias `recast`, valid 10,000 days, certificate `CN=Re:Cast, O=Re:Cast`: no personal name in it). The key file is in a folder
  of its own in the owner's home folder, outside the repository (`storeFile` in `android/keystore.properties` says where; give it an absolute path), and that properties file also holds the generated password. It is gitignored
  (`*.jks`, `*.keystore` and `keystore.properties` are all ignored). The password was never printed or put in a tracked file. **Back up both files** (a password manager and one more copy): an app signed
  with another key cannot update this one, so a lost key means every user must uninstall (losing their saves and game files in the app) to get an update. Certificate SHA-256 (public, for checking a download):
  `686ba6d779f92a927c82c7e882a28744b6dc9faafeeb06918b27d6cc41af0eac`.
- **Build:** in `android`, run `gradlew.bat assembleRelease "-Precast.buildPython=<a Python 3.12>"` (the same note as the debug build). It gives `app/build/outputs/apk/release/app-release.apk` (28.6 MB), signed with that key when
  `keystore.properties` exists (without it the release is unsigned, as before). `apksigner verify --print-certs` says it verifies (one signer, v2 scheme; v1 is not needed at minSdk 26); the package has
  no key files and no personal strings in its text entries; label Re:Cast, `com.khrecast.recast`, version **0.1.0 (code 1)**, targetSdk 36, arm64 only, one permission (INTERNET), not debuggable, backups off.
  **Raise `versionCode` in `app/build.gradle.kts` for every release you hand out** (Android refuses an update with a lower one).
- **Not done: running the signed build on the phone.** The phone has the debug build, signed with the debug key, so the release cannot be installed over it: Android would need the debug app uninstalled first,
  which deletes its saves, settings and installed game files (export saves from Saved games first; the game files would have to be picked again).
- **Still open before handing it out (each is the owner's call):** (1) the Unicorn library is GPLv2 and the project is GPL-3.0; (2) numpy and Pillow are only 4 KB aligned, so phones that use 16 KB memory pages
  cannot run it (the S23 and most phones today use 4 KB); (3) the APK carries the Wonderland theme (Aid1043's rendering, credited in `docs/CREDITS.md`) while the opening notice says "no game files": decide the
  wording and whether to ship it publicly; (4) the privacy wording against the website; (5) where it will be downloaded from, and its checksum next to the link (the desktop installers have `SHA256SUMS`).

## Release readiness, checked 2026-10-10 (nothing signed, nothing published; signing is done since 2026-10-12, see "Signing and building the release" above)

- **A release build compiles** (`assembleRelease`, unsigned): **25.9 MB** (the debug build is 37.6 MB; the bar was 60 MB). Signing
  needs a key that only the project owner should make and keep; the app is sideloaded, not on a store.
- **16 KB memory pages (Android 15 and later phones that use them): NOT ready.** `android/tools/check_page_alignment.py <apk>`
  reads the ELF headers of every native library, also inside Chaquopy's packed archives: 79 of 99 are 16 KB aligned (our
  libunicorn, Python, Chaquopy's own libraries), **20 are only 4 KB aligned: numpy's 16 `.so` files and Pillow's
  FreeType and imaging libraries** (the packages Chaquopy ships for Python 3.12: numpy 1.26.2 and Pillow 11.0.0; its package index has no
  other numpy for 3.12 and no 16 KB build). A phone with 16 KB pages would refuse to load them. Phones with 4 KB pages,
  including the S23 Ultra, are unaffected. Ways out, none tried: a newer Chaquopy with rebuilt packages, building numpy and Pillow
  ourselves with 16 KB alignment, or dropping them (hostgfx and the core use both).
- **The Unicorn build is now a script:** `android/build_unicorn_termux.sh` (tag 2.1.4, ARM only, Release, 16 KB linker
  alignment, prints size, SHA-256 and the segment alignment). It was written from the recorded steps and **has not been run**; a
  rebuild with another compiler will not be byte-identical, so it is checked by behavior, not by hash. The library still comes from
  the phone, so the build is repeatable but not independent of Termux.
- **Still open for release:** signing, the Unicorn
  GPLv2 against this project's GPL-3.0 question, the privacy wording against the website, naming the INTERNET permission in the
  install text, and the owner's own passes with a finger, a real controller and the pinch.

## Flip phone mode (2026-10-10, a mock-up; done in part)

- **What it is:** Options > Controls > "Flip phone look (upright only)". The game appears on the screen of a clamshell phone drawn
  round it (`FlipPhone.java`): speaker slot, black bezel, hinge, then the lower half with Soft 1 / Soft 2, a navigation ring with a
  center button, a green Call and a red End key, and a 12-key keypad. Held keys light up. It replaces the usual controls while on.
- **Look:** gray and silver plastic like a 2005 handset: gradient shell halves with a lit inner edge, a hinge barrel, a speaker with
  holes, a camera lens, a status light, a stub antenna on the top corner, pale raised keypad keys with dark print and soft shadows,
  blank darker-silver softkeys (no print), a metal navigation ring, glossy green Call and red End; held keys turn blue.
- **Name strip:** "Re:Cast" printed under the screen, and the defunct V CAST logo on a small light plate beside it
  (`res/drawable-nodpi/vcast_logo.png`, the owner's image of Verizon's old logo: a third party's mark, covered only by the project's
  fan-game disclaimer; the plate is light in both colors, since the logo is black and red on white). The logo and the blank softkeys were built but NOT seen on a screen (the phone was disconnected).
- **Graphite:** (2026-10-11: replaced by the color list described below) Options has "Graphite flip phone" (the same body in dark gray, `flip_graphite`); both colors were seen in screenshots
  on the S23. The Options wording ("Play it the way it was meant to be played: on a flip phone") was not looked at on screen. The
  owner tried landscape and the key presses (before the graphite color) and found them fine.
- **Keys:** 2, 4, 6, 8 send Up, Left, Right, Down and 5 sends Select (the game is steered with directions and Select, which the
  desktop's arrows and Enter send; the desktop's digit keys send digits, and whether the game also reads those is not checked); the ring does the same; * is Magic, 0 is Status; Soft 1 and Soft 2 as usual (the blank pills at the top corners of the keypad); End is
  Back; Call sends the phone's Send key, which the game ignores. 1, 3, 7, 9 and # send their keys, which the game also ignores.
- **Upright only:** sideways it falls back to the usual landscape layout. "Move the controls" says the flip phone has fixed keys.
- **Verified on the S23 Ultra:** the layout draws and the game runs in it; tapping 8 twice moved the title highlight from
  New Game to Options and the ring's center button opened it. **Not tried:** landscape fall-back on the device, the other keys
  (softkeys, Call, End, * and 0), multi-finger presses, other screen sizes. The picture is smaller than in the usual layout (it is about
  a third of the phone's height, since the keypad needs the rest).

## First-run style question and the small bezel (2026-10-10, done; seen on the S23)

- **The question:** the first time the app is opened, "I understand" on the opening notice leads to `StyleActivity` instead of the
  home screen: "How do you want to play?" with **Smartphone style** (touch controls round the picture) or **Flip phone style** ("the
  most authentic 2005 V CAST experience") with two tick boxes above its button, (since replaced by a color list) "Graphite instead of silver" and "Small bezel (a
  bigger picture)". The answer is stored (`style_chosen`, plus `flip_phone`, `flip_graphite`, `flip_small_bezel`) and the question is
  not asked again; "Restore the default settings" keeps `style_chosen` (a player who already answered is not asked again). Everything
  can be changed later in Options. Players who had the app before this build are asked once. Starting `HomeActivity` straight from adb skips the question and
  leaves the defaults (smartphone style); `StyleActivity` can be started the same way for testing.
- **Small bezel:** `FlipPhone.setSmallBezel`: the picture may use 44 percent of the free height and 90 percent of the shell's width
  (36 and 72 percent otherwise; about a fifth larger by the numbers), the frame round it is 3 dp instead of 8, the shell's side margin
  2 percent instead of 3, and the keypad is correspondingly shorter. Options has the switch too ("needs the flip phone look").
- **Verified on the S23 Ultra:** after the notice the question appears with both tick boxes visible; ticking both and choosing flip phone
  style, then Play from the title screen, gave the graphite small-bezel phone with a clearly bigger picture, the V CAST logo plate, the
  blank softkeys and 25 fps. **Not tried:** key presses on the shorter keypad (the owner is to judge whether the keys are comfortable),
  landscape with the new settings, the smartphone answer, and the silver small bezel. The buttons are plain themed text, not the
  menu-font pictures.

## Launch prep: the status line and the website pictures (2026-11-01)

- **The core's status line** ("running 25 fps frames ... faults 0") was drawn under the game in every build, release
  included, and right after a state load its fps figure is nonsense (the frame count jumps). `GameView.statusShown()` now
  draws it only when the game has stopped or the line carries an ERROR; it still goes to logcat every second (tag
  `recast`, "status: ..."). Seen on the S23 (debug build): gone in play.
- **Website pictures** (`site/assets/android_*.webp`): taken on the S23 with adb `screencap` from a debug build, prefs
  written per look through `run-as` (style chosen, mute on, autosaves off, sharing off, sharp text on), the game started
  with `am start -n com.khrecast.recast/.MainActivity --es load <slot>` (the slot is the number, `1` to `9`, or `auto1`
  to `auto3`). Scenes are four of the owner's PC save states copied into spare phone slots 5 to 8 and deleted after: the
  "Attack" tutorial fight (layouts A, sideways, the six colors), the Castle corridor (B), the Genie in the lava cave (C,
  silver flip phone). Status and navigation bars cropped (portrait y 100 to 2170, landscape y from 90, x to 2190),
  scaled (540 wide portrait, 1000 landscape, 900 the colors grid) and saved as WebP. Before: prefs, rotation, states,
  game saves and playtime.json backed up; after: all restored and checked with diff (playtime.json had grown and was put back).
- **The download** is `dist/KH-ReCast-Android.zip` (gitignored, like the installers): `KH-ReCast-Android.apk` (the signed
  release, stored), `KH-ReCast-game/` (`mif/`, `mod/` and the three `savegame(world).dat`, as the desktop installers carry
  them; the Wonderland theme is already in the APK) and `README.txt` (install steps). The player extracts it on the phone,
  installs the APK and picks `KH-ReCast-game` in Setup. Made by a one-off scratch script (not in the repo yet); 28.5 MB, 144
  entries, checked with `testzip`. `tools/checksums.py` lists it with the installers (prefix `KH-ReCast-`, `.zip`).
  The release was rebuilt after the status line change; `apksigner` shows the same certificate (SHA-256 686ba6d7...0eac).

## Website pictures retaken, and a debug build beside the release (2026-11-02)

- `gradlew assembleDebug -Precast.debugSuffix=true` gives a debug build with the app id `com.khrecast.recast.debug`, so it installs
  beside the signed release (same id would need the release uninstalled first, which deletes its data). Without the property nothing changes.
- The home page's phone pictures were retaken from a screencap of that build on the S23 (prefs written per look through `run-as`, the PC
  states pushed into its `files/data/states`, loaded with `am start --es load <slot or autoN>`, notifications silenced and rotation set
  for the sideways one, both put back after): portrait crop y 100 to 2170 and scaled to 810 wide, the colors grid 3 x 2 at 450 each, sideways
  crop (90, 90, 2190, 1040) scaled to 1600 wide, WebP quality 82. A set pairing a smartphone with the flip phone to show the Action word
  and softkeys (Attack, Enter, Continue and Replay, Save and Back) was made too, then left off the site at the user's request.

## Leaderboard rules from the core (2026-11-02)

The core changes reach the app with the next build, nothing app-specific: runs with a save state loaded are not
shared (`playtime.resync` is called by `savestate.load`, which the app's menu uses too), only a score that beats the
best this copy already shared goes out, and each shared score carries `pl=android` (detected by `web.platform_name`
from `sys.getandroidapilevel` or the `ANDROID_DATA` variable) and `vr=` the core version. The app's own version name
(0.1.0) is not sent. Not yet run on the phone.

## 1. This machine (checked 2026-10-06, before Chunk 2 installed the toolchain)

Windows 10 Home 19045, Intel i7-11700F (8 cores, 2.5 GHz base, about 4.9 GHz turbo), 16 GB RAM.
Python 3.14.7, unicorn 2.1.4, numpy 2.5.3, pygame-ce 2.5.8.

| Tool | Found |
| --- | --- |
| java / javac (JDK) | no |
| adb, sdkmanager, avdmanager, emulator | no |
| cmake, ninja, gradle | no |
| ANDROID_HOME, ANDROID_SDK_ROOT, ANDROID_NDK_HOME, JAVA_HOME | not set |
| %LOCALAPPDATA%\Android, C:\Program Files\Android, Java, Eclipse Adoptium | absent |
| adb device | none (no adb) |

## 2. Desktop baseline (measured)

Tool: `android/spike/bench_headless.py` (does not modify `khvcemu/`; it wraps `Cpu._on_trap` to count
BREW calls and can add a Unicorn block hook to count guest instructions). Headless, virtual clock,
`audio=False`, game files from the repo folder (`mif/`, `mod/`, `savegame(island).dat`).

```
SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=dummy python android/spike/bench_headless.py --root "$PWD" boot|world|audio [--count] [--traps]
```

| Run (game time) | Wall time | Real-time factor | Host frame cost | Game fps | BREW calls/game s | Guest instructions/game s |
| --- | --- | --- | --- | --- | --- | --- |
| Boot to title (11 s) | 5.7 to 7.2 s | 1.5x to 1.9x | 21 to 26 ms | 25 | 1,221 | 58 M (637 M total) |
| Island opening, cutscene + dialogue load (10 s) | 11.9 to 12.3 s | 0.82x to 0.84x | 47.5 to 49 ms | 25 | 11,688 | 160 M |
| Island opening, steady 3D (10 s) | 11.6 to 11.9 s | 0.84x to 0.86x | 46 to 47.5 ms | 25 | 1,020 | 168 M |

- The game asks for a frame every 40 ms (25 fps). In the 3D scene the desktop needs about 47 ms of host
  time per frame, so the real-time window runs at about 21 fps there. Each 3D frame is about 6.5 M
  guest ARM instructions.
- Effective Unicorn throughput, including Python: about 92 to 110 M guest instructions/s at boot, 130 to
  145 M/s in the 3D scene.
- Where the time goes (cProfile): boot run 85% inside `Uc.emu_start` (native Unicorn), 11% in the
  Python trap path (about 50 us per BREW call). The whole world run (including loading) 79% native,
  20% Python. In steady 3D there are only about 1,000 BREW calls per second (about 5% of the time):
  the frame cost is the game's own ARM code (kh.mod and the Swerve renderer; the split between the two
  was not measured) running in Unicorn. Moving the HLE layer to C++ would save at most that 5 to 20%.
- Hot BREW calls while a scene or dialogue loads: `Helper::strncmp` 85,611 in 10 s, `malloc` 29,797,
  `free` 25,735, `strcmp` 19,575, `strlen` 11,819 (`cpu.cstr` alone is about 2.2 s of a 50 s run).
  These are the first candidates for native helpers if loading stutters on a phone.
- Unicorn knobs (boot run, two runs each): TLB mode `UC_TLB_VIRTUAL` is 2.7x slower (15.4 to 17.2 s),
  do not use it. TCG buffer 64 MiB instead of the default 1024 MiB: same speed (5.7 s vs 5.7 s), so a
  phone build can use a small buffer.
- Memory: peak working set about 61 MB at the title, 64 MB in the 3D scene (Python, numpy, Unicorn,
  game). Windows also reports about 650 MB of committed address space (500 MB of it already right after
  the imports), which is reserved, not touched, memory.
- Built-in synth: the nine tunes (about 79 s of audio, 22,050 Hz mono) render in 6.3 to 6.7 s total on
  this PC (longest: training.mid 1.8 s). The disk cache is about 3.5 MB of int16.
- Without pygame at all (forced unimportable) the headless core still boots to the title and loads the
  3D scene with the same speed and no faults: only host-drawn text and BMP/PNG images are missing. A
  phone-side speed test therefore needs only Python, numpy and Unicorn.
- Game files: `mif/` 9 KB, `mod/` 1.7 MB.

What the core needs from the host besides Unicorn and numpy (all through pygame today):
`display.py` text (pygame.font with Verdana or a fallback; text layout and so the number of journal pages
depend on the font), `image.py` BMP/PNG decode, `audio.py` mixer (`pygame.mixer` Sound/Channel),
`savestate.py` thumbnail PNG, `lostmedia.py` Wonderland pages. `launcher.py` is tkinter (desktop only).

## 3. Research findings (sources checked 2026-10-06)

- **Unicorn on Android:** upstream documents cross-building Unicorn 2 with the NDK CMake toolchain for
  armeabi-v7a, arm64-v8a, x86 and x86_64 (CMake 3.19 or newer for current NDKs)
  ([COMPILE.md](https://github.com/unicorn-engine/unicorn/blob/master/docs/COMPILE.md)). Not tried
  here yet. No Android wheel on PyPI: unicorn 2.1.4 ships win, macOS, manylinux x86_64/aarch64 only.
  The Python binding is pure Python over ctypes and loads the library from `LIBUNICORN_PATH` (checked in
  the installed 2.1.4 binding), so on Android it can use a `libunicorn.so` built with the NDK.
  `pip install unicorn` in Termux fails on a missing `cmake/bundle_static.cmake` in the sdist
  ([termux-packages #22989](https://github.com/termux/termux-packages/issues/22989), open, no fix);
  building from the git source should avoid it (untried). The installed Windows DLL is 9.6 MB with
  all architectures; an ARM-only build should be much smaller (untried).
- **Executable memory for the JIT:** current AOSP policy still has
  `allow appdomain self:process execmem;` with the comment "WebView and other application-specific JIT
  compilers" ([private/app.te, main](https://android.googlesource.com/platform/system/sepolicy/+/refs/heads/main/private/app.te)).
  So anonymous RWX memory for Unicorn's TCG should be allowed for an ordinary app at any target SDK.
  Android 10's change removed `execute_no_trans` (running files from app storage with execve), not
  `execmem`. Checked in Chunk 3 on the S23 Ultra (Android 16, targetSdk 36): no avc lines.
- **16 KB pages:** devices with 16 KB pages exist (and an emulator image `google_apis_ps16k`). NDK r28+
  aligns to 16 KB by default. Unicorn has an old report about assuming 4 KB host pages
  ([unicorn #81](https://github.com/unicorn-engine/unicorn/issues/81)): test on the ps16k image.
- **Chaquopy:** open source (MIT). Chaquopy 17 supports Python 3.10 to 3.14, but Python 3.14 has very
  few Android wheels yet ([changelog](https://chaquo.com/chaquopy/doc/current/changelog.html); the site
  did not resolve from here today, seen through search). numpy for Chaquopy comes from its own
  repository for Python 3.12 and older; for 3.13+ wheels must come from PyPI (built with cibuildwheel),
  and numpy 2.5.3 on PyPI has no Android wheel as far as the PyPI JSON shows
  ([chaquopy pypi README](https://github.com/chaquo/chaquopy/blob/master/server/pypi/README.md)).
  So: plan on Python 3.12 inside the app (khvcemu needs 3.10+). No unicorn package: bundle the pure
  Python binding plus our NDK-built `libunicorn.so`. No pygame: the host functions above need an
  Android backend.
- **python-for-android (Kivy/buildozer):** has numpy and a pygame-ce recipe (SDL2,
  [p4a PR #2971](https://github.com/kivy/python-for-android/pull/2971)), which would keep pygame working,
  but buildozer runs on Linux or macOS only (WSL2 on this PC) and SAF, lifecycle and gamepads go through
  pyjnius. Not chosen (see 4).
- **Prior art, Melange** ([gitlab.com/usernameak/brewemulator](https://gitlab.com/usernameak/brewemulator),
  credited in README): an Android BREW emulator written in C (99%), built for `armeabi-v7a` only,
  targetSdk 20, and it ships RVCT runtime helpers (`ARMLegacyABI.S`: `__ARM_ll_*`). From its layout it
  appears to run the BREW module's ARM code natively on a 32-bit ARM CPU rather than emulating it (not
  confirmed by reading its loader). That is the fastest possible path but only on phones that can still
  run 32-bit code (many 2023+ phones cannot) and it cannot install on Android 15+ without
  `--bypass-low-target-sdk-block` at targetSdk 20. It also explains "the game runs in an Android
  emulator without audio" in our README.
- **Faster CPU backend if Unicorn is too slow:** dynarmic (0BSD) has an arm64 host backend and an A32
  frontend (ARMv6K/v7 era); ARMv5 differences (unaligned LDR rotation, some CP15) would need checking.
  Not evaluated; listed only as the lever if the spike fails.
- **Sideloading rules:** Android 15+ refuses to install apps targeting below API 24
  ([bayton.org](https://bayton.org/android/advisories/android-15-app-install/)). Developer verification:
  from September 2026 in Brazil, Indonesia, Singapore and Thailand, and from 2027 globally, apps on
  certified devices must come from a verified developer or be installed through an "advanced" flow with a
  waiting period; `adb install` stays exempt
  ([Android Authority, 2026-03-30](https://www.androidauthority.com/android-developer-verification-rollout-sideloading-flow-3653395/)).
  A sideloaded Re:Cast APK will need either a verified developer identity or users installing through
  that flow or adb. This is a decision for the user, not an engineering one. Play target API from
  2026-08-31 is 36; irrelevant for sideloading but target 36 anyway.
- **Build stack today:** Android Gradle Plugin 9.4 (Gradle 9.6, build-tools 36.0.0, default NDK
  28.2.13676358, JDK 17, max API 37) ([AGP notes](https://developer.android.com/build/releases/gradle-plugin));
  latest LTS NDK r30 30.0.16248370 ([NDK downloads](https://developer.android.com/ndk/downloads)).

## 4. Recommendation: Python core on Chaquopy, native Unicorn, Kotlin front end

Keep `khvcemu/` as the one emulator core for desktop and Android. The Android app is Kotlin (Compose for
menus, a SurfaceView showing the 176x220 RGB565 frame, which Android's `Bitmap.Config.RGB_565` takes
as is), runs the core in a background thread through Chaquopy (Python 3.12, numpy from Chaquopy's
repository), and loads `libunicorn.so` built from source with the NDK (ARM guest only, arm64-v8a plus
x86_64 for the emulator, 16 KB aligned, TCG buffer 64 MiB). The four pygame uses get a small host
interface with pygame as the default desktop backend and an Android backend (text with a bundled font,
images via Android's decoder, sounds played by Kotlin AudioTrack/Oboe from the core's PCM). Hot spots
move to native code only when a device measurement shows they matter (hybrid, step by step).

**Main trade-off:** we accept about 5 to 20% CPU overhead from Python and a larger APK (Python runtime
plus numpy, an estimated 30 to 50 MB, to measure) in exchange for not rewriting 9,200 lines and for one
codebase that the 225 desktop tests keep correct. The measurements say a C++ rewrite would not make a
slow phone fast: about 90% or more of a 3D frame is the game's own ARM code inside Unicorn. If a phone
is too slow, the levers are the CPU backend (dynarmic) and the frame cap, not the HLE language.

What decides playability is the phone's single-core speed. The desktop (a fast desktop core) gets about
21 fps in a busy 3D scene; a phone core at half that speed would get about 10 fps. The original
phones ran this on an ARM926 at a few hundred MHz, so they likely did not reach 25 fps there either
(6.5 M instructions per frame), but that is an inference, not a measurement.

## 5. Feasibility spike plan (pass/fail numbers)

Run every step on the user's slowest phone that matters (arm64 device; an x86_64 emulator image is only
a functional check, never a speed number). Record each result in section 6 with the device model, SoC,
Android version and battery/thermal state.

**Spike 0 (optional, no PC toolchain, about an hour, needs user approval for the phone):** Termux on the
phone (`pkg install python python-numpy clang cmake make git`), build Unicorn from the git source with
Termux's clang, install its Python binding, copy the repo and the game folder, then run
`bench_headless.py boot`, `world`, `audio` exactly as on the desktop. Termux is a normal Android app on
the phone's own CPU, so its numbers are the phone's numbers. This answers the go/no-go question before
downloading about 1.3 GB of toolchain.

**Spike 1 (APK, needs the install list):**
1. Minimal Kotlin app (targetSdk 36, minSdk 26) with `libunicorn.so` from CMake, JNI test that maps
   memory, runs a short ARM + Thumb snippet with a trap-page `bx lr` and a code hook, and checks R0.
   Pass: correct result on the phone and on the x86_64 emulator (4 KB and ps16k images), no `avc:
   denied` for execmem in logcat.
2. Add Chaquopy (Python 3.12, numpy), copy the game folder in once through the document picker
   (`ACTION_OPEN_DOCUMENT_TREE`) into app-specific storage, run `bench_headless.py boot` in-process.
   Pass: `title_reached: true` (frames >= 200, faults 0, lit > 0.2, as `test_boots_to_title_menu`).
3. Run `world` and `audio` in-process and note APK size and memory (`adb shell dumpsys meminfo`).

Pass/fail on the target phone (desktop in brackets):

| Measure | Pass | Marginal | Fail | Desktop |
| --- | --- | --- | --- | --- |
| Boot to title, real-time factor | >= 1.0x | 0.6x to 1.0x | < 0.6x | 1.5x to 1.9x |
| 3D scene (`world_scene_b`), real-time factor | >= 0.6x (15+ fps) | 0.4x to 0.6x (10 to 15 fps) | < 0.4x (under 10 fps) | 0.84x to 0.86x (21 fps) |
| Guest instructions/s in 3D (168 M per game second x the real-time factor) | >= 100 M | 65 to 100 M | < 65 M | 140 to 145 M |
| Synth render of the nine tunes, first launch only | < 60 s | 60 to 180 s | > 180 s | 6.3 s |
| Peak memory (PSS) in the 3D scene | < 300 MB | 300 to 500 MB | > 500 MB | 64 MB working set |
| APK size (arm64 only) | < 60 MB | 60 to 100 MB | > 100 MB | not built |

Marginal or fail means: stop and report, then in this order try a 15 fps cap (the game is time based),
native string/heap helpers (only matters while loading), and a dynarmic backend behind the `Cpu` class.

## 6. Spike results

### Spike 0, Termux, 2026-10-10: Galaxy S23 Ultra (user's phone), Python 3.14.6, Unicorn 2.1.4 built on the phone

Read off the user's screenshot of `~/spike_log.txt` (the phone and SoC header lines scrolled off it; battery and
temperature were not recorded; one run of each, no repeats). The same repo code as the desktop, no pygame
installed (so no host-drawn text), the speed patches `span` and `matinv` on (the default).

| Measure | Phone | Pass bar | Desktop | Verdict |
| --- | --- | --- | --- | --- |
| Boot to title, real-time factor | 1.389x (28.8 ms per frame, 275 frames, faults 0, title reached) | >= 1.0x | 1.5x to 1.9x | pass |
| 3D scene, real-time factor | 0.876x (scene a, loading), 0.92x (scene b, steady 3D; 43.5 ms per frame, 23 fps capacity) | >= 0.6x | 0.84x to 0.86x before the speed patches, about 0.93x with them | pass |
| Guest instructions per second in 3D | not counted on the phone; about 150 M estimated (168 M per game second on the desktop x 0.92; fewer with the patches) | >= 100 M | 140 to 145 M | pass (estimate) |
| Synth render of the nine tunes | 11.99 s (training 2.97 s the longest), peak 48.6 MiB | < 60 s | 6.3 s | pass |
| Peak memory (the Python process) | 58.8 to 60.6 MiB RSS | < 300 MB (PSS in the real app is still to be measured) | 64 MB | pass |
| APK size (in Chunk 4, with Python) | 26.9 MB debug APK with Python, numpy, Unicorn and the core | < 60 MB | | pass |

What this says: on this phone the unmodified Python core with an ARM-only Unicorn built by Termux's clang runs the
game at about 0.9x real time in the busiest scene tried, as fast as the development PC. It reaches 25 fps in the
menus and about 22 to 23 fps in 3D. The S23 Ultra's Cortex-X3 is one of the fastest phone cores of its generation,
so this is a best case: a pass here does not make a mid-range phone pass.

What it does not say:
- Sustained play (heat): each run was seconds long. Thermal throttling over 10 or 20 minutes is unmeasured.
- The Agrabah lava scene (the slowest on the desktop, about 15 fps there) and a fight were not run; save states
  7 and 9 would need the benchmark pointed at them.
- Termux is an app with an older target SDK (28); the same check in an APK at target SDK 36 was done in Chunk 3
  (it passed on this phone).
- The frame digest differs from the desktop's (boot: phone 250a782cb28866d9, desktop e4aae8d85cb1a4c6) and `lit`
  is 0.366 against 0.376. Probably the host-drawn text (pygame is not installed on the phone, and the desktop
  run had it); not verified. Frames from the core alone should be compared before trusting the picture.
- Python 3.14 worked in Termux, but Chaquopy's Python (3.12, section 3) is a different build.

Decision: the pass bar is met on the test phone, so the plan continues with the toolchain (chunk 2). A slower
phone, if the user has one, is the next useful measurement.

First attempt (earlier the same day): stopped at `CANNOT LINK EXECUTABLE "cmake"` until `pkg upgrade -y` (see Chunk 1).

## 7. Install list for Spike 1 (for the user to approve; nothing downloaded)

Sizes are the download sizes from Google's SDK manifest (`repository2-3.xml`) and the Adoptium and Gradle
servers, read 2026-10-06. Install under one folder the user names, outside the repo (for example
`C:\Android`). Environment variables would be set per shell call, not system-wide.

| Item | Version | Download |
| --- | --- | --- |
| JDK 17 (Eclipse Temurin, zip, no installer needed) | 17.0.20.1+1 | 182.0 MiB |
| Android command-line tools (`cmdline-tools;latest`, gives `sdkmanager`) | 16111833 | 147.8 MiB |
| `platform-tools` (adb) | 37.0.1 | 7.7 MiB |
| `platforms;android-36` | r02 | 62.8 MiB |
| `build-tools;36.0.0` (AGP 9.4 default) | 36.0.0 | 56.0 MiB |
| `ndk;28.2.13676358` (r28c, AGP 9.4 default, 16 KB aligned by default) | r28c | 713.5 MiB |
| `cmake;3.31.6` (includes ninja) | 3.31.6 | 19.5 MiB |
| Gradle (fetched by the wrapper on first build) | 9.6.0 | 134.2 MiB |
| AGP, Kotlin, Compose, Chaquopy and its Python 3.12 + numpy (Gradle/Maven cache, first build) | | estimated 0.5 to 1 GB |
| **Required total** | | **about 1.3 GB download plus the first-build cache; about 4 to 5 GB on disk once unpacked (estimate)** |
| Optional: `emulator` | 36.x | 434.2 MiB |
| Optional: `system-images;android-36.1;google_apis;x86_64` | r04 | 1,869.7 MiB |
| Optional: `system-images;android-36.1;google_apis_ps16k;x86_64` (16 KB page test) | r04 | 1,825.3 MiB |
| Optional: `extras;google;usb_driver` (Pixel phones on Windows; other brands use their own driver) | | small |

Plus the SDK licenses (`sdkmanager --licenses`), which the user must accept. The x86_64 images also need
the Windows Hypervisor Platform turned on. An arm64 system image on this x86 PC would be far too slow to
judge anything and is not on the list.

A physical arm64 phone with Developer options and USB debugging on is required for every speed number.

## 8. Open questions for the user

1. ANSWERED 2026-10-09: Galaxy S23 Ultra (the slowest phone that should still play is still undecided).
2. ANSWERED 2026-10-09: Spike 0 in Termux first, then the toolchain.
3. ANSWERED 2026-10-09: approved, under C:\Android.
4. OPEN. Distribution: sideloaded APK only. Developer verification (from 2027 globally) means either a verified
   developer account (identity, US$25) or users installing through Android's advanced flow or adb.
