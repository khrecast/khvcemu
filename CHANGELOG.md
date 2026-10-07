# Changelog

## Unreleased

### New
- **The Options tab is redesigned, and autosave is split in three.** Settings now sit in boxes (Window, While playing,
  Screenshots, Online scores, Speed-ups) in two columns, and the "Window size note" box and its title are gone: its tip is one
  small gray line under the size choices. Autosave is three separate options: every N minutes (type the number; 1 to 120,
  default 5), when you quit, and at loading screens; F8 in game says which are on. Command line: `--autosave-every MINUTES`
  (0 turns the timed ones off), `--no-autosave-on-quit`, `--no-autosave-on-loading` (`--no-autosave` still turns them all off,
  and a launcher setting from before the split that had autosave off keeps all three off). New: the screenshot box lists the
  pictures in the screenshot folder (newest first, by the time they were taken) with a preview of the one selected, and small
  icons instead of text buttons: a folder to choose the folder, a picture to open the selected one and a folder to open the
  folder (double-click opens one). The launcher window is a little taller (692 px, was 649) and the four website launcher pictures
  were retaken (the site files are changed, not deployed).
- **Agrabah's twangy rhythm part can be heard.** The "parapa pa pa pa" part that lands with the bass is a koto in
  the game's MIDI, and the built-in synth played it as a soft harp that the strings buried (it carried about a tenth
  of the sound between 600 Hz and 2.4 kHz). Banjo, koto, shamisen and sitar (the four picked instruments, GM 104 to
  107) now have their own voice: bright, dry, short, with a pick click. Measured against the authentic recording of
  Agrabah, the whole tune's balance between 300 Hz and 9.6 kHz is much closer (squared error 40 dB to 11 dB), and
  the part now holds between a third and three fifths of the energy from 600 Hz to 4.8 kHz instead of about a tenth.
  Only the koto (GM 107) is used by the game, so no other tune changes; the Harp and guitar slider on the Sound tab
  controls it. Measured, not heard: please listen, and tell me if it is too loud or too sharp (the knobs are the
  TWANG_ constants).
- **Faster 3D: three speed-ups for the game's 3D engine, same picture.** In memory only, and only when the game
  module is byte for byte the known one. (1) A tighter version of the function that fills a row of a polygon
  pixel by pixel (about half of the game's work in some scenes): same pixels in about half the instructions,
  checked on 3,000 random rows. (2) A cache for the 4x4 matrix inversion the engine repeats hundreds of times a
  frame on a few hundred different matrices: the key is all 17 input words, so an answer is exactly what the
  original would have computed (checked on 1,500 random calls). (3) A shortcut for the engine's soft-float
  reverse subtract, which runs half a million times a second, mostly with a zero operand (bit for bit the same
  result on 60,000 random operand pairs, odd ones included; it gains only about 1%). A whole scene gives the
  same picture frame by frame with and without them. On the build machine the Island's opening scene went from
  about 21 to about 25 frames per second and a walking scene from about 21 to about 23. The Options tab has a
  checkbox for each ("Faster 3D fill", "Matrix cache", "Float shortcut"), `--no-speed-patch[=span,matinv,float]`
  turns them off, and the website's launcher pictures were retaken. Needs an installer rebuild to ship.
- **Website: the search for Wonderland is now the top goal.** A gold banner above the hero, a "Find Wonderland"
  item first in the menu, and a new section right after the hero ("Do you still have the phone?") with a
  checklist, the phone models and two screenshots; the old section at the bottom is gone. The phone date range is
  now "the V CAST years (2005 to 2012)" on the website and in the README, and the splash screen in the game no
  longer says "since 2007". Needs the website deployed (and an installer rebuild for the splash wording).
- **A stats dashboard button, and more detail in the website counters.** `tools/show_site_stats.bat` opens a page in your browser with the visits per day, time of day, where visitors came from, countries,
  kinds of computer, how far down the page people got, and clicks. The counters now also tally, as separate counts
  kept apart and never stored per visit (on a very quiet day they could still be matched up by eye), each main-page opening's hour, country (Cloudflare's coarse location, no address kept),
  kind of computer and referring website (its name only, from a fixed list), and which section of the page was
  scrolled to. The footer says so. Needs the server and the website deployed.
