# Android: from "playable" to launcher parity

Status: a plan, first written 2026-10-10 after chunk 7 and updated the same day with the user's decisions. Nothing in
it is built yet. The working method is the one in the khvcemu-workflow skill, section 10: plan, develop, review,
iterate, test, commit, one chunk at a time, on this branch. `android/NOTES.md` stays the log of what was done and
measured; this file says what comes next and why.

## 1. Decided

| Question | Decision |
| --- | --- |
| Distribution | A sideloaded APK only (no Play Store) |
| Orientation | Both portrait and landscape |
| Controls | They are fine. Move the pad and buttons up (the bottom is cut off a little), and make the game's own on-screen buttons tappable (Continue, Save, the shop...) |
| Picture size | A new option: the picture at its original pixel size (176x220) or at the whole-number scale that looks best, as well as filling the screen |
| Frame-locked clock on the desktop | Yes, make it the desktop default (written 2026-10-10; committed on this branch as its own desktop commit) |
| Saves between PC and phone | Yes: the same files in both directions |
| Online sharing on first use | Ask the first time |
| Name and icon | Re:Cast, the project's logo |
| Lowest phone | As widely available as is cheap to make it, but only the user's own phone (a Galaxy S23) really matters: a small measured study near the end, see chunk 16 |

## 2. Where we are

The game is playable on the Galaxy S23 Ultra: the Python core runs inside the app (Chaquopy, Python 3.12, numpy,
Pillow, an ARM-only Unicorn), the picture is drawn, touch controls work, the game's text, images and sound work, it
holds 25 fps, and it pauses when the app leaves the foreground (chunks 1 to 7). What it does not have is everything
around the game: the player has to copy the game files in with `adb`, there is no menu, no way to save or load, no
options, no sound settings, no controls editor, no landscape, no Wonderland pages, no score sharing, no release build.

## 3. What "parity" means here

Parity means a player can do on the phone what the desktop launcher lets them do, in a form that suits a phone. It does
not mean copying the Tk window. Some desktop features have no meaning on a phone and are dropped; some change shape.

| Desktop launcher | On Android | Verdict |
| --- | --- | --- |
| Setup tab: find the game folder, check requirements, install packages | A first-run screen: pick the folder with the game files (Android's folder picker), copy it into the app, check it. No packages to install | Keep, simpler |
| Setup: optional Wonderland theme, Play button, volume | Same, in the same screen | Keep |
| Play tab: Continue card with a preview and the world, Play from the title screen | Home screen with the same card and two buttons | Keep |
| Saves tab: 9 save states and 3 autosaves with thumbnails and dates, load, Start at world (backs up your save first) | A Saves screen with the same list; save and load from a pause menu in the game | Keep |
| Autosave settings: every N minutes, on quit, at loading screens | The same three switches | Keep |
| Options > Window: size | **Picture size**: Whole-number scale (the largest whole multiple of 176x220 that fits, with sharp pixels: the default, since it looks best), Fill the screen (smoothly scaled, as today), and Original (1x: 176x220 real pixels), with a size choice from 1x up | New shape |
| Options > Window: text size, picture filter, smooth hi-res text | Kept. The dark screen is dropped: the area around the picture is already black | Keep, minus dark screen |
| Options > While playing: mute, pause when you click away, ask before quitting | Mute stays. Pausing when the app leaves is automatic and always on. "Ask before quitting" becomes what the Back button does | Change |
| Options > Screenshots: folder, list, preview, delete, F12 | A screenshot button in the pause menu, saved to Pictures; a list with share and delete | Keep, changed |
| Options > Online scores: share on or off, server address | The same switch, asked the first time; the address stays under an advanced option | Keep |
| Options > Speed enhancements: the two 3D speed-ups (and the frame clock) | The same window, with the frame clock as a third switch | Keep |
| Options > Restore default settings | Same | Keep |
| Sound tab: instrument sliders, mixes, saved mixes with favorites, tune player, compare with a recording, use a recording in the game, Advanced (SoundFont, clear cache) | The sliders, mixes, saved mixes, tune player, recordings and Clear cached music. SoundFont needs `fluidsynth`, which Android cannot run | Keep, minus SoundFont |
| Controls tab: change the ten keys | Touch layout editor (size, position, opacity, left or right hand, haptics); physical keyboard and game controller mapping, with the same rebinding screen | Keep, wider |
| Keyboard shortcuts (F5 save, F9 load, F10 mute, F11 filter, F12 screenshot...) | The pause menu, and the same keys when a keyboard is attached | Change |
| Click the game's own buttons with the mouse (the desktop only has keys) | **Tap the game's own on-screen buttons** (the softkey labels, menu entries, shop items) | New |
| Leaderboard posting, play timer, clear times | Already in the core; needs the INTERNET permission and the share switch | Keep |
| Wonderland "lost media" pages | Needs the pygame-based pages redrawn (`lostmedia.py`) | Keep |

## 4. How the pieces fit

- **The core stays Python and stays shared.** The save states (`savestate.py`, `StateSlots`), the autosave rules, the
  clear times, the music settings and the key table already live in `khvcemu/` and have tests. The app should call
  them, not rewrite them. Where a feature's logic is trapped inside `launcher.py` (the option defaults, the config
  file, the screenshot list), move the logic into a plain module first (for example `khvcemu/appconfig.py`) with its
  tests, then let both the Tk launcher and the app use it. Each such move is its own commit, separate from the
  Android UI work, so it can go to `dev`.
