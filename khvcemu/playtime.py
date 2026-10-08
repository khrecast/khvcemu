"""How long a world took, as the emulator sees it.

The game's own time value (the `t` it sends with a score) is a running clock, not a
completion time, so this measures it directly: the emulated game clock, counted while a
world is on screen. That clock already stops while the window is paused and is not
rewound by loading a save state, so time is never lost or gained by those.

* A world starts counting when the game opens its file (island.m3g and so on), or when a
  save state that was taken inside it is loaded.
* The Summary screen ends the run: the time so far is kept as that world's last clear and
  the count restarts from zero for the next run.
* The same Summary screen shows the Munny, EXP and Level behind the score (Score = Munny +
  100 x EXP). They are read off the screen as the game draws it, each number being the text drawn
  next to its label on the same line, and sent with the score so the shared leaderboard can show
  them (and can tell numbers that do not add up).
* Totals survive quitting (playtime.json in the data folder), so a world played over
  several sittings adds up.
* Every finished world is appended to clear_times.csv as a "clear" row with its time, and
  every score the game posts as a "post" row with the time measured for that world, next to
  the game's own value, so real clear times can be looked at. The measured time is what is
  sent to the shared leaderboard (as `pt`, in seconds).

Loading a save state taken earlier in a world does not take time off: only time spent
watching the game run is ever added.

A run in which a save state was loaded (autosaves included) is still timed and logged, but its
time is never sent with the score, so the shared leaderboard (which ignores a score that comes
without a time) does not record it. States make a run easy to repeat, and a time measured
across a jump is not a fair time. A state loaded after a world's Summary also ends the right
to post that clear. The score still goes into your own table.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import parse_qs, urlsplit

WORLD_FILES = {"training.m3g": "training", "island.m3g": "island",
               "agrabah.m3g": "agrabah", "castle.m3g": "castle"}
CSV_HEADER = "when,event,world,score,play_seconds,game_t"
OLD_CSV_HEADER = "when,world,score,play_seconds,game_t"      # before clears were logged too
SUMMARY_LABELS = {"Munny": "munny", "EXP": "exp", "Level": "level", "Score": "score"}   # as the game draws them
MAX_GAP_MS = 60_000          # a longer silence between frames is not play (a stall, a prompt)
SAVE_EVERY_MS = 30_000


class PlayTimer:
    def __init__(self, emu, path: str):
        self.emu = emu
        self.path = path
        self.totals: dict = {}        # world -> ms played in the current run
        self.clears: dict = {}        # world -> ms of the last finished run
        self.world = None             # the world on screen, if any
        self.last = None              # game clock at the last tick
        self.stats: dict = {}         # munny, exp, level, score read off the latest Summary screen
        self.state_used: set = set()  # worlds whose current run had a save state loaded (kept in the file)
        self.fair: set = set()        # worlds whose last clear was finished without one (this sitting only)
        self._label = None            # (stat, y) of the label just drawn, waiting for its number
        self._unsaved = 0
        self._load()

    # ---------------------------------------------------------------- file
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.totals = {k: int(v) for k, v in d.get("totals", {}).items()}
            self.clears = {k: int(v) for k, v in d.get("clears", {}).items()}
            self.state_used = {str(w) for w in d.get("state_used", [])}
        except (OSError, ValueError, AttributeError, TypeError):
            self.totals, self.clears, self.state_used = {}, {}, set()

    def save(self):
        self.tick()
        self._write()

    def _write(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"totals": self.totals, "clears": self.clears,
                           "state_used": sorted(self.state_used)}, f)
            os.replace(tmp, self.path)
            self._unsaved = 0
        except OSError:
            pass                      # the timer must never disturb the game

    # ---------------------------------------------------------------- counting
    def tick(self, _frame=None):
        now = self.emu.clock_ms()
        if self.last is not None and self.world:
            d = now - self.last
            if 0 < d <= MAX_GAP_MS:
                self.totals[self.world] = self.totals.get(self.world, 0) + d
                self._unsaved += d
        self.last = now
        if self._unsaved >= SAVE_EVERY_MS:
            self._write()

    def resync(self, world=None):
        """After a save state is loaded: the clock jumped, so start again from here, in the
        world the state was taken in. Whatever world that is, its run no longer counts for the
        shared leaderboard, and neither does a clear finished before the state was loaded."""
        self.world = world
        self.last = self.emu.clock_ms()
        self.fair.clear()
        if world:
            self.state_used.add(world)
        self._write()

    def file_opened(self, name: str):
        world = WORLD_FILES.get(name.lower().replace("\\", "/").rsplit("/", 1)[-1])
        if world and world != self.world:
            self.tick()
            self.world = world

    def text_drawn(self, text: str, x=None, y=None):
        """Every string the game draws comes through here (display.DrawText): the Summary's
        heading ends the run, and its rows are read as a label followed by a number at the
        same height. The screen is drawn again every frame, so the numbers are simply kept
        up to date; the heading starts each pass afresh."""
        if text == "SUMMARY":
            self.stats, self._label = {}, None
            self.summary()
        elif text in SUMMARY_LABELS:
            self._label = (SUMMARY_LABELS[text], y)
        elif self._label is not None and y == self._label[1] and re.fullmatch(r"\d{1,9}", text):
            self.stats[self._label[0]] = int(text)
            self._label = None

    def summary(self):
        """The world is finished. The Summary is drawn on every frame, so this only acts once."""
        if not self.world:
            return
        self.tick()
        ms = self.totals.pop(self.world, 0)
        if ms > 0:
            self.clears[self.world] = ms
            self.log_row("clear", self.world, "", round(ms / 1000), "")
            if self.world in self.state_used:
                self.fair.discard(self.world)
                self.emu.log(f"[time] {self.world}: a save state was used in this run, so its score "
                             "stays on your own table and is not shared")
            else:
                self.fair.add(self.world)
        self.state_used.discard(self.world)
        self.world = None
        self.save()

    # ---------------------------------------------------------------- scores
    def on_post(self, url: str):
        """The game is posting a score: note how long that world took."""
        parts = urlsplit(url)
        if not parts.path.lower().endswith("/rank.php"):
            return
        q = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        lid = q.get("lid", "").lower()
        world = "island" if lid == "wonderland" else lid      # that screen repeats the Island run
        ms = self.clears.get(world)
        text = "not measured" if ms is None else f"{ms // 60000}:{ms // 1000 % 60:02d} of play"
        if ms is not None and world not in self.fair:
            text += ", not shared (a save state was used, or the run was not finished in this sitting)"
        self.emu.log(f"[time] {lid} score {q.get('s', '?')}: {text} (the game's own value: {q.get('t', '?')})")
        self.log_row("post", lid, q.get("s", ""), "" if ms is None else round(ms / 1000), q.get("t", ""))

    def stats_for_url(self, url: str):
        """{'munny', 'exp', 'level'} for the score a rank.php request posts, if the Summary
        screen just showed numbers that make exactly that score (Munny + 100 x EXP), else None:
        a score is never sent with numbers it was not made of."""
        parts = urlsplit(url)
        if not parts.path.lower().endswith("/rank.php"):
            return None
        q = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        try:
            score = int(q.get("s", ""))
        except ValueError:
            return None
        st = self.stats
        if "munny" not in st or "exp" not in st or st["munny"] + 100 * st["exp"] != score:
            return None
        if "score" in st and st["score"] != score:
            return None
        out = {"munny": st["munny"], "exp": st["exp"]}
        if "level" in st:
            out["level"] = st["level"]
        return out

    def seconds_for_url(self, url: str):
        """The measured time, in whole seconds, for the world a rank.php request is about, or
        None if that run was not measured, or was not a fair one (a save state was loaded in it,
        or since its Summary, or it was finished in an earlier sitting): the shared leaderboard
        records no score that comes without a time."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}
        lid = q.get("lid", "").lower()
        world = "island" if lid == "wonderland" else lid
        ms = self.clears.get(world)
        if ms is None or world not in self.fair:
            return None
        return max(0, round(ms / 1000))

    def log_row(self, event: str, world, score, seconds, game_t):
        """Append a line to clear_times.csv: a world finished ("clear") or a score posted ("post")."""
        path = self.csv_path()
        try:
            self._upgrade_csv(path)
            new = not os.path.exists(path)
            with open(path, "a", encoding="utf-8", newline="") as f:
                if new:
                    f.write(CSV_HEADER + "\n")
                f.write("%s,%s,%s,%s,%s,%s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), event, world, score, seconds, game_t))
        except OSError:
            pass                      # the timer must never disturb the game

    @staticmethod
    def _upgrade_csv(path: str):
        """A file from before clears were logged has one row per posted score and no event
        column: give it one, keeping every row."""
        try:
            with open(path, encoding="utf-8", newline="") as f:
                lines = f.read().splitlines()
        except OSError:
            return
        if not lines or lines[0].strip() != OLD_CSV_HEADER:
            return
        out = [CSV_HEADER]
        for line in lines[1:]:
            when, _, rest = line.partition(",")
            if when:
                out.append(f"{when},post,{rest}")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(out) + "\n")

    def csv_path(self) -> str:
        return os.path.join(os.path.dirname(self.path), "clear_times.csv")