- **Faster loading: the music is rendered ahead of time.** The built-in synth used to build each tune the
  first time the game played it, which froze the game for about a second or two at the title screen and at
  each world's start (the title tune took 1.9 s). Now all the tunes are rendered in the background as the
  game starts, and kept in an `audio_cache` folder (about 3.5 MB) next to your saves, so from the second
  launch on the title tune is ready in a few milliseconds. The cache is rebuilt by itself when a tune, the
  Sound tab settings or the synth change, and it is safe to delete. The rest of loading is the game's own
  code and is unchanged.
- **The Stop buttons say so.** On the Sound tab, Stop now shows "Music stopped." (or "Nothing is playing.")
  in the line at the bottom of the launcher, and the Wonderland theme's Stop shows "Wonderland theme
  stopped."; before, the line kept saying "Playing...".
- **Anonymous website counters.** The website now counts, per day, how often its pages are opened and
  which buttons are clicked (the downloads per platform, the source and issue links, the soundtrack
  link), so the author can tell whether anyone uses it. No cookies, no addresses, nothing about the
  visitor is kept by the project's server, browsers that send Do Not Track or Global Privacy Control are not
  counted, each count has a daily ceiling, and the footer says what is and is not kept (Cloudflare, which hosts
  the site, still keeps its usual logs).
  `python tools/site_stats.py` shows the totals. Needs one new table on the server
  (`server/migrate_002_site_stats.sql`) and a server and website deploy.
- **Leaderboard score ceiling raised from 250,000 to 1,000,000**, to see how far people get when
  they farm enemy waves for EXP before deciding on lower limits. Needs the server deployed.
- **Leaderboard minimum run times are now set per world** from real first clears: Island 6 minutes,
  Agrabah 10, Castle 8 (all were 3 minutes). Runs under the minimum are still turned away silently.
  Needs the server deployed (`cd server && npx wrangler deploy`).
- **Needs pygame-ce 2.5 or newer** (the dark screen option uses its multi-window support); the
  requirements and package metadata now say so. Without it everything else still works.
- **Autosaves show a small floppy disc** in the bottom-left corner instead of an "Autosaved" message
  across the top, which covered the dialogue now that autosaves are more frequent. Manual saves still
  show their message.
- **Autosave when you enter a new area.** About 3 seconds after a "Loading..." screen ends, the game
  autosaves (not within 30 seconds of the last autosave, only if you have pressed a game key since the last save).
  Saving by hand (F5) no longer restarts the 5-minute autosave timer, which could keep autosaves
  from ever happening for people who save often, and a failed autosave now waits before trying
  again instead of retrying constantly. Still three autosaves kept.
- **"Don't ask me again" for the quit question.** In the "Quit the game?" box, **D** quits and turns the
  question off for good; the Options tab has an "Ask before quitting (Esc / X)" checkbox to turn it back
  on (`--no-quit-prompt` on the command line). Autosave on exit still happens.
- **A paused game says so.** When the game is held still because its window lost focus, the picture
  dims and a "PAUSED - Click the window to continue" box shows, so a paused game never looks frozen.
- **Dark screen option.** The Options tab's "Dark screen" (`--dark-screen`) blacks out the rest of
  the monitor the game window is on, behind the window, for playing without distractions.
  Clicking the black area just brings the game back to the front; minimising the game removes it;
  the game window's X button still asks "Quit the game?".
- **F12 tells you where the screenshot went.** A small "Saved: ..." message shows at the top of
  the window (or "Screenshot failed"). Screenshots now go to a `khvcemu` folder in your Pictures
  folder by default (the current folder if there is none), and the Options tab has a
  **Screenshots (F12)** folder setting (`--screenshots DIR`); the folder is made if it is missing.
- **The Setup tab checks for the Wonderland theme.** It is optional and not in the game's files,
  so the installers bring it but a copy of the repository does not; Setup now says whether
  `wonderland/Wonderland.flac` (or .mid, .ogg, .wav, .mp3) is in the game folder and where to put
  it, without marking Setup with "(!)". When it is there, a **Play** button and a **Volume** slider
  (0 to 200%) play it in the launcher, and the same volume applies in the game on the Wonderland
  screen (`--wonderland-volume X`, written by the launcher).