- **The app UI is Kotlin.** Jetpack Compose for the screens (Home, Saves, Options, Sound, Setup, Controls), with the
  existing `GameView` (a plain `View`) for the game itself, or a `SurfaceView`/OpenGL view when the picture filters
  need a shader. Compose adds to the APK; to be measured (39.5 MB now; the bar is 60).
- **Files.** Python needs real file paths, so the game files the player picks are copied into the app's private folder
  (about 1.7 MB). Saves and settings live in the app's files folder, with an export and import to the Downloads folder
  (through Android's file picker) for backup, in the same formats the desktop uses, so a save state or a game save can
  move between the PC and the phone.
- **Settings** are one JSON file in the app's folder, read by both Kotlin and Python (the same idea as the desktop's
  `launcher.json`), so the core sees the player's choices without a command line.
- **Nothing copyrighted is bundled.** The game files, the Wonderland theme and the soundtrack recordings are the
  player's own, as on the desktop.

## 5. The chunks, in the order to build them

Each chunk is small enough to check on the phone, ends in a commit, and goes through the two review passes. The first two
fix what the user noticed; then the order removes pain first (no more `adb`), then saving, then the rest.

**Chunk 8, controls polish: keep the pad on screen and tap the game's own buttons.**
Goal: the controls fit and the game's own buttons answer the finger. Steps: lay the controls out inside the system's safe
area (the navigation bar and gesture area: read the window insets, and move the pad and buttons up so nothing is cut
off, on every screen shape); then taps on the picture. The first, certain part: the softkey bars at the bottom of the
game's screen (the left one is Soft 1, the right one Soft 2; they carry Continue, Options, Save, the shop...) press the
matching key when tapped. The second part, tried after the first works: taps on menu entries. The game's own text calls
tell the host where each string is on screen (`Display.text_items`), so a tap can be matched to the entry under it; the
selected entry is found from the highlight bar; a tap on an entry moves the highlight there with Up and Down and a tap on
the highlighted entry presses Action. If the highlight cannot be read reliably on some screens, those screens keep
working with the pad. Checks: on the phone, tap Continue and Options on the intro pages and the pause screen; tap
through the title menu and the Options menu; a fight still plays with the pad; no tap ever presses two things.
Risks: the menu part is a guess until tried; the game draws some lists in different styles (title, options, shop).

**Chunk 9, the first-run flow: game files without `adb`.**
Goal: install the app, open it, pick the game folder, play. Steps: a Setup screen with a folder picker (the system
document-tree picker); copy `mif/`, `mod/` and, if present, `savegame(*).dat` and the Wonderland theme into the app's
folder with a progress bar; check what was copied (the same checks the launcher makes: the two `.mif` files, the two
`.mod` files, and a clear message naming whatever is missing); remember it; skip the screen from then on. A "Remove
game files" action. Checks: a clean install on the phone plays from nothing but the picker; a wrong folder gives a
clear message; removing and re-adding works. Risks: the picker returns content URIs, not paths (copy through
`ContentResolver`); a large folder takes a moment (progress bar, off the main thread).

**Chunk 10, a home screen and the app's settings file.**
Goal: a real front door. Steps: Compose added to the build; a Home screen with the Continue card (the preview of the
newest save and the world it is in, once Saves exist), "Play from the title screen", and entries for the other
screens; the settings JSON and the small shared module that reads and writes it (with the option defaults moved out
of `launcher.py`; tests for it, and the Tk launcher switched to use it); the app opens on Setup when the game files are
missing; the app's name and icon (Re:Cast, the logo; the icon from `khvcemu/assets/recast_icon.png`). Checks: the
desktop launcher tests still pass; the app opens, remembers its last screen, survives rotation and process death.
Risks: the APK grows (measure it); Compose with AGP 9.2 and Chaquopy 17 together (try it in a throwaway build first).

