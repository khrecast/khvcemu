# The game, its files and its music

Background for anyone working on the files or the emulator. Facts here come
from public community sources (linked); anything marked *inferred* is our own
reading of the evidence. Nothing in this repository contains the game's files.

## The game

*Kingdom Hearts* (2005) is a Qualcomm BREW phone game for Verizon V CAST,
built by Superscape on its Swerve 3D engine for Disney Mobile. It was sold as
separate chapters, and a phone held **one chapter at a time**: finishing a
chapter made the game download the next one over the network and delete the
old one. The download server is long gone.

| Chapter | State |
|---|---|
| 1. Obstacle Course and Swashbuckler's Island | Recovered |
| 2. Alice in Wonderland | **Lost** (see below) |
| 3. Agrabah | Recovered |
| 4. Maleficent's Castle | Recovered |

## Where the files came from

Chapters were dumped separately by different people ([Lost Media Wiki][lmw],
[KHwiki][khwiki]):

- Chapter 1: 4chan user "Wedge", 2016 ([KH13 news][kh13]); mirrored on the
  [Internet Archive][ia] in 2018.
- Agrabah: KHInsider user "Cbajd5", 2018.
- Maleficent's Castle: "Eriyu" and "kraze1984", 2022.

The community "mega dump" is these separate dumps merged into one folder
(*inferred*; no source documents how it was assembled). That is why khvcemu
sees all surviving chapters at once, and why it protects those files from the
game's own "delete the old chapter" step.

## Wonderland is lost media

No copy of chapter 2's files is known to exist. What survives is what the
other chapters carry: Jiminy's journal entry (`ro_wonderland_jtext.m3g`), the
splash image, two screenshots from the time, and the composer's MIDI of its
theme. khvcemu bridges the gap (see the README), and appeals to anyone who
might still have the chapter on a phone. If that's you, please don't reset the
phone: email **khrecast@gmail.com** so the files can be dumped safely.

## The music

Composer: Ian Livingstone, credited in game as "Music and Sound by MTS -
Mediathemes & Sound" ([KH Database][khdb]). He wrote the pieces in 2004
without playing the game (he saw only a few screenshots) and said memory was so
tight that they had to be very short ([interview in the description of 13th
Vessel's soundtrack video][13v]).

The game's data has nine MIDI files, one loop per world plus short stingers:

| File | Track | When the game plays it |
|---|---|---|
| `training.mid` | Obstacle Course | Title screen, and the tutorial world's splash |
| `island.mid` | Swashbuckler's Island | The Island's splash screen |
| `agrabah.mid` | Agrabah | The Agrabah splash screen |
| `castle.mid` | Maleficent's Castle | The Castle's splash screen |
| `death.mid` | Death music | On defeat |
| `keyblade`, `good`, `bad`, `magic_alert` `.mid` | Stingers under 5 s | Game events |

A Wonderland theme existed (`wonderland.mid`) but is not in any dump; two
further unused alternates (Island and Castle "v03") never shipped.
[Aid1043's 2025 "Authentic Restoration" soundtrack][ost] renders the original
MIDIs through a Qualcomm CMX 4.1 soundfont, which is a faithful reconstruction
rather than a phone recording.

### Is there music during levels?

**No, on a real phone the levels are silent.** We traced the game's code and
scripts: it plays MIDI only on the title screen, on each world's splash screen
(looping it itself by restarting the tune when playback ends), and for the
death tune and stingers. When a scene loads, the game stops the music and
never starts any until the next splash. Footage of the Castle level on a real
phone matches (Negative Space's 2022 video). The long guitar/drum tracks heard
under the Zeebo longplay of Agrabah are not part of the game's data and were
added outside it.

### Emulating it

BREW leaves how many sounds can play at once to the device. khvcemu follows the
single-MIDI-player behavior of phones of the time: starting a tune stops any
other MIDI (with an "aborted" notification), while the short `.pmd` sound
effects (QCELP audio in a CMX wrapper) mix freely. The built-in synth is an
approximation; `--soundfont` with fluidsynth gets closer to the phone.

## Other platforms

The game was never an official Zeebo release. A collector (KrZ One) runs the
phone version on real Zeebo hardware with modifications, and an Android
emulator (Melange) can run it without audio. khvcemu is, as far as we know,
the first emulator to play the game with sound in context.

[lmw]: https://lostmediawiki.com/Kingdom_Hearts:_V_Cast_(partially_lost_mobile_game;_2005)
[khwiki]: https://www.khwiki.com/Kingdom_Hearts_V_CAST
[kh13]: https://www.kh13.com/news/kingdom-hearts-v-cast-code-released-including-various-screenshots-audio-files-more/
[ia]: https://archive.org/details/KingdomHeartsVCastChapter1
[khdb]: https://www.khdatabase.com/Forum:Note_05:_Game_Credits_(KH_VCast)
[13v]: https://www.youtube.com/watch?v=__ZbGHQslmw
[ost]: https://www.youtube.com/watch?v=Kmpcy8NgJ6c