- **Website and tools.** The website (live at khrecast.com) gains a "The launcher" section with
  screenshots of the Play, Saves, Options and Sound tabs, a Leaderboard link in its menu, and
  in its music section a link to the soundtrack's audio files on KHInsider, with how to play
  them in the game instead of the built-in synth (Sound tab, Use the recording in the game);
  its source-code and issue links are inactive until the code is published.
  `tools/launcher_screenshots.py` (Windows) retakes the launcher screenshots from a temporary
  profile, so they show no personal paths or settings. `site-deploy/` holds the website's own
  Cloudflare config, kept apart from the leaderboard server's. Until launch the site is behind a
  password splash page ("Coming soon", a Cloudflare Worker, `site-deploy/gate.js`, with tests);
  every other page, picture and the leaderboard page are only served after the password. The website's Controls table now
  has the same twelve entries and keys as the launcher's Controls tab (a test keeps them in
  step), and its "Why is the music a bit odd?" answer was removed. The top menu is a
  "Menu" drop-down button below 1000 px wide (it was hidden on small screens).
- **The launcher's tab names are in the Kingdom Hearts menu font**, blocky like the Re:Cast title:
  drawn small, in silver with a dark outline, then doubled with hard pixel edges, and brighter
  on the selected tab ("Setup (!)" too). The font is KHMenu, recreated by Televo for "Kingdom
  Hearts Re:Collection", now credited on the website, in README and in docs/CREDITS.md; only the
  pictures are included (`khvcemu/assets/tabs/`, made by `tools/make_tab_labels.py`), not the
  font. If the pictures are missing the tabs fall back to plain text.
- **Mixes, saved mixes and your own recordings in the Sound tab.**
  - **Ready-made mixes** to switch between: As tuned (every slider at 100%), More bass, Bright
    and crisp, Big brass, Soft and warm, Quiet background.
  - **Your own mixes:** Save as... keeps the current sliders under a name; a star marks
    favorites, which are listed first; Delete removes one. Moving a slider shows "Custom
    (unsaved)".
  - **Grayed-out sliders look off:** a slider that does not apply (a SoundFont or an in-game
    recording is in use) is dark, a live one is light.
  - **The comparison recording** gets its own volume, and Match sets it to the built-in synth's
    level (done automatically when you choose one; the recordings are often mixed much quieter).
    Match never aims below a standard level, so a recording of a tune the synth renders quietly
    (Swashbuckler's Island) is not left quieter than the others.
    The button of whatever is playing is lit.
  - **Use the recording in the game:** a tune can play your own recording instead of its MIDI
    (`--music-file NAME=PATH`, `--music-file-volume NAME=GAIN`; your file, never bundled). It is
    cut (with a short fade) or padded to the length the MIDI renders to (a looping tune is cut at
    the MIDI's own end, so the start of the recording's next loop is never heard), so everything
    the game times by the tune, its looping, and save states, is unchanged, whatever the
    sliders are set to. A recording made from the same MIDI that starts at the same moment
    should loop seamlessly. Recordings are played at the game's 22.05 kHz mono (stereo is mixed
    down). Volume, mute and Music volume apply; a missing or unreadable file falls back to the
    MIDI (and is tried again once the file is changed).
  - The launcher grows from 595 to about 619 px tall for the extra rows.
- **Punchier Swashbuckler's Island horns, round two.** Measured at the stabs against the
  recording, ours had about 5 dB too little low thump (the timpani under every stab) and about
  6 dB too little bite above 2.4 kHz (a horn note only had eight partials, none above 1.5 kHz).
  The timpani is now twice as loud and rings a little longer, and horns have 20 partials, a
  brighter roll-off and a short bright burst at the start of each note. At the stabs every band
  is now within about 1 dB of the recording except 600 to 1200 Hz, which is still about 3 dB
  heavy (it comes from the strings, not the horns, and was left alone). Other tunes are
  unchanged to within 1%, except the short "bad" jingle (5% quieter). The **Brass and horns**
  and **Drums and timpani** sliders scale it.
- **The title tune's melody no longer clicks.** It sounded like "pop in, pop out" where the
  recording is a smooth, sustained, nearly pure tone that sits at the front. The hammer tick
  that every piano note starts with had 10 to 14 dB more bright energy than the recording in
  the first 40 ms of each melody note; it is now limited to the lower partials and fades above
  500 Hz, the upper partials of high notes fade a little, and the melody range (around 880 Hz)
  is lifted by about 40%. Against the recording the click is within 1 dB, and the overall
  band-by-band fit improved (0.43 to 0.40). The melody is a piano part in the game's file (there
  is no flute in it), so the **Piano** slider controls it, not Flutes and reeds. The lower
  chords keep their tick, which is what rescued the quiet chord of "duh duh di". Measured, not
  heard: the notes' endings ("pop out") were not separately checked.
