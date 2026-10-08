# Android port: running notes

A log of what was tried, measured and decided, so no session redoes it. Newest entries first in each
section. Nothing here has run on Android yet.

## Status (2026-10-06, step 1: planning)

- No Android toolchain on the development PC, no device attached. Nothing installed, nothing committed.
- Desktop baseline measured (below). The cost is the guest's own ARM code (the Swerve renderer)
  running in Unicorn, not the Python HLE layer.
- Recommendation: keep the Python core, run it on Android with Chaquopy, Unicorn as a native library,
  Kotlin front end. Waiting for the user: which phone(s), and approval of the install list.

## 1. This machine (checked 2026-10-06)

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
  `execmem`. To confirm on a device at targetSdk 36, with `adb logcat | grep avc`.
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

None yet. (Device, Android version, numbers, failures and why.)

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

1. Which phone(s)? Model and Android version, and which is the slowest one that should still play.
2. Approve Spike 0 (Termux on the phone) first, or go straight to the Spike 1 install list?
3. Approve the install list and name the folder.
4. Distribution: sideloaded APK only. Developer verification (from 2027 globally) means either a verified
   developer account (identity, US$25) or users installing through Android's advanced flow or adb.