**Chunk 11, saves: the pause menu, the Saves screen, autosave.**
Goal: never lose progress. Steps: a pause menu in the game (the softkeys stay the game's; a small menu button opens ours)
with Save to slot, Load from slot, Quick save and load, Resume, Screenshot, Mute, Quit; the Saves screen with the 9 slots
and 3 autosaves (thumbnail, world, date), load, delete, and "Start at world" with the same warning and backup of the
current save as the desktop; the three autosave kinds (every N minutes, on quit, at loading screens) and their switches;
save a state when the app is sent to the background for good (the `onStop` path) so a killed app never loses the
session; Export and Import of saves to the Downloads folder, in the desktop's formats. Checks: save, kill the app,
load; a state saved on the phone loads on the PC and the other way round (including a state made with the speed
patches on or off); the autosave rotation matches the desktop's (existing tests plus a device run). Risks: Android may
kill the app without a callback (so the timed autosave matters most); a state is 0.5 to 2 MB, so 12 are about 25 MB.

**Chunk 12, Options.**
Goal: the Options screen. Steps: **Picture size** (whole-number scale as the default, fill the screen, and 1x original with
a choice of 1x up to the largest that fits; the picture is centered with black around it, in portrait and landscape; the
scale is a whole number so the pixels stay sharp); picture filter (crisp, smooth, sharp
pixels, Scale2x: crisp and smooth are bitmap filters; sharp pixels and Scale2x need a small shader or a Python-side
upscale, decided by what costs the least frame time); text size and smooth hi-res text (the Pillow font path exists; the
hi-res overlay must be ported from pygame); mute; "Back button asks before quitting"; the screenshot list with preview,
share and delete; the share scores switch (asked on first use, with the INTERNET permission and a clear note of what is
sent); the Speed enhancements window, with the frame clock; Restore default settings. Checks: every option changes the
running game the way the desktop's does; defaults restore. Risks: hi-res text and Scale2x on a phone may not hold
25 fps (measure before promising them); the permission wording must match the website's privacy text.

**Chunk 13, Sound.**
Goal: the Sound tab. Steps: the sliders and mixes (the `music_settings` module is shared already); saved mixes with
favorites; the tune player (renders a tune with the chosen settings in a preview mixer apart from the game's, and plays
it; up to 3 seconds per tune on the phone, so show progress); compare with a recording (the file picker, and turning the
recording into samples without ffmpeg, which Android does not have: Android's `MediaExtractor` and `MediaCodec`, a new
piece); Its volume and Match; Use the recording in the game; Advanced: Clear cached music (no SoundFont, with a line on
why). Checks: the settings reach the game on its next start; a recording replaces its tune with the same length and
looping; Match gives the same level as the desktop within a small tolerance. Risks: decoding long FLAC or MP3 files in
memory; the ffmpeg-free path is new code and the least tested part of the whole plan.

**Chunk 14, landscape, the controls editor and game controllers.**
Goal: both orientations, and controls that are the player's own. Steps: landscape, with the picture on one side and the
controls on the edges (and the picture-size option working there too); a layout editor (drag and resize each
control, opacity, a left or right hand preset, haptic feedback on or off, show or hide the pad); physical keyboard and
game controller support, with a rebinding screen like the desktop's (the key table and its checks are in `keys.py`);
Reset to defaults. Checks: a controller plays the game; a layout survives a restart; landscape and portrait both play,
and rotating mid-game keeps the game running. Risks: controller buttons differ by maker; the feel of the pad needs the
user's thumbs, not only `adb` taps.

**Chunk 15, Wonderland and the online parts.**
Goal: the pieces only the real game flow reaches. Steps: redraw the Wonderland lost-media pages without pygame (the pages
are text and two pictures: Pillow can draw them) and play the Wonderland theme with its volume; the leaderboard post and
the share switch against `scores.khrecast.com` (the core's `web.py` already speaks the protocol; check it works under
Chaquopy and with the phone's TLS); a note on screen about what is shared. Checks: finish the Island on the phone and
see the Wonderland pages, then Agrabah; a posted score appears (use the local server first, the live one only when the
user says). This needs the Island played to its end on the phone, which has not been done.

**Chunk 16, the floor: how widely will it run.** (Small, near the end: the user's own phone, a Galaxy S23, is the
target, everything before this chunk is built for it, and this chunk only widens the net where that is cheap.)
Goal: a measured answer to "how low", and the settings that make a slow phone usable. What is known: Chaquopy 17 needs
Android 7.0 (API 24) or newer, and has numpy and Pillow for 64-bit ARM and x86-64 only on Python 3.12; the 32-bit ARM
phones (`armeabi-v7a`, common on old and cheap phones) are covered only on Python 3.11 and older, which means a second
build of Unicorn for 32-bit ARM and Python 3.11 (the core needs 3.10 or newer, so that is allowed). The only phone on
hand is a flagship, so the first step is data: run the Spike 0 kit (`android/spike/`) on every older or cheaper phone
the user can lend, record the real-time factor and the 3D frame cost, and rank them. Then: (a) decide the lowest Android
version and whether to add 32-bit ARM with Python 3.11; (b) the **steady frame rate** (the frame-locked clock) stays on: a phone that cannot keep up
shows fewer frames at the game's normal speed, because the game still sees real elapsed time between frames (it does
not slow down), so no separate speed mode is needed; an on-screen note when the frame rate stays below 20 is enough; (c) lighter options for weak
phones: a lower sound sample rate, no tune pre-rendering (render on demand), the costly picture filters off, a 15 fps
cap; (d) a "performance" line in the About screen (fps, memory) to help bug reports. Checks: each tier on a phone of
that tier, with the numbers written into `NOTES.md`; nothing here may slow the flagship. Risks: the guest code
(the 3D renderer) is the cost and no setting makes it cheaper; a phone below the line plays in slow motion, and the plan
says so honestly instead of promising it.

**Chunk 17, a release you can hand to someone.**
Goal: an installable, signed, documented app. Steps: a version scheme; a release build with a signing key (the key is
the user's, never in the repo); size work (R8 for the Java side, strip symbols, per-ABI APKs if two ABIs ship); an About
screen with the licenses (this project is GPL-3.0; Unicorn is GPLv2, and the source offer the licenses ask for); a way
to export logs for bug reports; a reproducible build of the Unicorn library (today it comes from Termux: a Linux
container or a CI job that builds it with the NDK, plus the 16 KB page alignment check and an x86_64 build for the
emulator); testing on more than one phone (at least one slower, one older Android, one 16 KB-page device or emulator
image); the README, the website's download card (an Android entry next to the six installers) and the checksums.

## 6. How each chunk is checked

- Anything in `khvcemu/` gets unit tests, and the full desktop suite runs once at the end of the chunk. The desktop must
  not change unless the user said so (the frame-locked clock is the one deliberate exception, decided separately).
- Every chunk is run on the phone, with `adb` for the install and for taps and screenshots, and the log read for
  faults. Things only a human can judge (how the controls feel, how the sound sounds, whether the text is readable) are
  listed in the chunk's notes as "for the user to check" and never reported as verified.
- Frame rate, memory and APK size are measured after every chunk that could move them, against the same bars as the
  spike (25 fps in 3D, under 300 MB, under 60 MB).
- The reviewer agent runs twice per chunk, as always; a third pass only for a break-the-behavior finding.

## 7. Still to settle

Nothing blocks the build. Open for later:

1. **The tap-the-menu idea** (chunk 8, second part) is a guess until tried on the title, options and shop menus; the
   softkey bars are certain.
2. **Older and cheaper phones** (chunk 16): the Android floor (Chaquopy 17 needs Android 7.0, API 24) and 32-bit phones
   wait on measurements from any older phone the user can lend; without one, the app is built and tested for the
   S23 only and says so.

## 8. What could go wrong

- **Speed on weaker phones.** The S23 Ultra is among the fastest of its generation. A mid-range phone may not hold 25 fps
  in 3D, and every added feature (filters, hi-res text, sound rendering) spends frame time. The plan measures after each
  chunk and keeps the costly options off by default; chunk 16 puts numbers on it.
- **Heat over a long session.** Every run so far lasted minutes. A 20-minute test, and a slower phone, come before any
  claim about it.
- **The build.** Kotlin, Compose, Chaquopy and the NDK in one Gradle project is a lot of moving parts; the Unicorn library
  still comes from Termux; Python 3.12 and numpy 1.26 are pinned by Chaquopy's wheels.
- **Licensing.** GPLv2 (Unicorn) inside a GPL-3.0 project in an APK needs settling before anything is handed out.
- **Android decides to kill the app.** Anything that must survive (a save) is written as soon as it can be, not on exit.
- **What I cannot verify from here:** sound quality, the feel of the controls, readability of text on other screens,
  other makers' phones. Those are listed for the user to check, chunk by chunk.