- **Munny, EXP and Level on the leaderboard, and a top 100.** The game's Summary screen shows
  the Munny, EXP and Level a score is made of (Score = Munny + 100 x EXP). The emulator now
  reads them off that screen as the game draws it, and sends them with the score (`mn`, `ex`,
  `lv`) only if they add up to exactly the score that is being posted. The shared server stores
  them, silently drops a post whose numbers do not add up (a free extra check on top of the
  score ceiling, the minimum run time for each world and the rate limit), and `/top` now returns the best
  100 per world, each with its time, Munny, EXP and Level (older scores show dashes). A new
  page, `site/leaderboard.html`, shows it as one table per world: a scrolling top 100 with a
  fixed header. The database needs `server/migrate_001_stats.sql` run once, and the worker
  deployed; installers built before this keep working and just post without the numbers.
- **A speaker icon when you mute or unmute (F10).** The game is mostly silent apart from a few
  effects and some screens' music, so it was hard to tell whether F10 had done anything. A
  speaker now flashes in the top-right corner for a moment, crossed out in red when sound is
  off and with sound waves when it is back, like the autosave notice.
- **"Auto" window size stops at 2x.** It used to pick the largest window that fits the desktop
  (up to 4x), but the game was made for a tiny phone screen and looks best small. The launcher
  still offers 3 and 4, and the window can be dragged bigger.
- **Restore default settings (Options tab).** One button, with a confirmation, puts the options
  back as they were at the start: window size, text size, mute, hi-res text, picture filter,
  autosave, and score sharing and its address (in case the leaderboard address was mistyped).
  Saves, the game folder and everything on the Sound tab (sliders, mixes, recordings and the
  SoundFont) are left alone.
- **The SoundFont moved to an Advanced... window on the Sound tab.** The window explains what
  a SoundFont is and how to use one: it only does anything when the free `fluidsynth` program
  is installed, which none of the installers include, so its box is grayed out with a note when
  fluidsynth is missing (it used to be accepted and silently ignored).
- **What does not apply is grayed out.** A SoundFont, or a recording used in the game, replaces
  the built-in synth, so while one is in use the instrument and character sliders and the
  mixes are grayed out (Music volume always applies; a recording only for its own tune), and
  the note under the sliders says why.
- **A Sound tab in the launcher for tuning the music.** Sliders for the volume of each
  family of instruments (piano, strings, brass, harp and guitar, bells, flutes, pads, bass,
  drums) and of the music as a whole, and for the character of the sound: piano hammer,
  piano tail, horn note length, bass cut and high-note softening. Pick a tune and press Play
  to hear it in the launcher; while it plays, letting go of a slider plays the change (a tune
  takes a second or two to prepare). 100% everywhere is the sound as tuned, sample for sample. You can also
  choose a recording of a tune (your own file) and switch between it and ours to compare.
  The sliders are saved with the other options and the game uses them when it next starts;
  on the command line they are `--music "piano=0.8,bass_cut=1.5"`. With a SoundFont in use
  (fluidsynth installed), only the music volume applies in game. The tab keeps the launcher the same height.
- **A softer, rounder main-menu tune.** The title music (`training.mid`, which Aid1043's
  restoration calls "Obstacle Course") sounded like pings on every beat, and the quiet chord at
  the end of each "duh duh di" figure was lost. Piano notes now start with a short hammer strike,
  have a rounder tone, and play their top octave (the melody's high doubling) much quieter, the
  way a SoundFont render does; the piano as a whole sits lower, its low notes and low harp
  and guitar notes are lighter (the bass was boomy), and the celesta and pad sit lower too.
  Fitted against that render: the lost chords went from about 60% to 100% of the recording's
  strength, and the bass-to-treble balance is now within about 2 dB of it in every octave
  (it was up to 5.5 dB too bassy). The other tunes were checked for level, not against
  recordings: most are within about 10% of before, Agrabah is about 15% quieter and the short
  "good" jingle about 30% louder, so Castle, Agrabah and the jingles may sound slightly
  different. The Island tune's bass was already a little lighter than its recording and is
  unchanged.
- **Punchier horns in the built-in synth.** The Swashbuckler's Island opening ("BA BA BA... BA!")
  had its horn stabs sitting faded behind the strings. Horn and brass notes now have a shorter
  tail and a quicker settle, and section strings come in faster, so the stabs stand out the way
  they do in a SoundFont render of the same file (measured against one: the stabs' peak over the
  average level went from 1.4x to 2.2x, the reference is 2.0x). The other eight tunes were
  checked for level and length, and are about the same loudness.
- **A game window that opens behind another one pauses too.** Windows only reports losing
  focus, never starting without it, so a window that opened unfocused ran until you clicked it.
  The window now checks once, a second after it opens, and holds the game until you click it.
- **Every finished world is logged to `clear_times.csv`**, not only scores the game posted
  (a run that does not beat your best never offers to post). Rows now say whether they are a
  `clear` or a `post`; an older file is upgraded in place and keeps its rows.
- **The launcher's Saves list highlights the newest save** as you make them, until you pick a
  row yourself; after that your choice is kept.
- **The game pauses when its window loses focus.** Alt-tabbing away or minimizing now holds
  the game still (clock, keys and audio) until you come back, so time away never counts as
  play time or as clear time. Before, only the Esc quit prompt paused it. It is an option: the
  Options tab's "Pause when the window loses focus" (on by default; `--no-focus-pause`).
- **The launcher follows the game's save states live.** Saving a state in the game (F5, or an
  autosave) now shows up in the launcher's Saves list and Continue card within five seconds, or at once when you click the launcher, with
  the slot you picked kept selected. It used to refresh only when the game closed.
