# Android port: running notes

A log of what was tried, measured and decided, so no session redoes it. Newest entries first in each
section. Spike results and the first app run on the phone are in section 6 and Chunk 3.

## Status (updated 2026-10-10: chunks 1 to 4 done; next is drawing the picture and touch input)

- Toolchain installed under C:\Android (Chunk 2). The test phone is connected over adb. Spike 0 passed on it
  (section 6) and a probe APK at target SDK 36 runs Unicorn on it (Chunk 3).
- Desktop baseline measured (below). The cost is the guest's own ARM code (the Swerve renderer)
  running in Unicorn, not the Python HLE layer.
- Recommendation: keep the Python core, run it on Android with Chaquopy, Unicorn as a native library,
  Kotlin front end. Chunk 4 proved it: the core boots to the title inside the app on the phone at about 1.7 to 1.8x real time.
  Next: show the frames on screen and take touch input (chunk 5).

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
