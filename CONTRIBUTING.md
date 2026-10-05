# Contributing to Kingdom Hearts Re:Cast (khvcemu)

Thanks for helping preserve this game. Bug reports, fixes, documentation and
research on the original game are all welcome.

## Ground rules

- **Never commit or attach game files.** That means `mif/`, `mod/`, `.m3g`,
  `.mid`, `.pmd` and `.png` assets from the game, the game's save files, and
  any recordings of its music. `.gitignore` keeps the usual places out of git;
  please double-check `git status` before you commit. Bug reports should
  describe the problem and include the terminal log instead.
- Keep your own dump in a folder outside your checkout if you can.
- By contributing you agree your work is released under the project's
  [GPL-3.0 license](LICENSE).

## Getting set up

```
git clone https://github.com/khrecast/khvcemu.git
cd khvcemu
python -m pip install -r requirements.txt
python -m khvcemu path/to/your/dump          # run the game
python -m unittest tests.test_units tests.test_music_settings tests.test_music_mixes   # unit tests, no game files needed
```

You need Python 3.10 or newer and `ffmpeg` on your PATH (for sound effects).
`tools/disasm.py` and `tools/xrefs.py` also want `capstone`.

## Tests

- `python -m unittest tests.test_units` runs in under a second and needs no
  game files. CI runs it, with the other tests that need no game files
  (`test_music_settings`, `test_music_mixes`, `test_playtime`, `test_shared_leaderboard`,
  `test_launcher_states`, `test_checksums`), on Linux and Windows.
- `KH_DUMP=path/to/dump python -m unittest tests.test_game` plays the real game
  headless (about 5 minutes). Run it when you change emulation behavior (CPU,
  BREW interfaces, display, audio, save states). It is not run in CI because it
  needs the game files.

## Code style

- Match the surrounding code: type-hinted where it helps, short comments that
  explain *why* (the game does X, so we do Y), no heavy abstractions.
- The BREW interfaces are reimplemented from what the game actually calls.
  When you add one, log unimplemented calls with the existing `[unimpl]`
  mechanism instead of guessing silently, and say in a comment where the
  behavior was inferred from.
- A bug fix should come with a unit test where the logic can be tested without
  the game, or a note about how you checked it against the game.

## Where things are

See "How it works" in the [README](README.md) and
[docs/PRESERVATION.md](docs/PRESERVATION.md) for the history of the game and
its files.

## Reporting a security problem

See [SECURITY.md](SECURITY.md).

## Contact

khrecast@gmail.com