- **The launcher is split into tabs** (Play, Saves, Options, Setup, Controls) instead of fold-away
  sections, so the window is about 595 px tall instead of 730 with everything folded and
  1378 with everything open. It reopens on the tab you used last, and opens on Setup, marked
  "Setup (!)", when the game folder or a requirement is missing.
- **Single-file installers for Windows (64-bit and 32-bit), macOS (Apple Silicon and
  Intel) and Linux (x86-64 and ARM64).** `python tools/build_installer.py [--target win32]`
  makes a self-extracting Windows exe (about 56 MB / 43 MB), `python tools/build_mac.py`
  makes zipped macOS apps (about 81 MB / 86 MB) and `python tools/build_linux.py` makes
  self-extracting `.run` files for Linux (about 105 MB / 93 MB), each containing Python,
  the libraries, ffmpeg, khvcemu and the game files. The Windows ones install per user (no administrator rights), add
  Start Menu and desktop shortcuts and an Apps entry, and uninstall cleanly. A `bin`
  folder next to the game is now put on PATH, which is how the bundled ffmpeg is found.
  Both Windows builds were tested on a clean profile with the system Python and ffmpeg
  hidden (the 32-bit one runs under Windows' 32-bit mode). The macOS builds are checked
  for the right CPU in every compiled file but have not been run on a Mac. The Linux
  x86-64 installer was tested in clean Ubuntu 20.04 and Debian 10 containers.
- **Clear times.** The emulator now times each world (`khvcemu/playtime.py`): the game's clock
  while the world is on screen, unaffected by pausing or save states, ended by the Summary
  screen. Scores posted are logged with their time in `clear_times.csv`, and the measured time
  is sent to the shared leaderboard, which turns away runs under a minimum time for the world (Island 6 minutes, Agrabah 10, Castle 8), ranks equal
  scores by the faster time and shows each time on the web page.
- **A public leaderboard on the web page.** The shared leaderboard server gains `GET /top`
  (the best ten scores per world, anonymous), and the page shows them in a Leaderboard
  section. Scores above 250,000 are now refused (the limit was 10,000,000, far too loose).
- **A window icon.** A blue heart (drawn for this project, not taken from the game) shows on
  the launcher and the game window and in the Windows taskbar. `python tools/make_icon.py`
  redraws it.
- **A new look for the launcher.** Dark theme in the game's blue and green, and a
  front card showing where you left off: a snapshot of your newest save, the world
  you are in, and a big **Continue** button that resumes it. "Play from the title
  screen" sits beside it. Game folder, requirements and the save list start folded
  away so the whole window fits on a normal screen. The header shows the Re:Cast
  logo (`khvcemu/assets/recast_logo_lowres_hardpixels.png`), or a text header if that
  file is missing.
- **macOS and Linux launcher scripts:** `Launch khvcemu.command` and
  `launch-khvcemu.sh`, the counterparts of the Windows `.bat`. They find Python
  and tell you how to install tkinter if it is missing. Not yet tried on a Mac or
  a Linux machine.

### Verified
- **A full human playthrough is complete:** the tutorial, the Island, Agrabah and
  the Castle, played by hand to the end in the emulator.

### New
- **Offline high scores.** "Post it to the server and get a ranking?" works
  again: khvcemu answers the game's `rank.php` and `rankex.php` requests from a
  SQLite file (`leaderboard.db`) in the data folder. The Summary shows the
  rank, and the Score screen's Update refreshes the ranks. Implements the
  game's IWeb calls (`web.py`, `leaderboard.py`) and the `STRCHREND` helper.
- **Z opens the Status screen** (health, magic, stats; **Next** lists your
  items, potions and munny). It is an alias for the phone's `0` key, which was
  the only way in and wasn't documented.
- **Picture filters.** Choose how the 176x220 picture is enlarged: crisp
  pixels (the default, unchanged), smooth (bicubic, not blurry), sharp pixels (even-width blocks, best
  at odd window sizes) or Scale2x (rounded edges without blur). `--filter`, the
  launcher's **Picture** option, or F11 in game to cycle through them. Works
  alongside hi-res text.
- The launcher has a **Controls** section listing the in-game and emulator
  keys. Every launcher section (Game folder, Requirements, Controls, Play,
  Options) now folds away when you click its title, and each one remembers
  whether it was left open.
- **An optional shared leaderboard** (`server/`): a small Cloudflare Worker that
  answers the same two requests, so scores can be ranked against other players'.
  Off by default; turn it on in the launcher's Options or with `--leaderboard
  URL`. Scores are always kept offline too and are used whenever the server
  can't be reached. It has no accounts and stores nothing identifying, because
  the game only ever displays a rank number.
- The Download screen (dead episode server) still ends in the game's own
  "network is not available" message.

### Fixed
- **Smooth hi-res text (`--hires-text`) left ghosts behind.** A string the game
  had stopped drawing ("Loading.....", a dismissed dialog) could stay on screen,
  usually as a blocky low-res outline. It happened when the next screen was the
  text's own color where the glyphs had been: they still "matched", so the old
  background was pasted back in glyph shape. A second form showed in the shop:
  after buying a potion, "restores your" from the item description stayed drawn
  over the list's black selection bar. A string is now kept only if its whole box
  still looks exactly the way it did when drawn (the background it was on, with
  the glyphs on top).
- **Renaming or moving the game folder no longer looks like losing your saves.**
  The data folder is named after the game folder; when it holds nothing and
  exactly one other save folder exists, that one is used (nothing is moved or
  copied). With several, khvcemu names them in the log rather than guessing.
- A black console window flashed briefly the first time a sound effect played
  (for example the jump on Action): ffmpeg, used to decode `.pmd` effects, was
  started without hiding its window on Windows.

## 0.2.0: Kingdom Hearts Re:Cast

The project is now **Kingdom Hearts Re:Cast** (`khvcemu`, previously `khemu`).

### Renamed
- Python package `khemu` is now `khvcemu` (`python -m khvcemu`), and the
  per-user folder `~/.khemu` is now `~/.khvcemu`. An existing `~/.khemu` is
  copied over automatically on first run (the old folder is left alone), and
  save states made by the old name still load.

### New
- **Launcher** (`Launch khvcemu.bat` or `python -m khvcemu.launcher`): finds the
  game folder, installs requirements, play / resume a save state / start at a
  world, remembered options.
- **Save states**: F5 save, F9 load, F6/F7 or Shift+1-9 to pick slots 1-9,
  autosave every 5 minutes and on quit (F8 toggles), `--load-state`.
- **Wonderland bridge**: after the Island the game shows its surviving
  Wonderland journal and splash screen (with the Wonderland theme if you
  provide one), two pages about the lost chapter, then continues to Agrabah.
- Esc asks "Quit the game?" before closing.
- WASD for movement, F for magic, Q / E for the softkeys (the original keys
  still work).
- Automatic backups of `savegame.dat`, `replaygame.dat` and `scoredata.dat`
  before they are changed; `--start` warns before replacing a save.

### Fixed
- Sound played twice as fast and an octave high on devices that open a stereo
  mixer (most Windows PCs); music volume was applied twice on repeats.
- Only one MIDI plays at a time, like a phone (the title music no longer plays
  underneath a world's splash tune).
- The HUD emblem showed only its left half.
- A much better built-in MIDI synth (pitch bend, sustain pedal, real
  percussion and instrument voices).

### Changed
- Text is drawn at the phone's 176x220 by default (the smooth hi-res text is
  now the experimental `--hires-text`); the default font is Verdana.

## 0.1.x

First public MVP as `khemu`: boots the game, 3D, audio, chapter flow.
