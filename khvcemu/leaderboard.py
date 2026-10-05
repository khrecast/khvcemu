"""Offline high-score table, standing in for the game's dead ranking server.

After a world the game offers to "post it to the server and get a ranking".
It asks http://swervenet.superscape.com/disney/rank.php (and, for the HIGH
SCORES screen, rankex.php). The server is gone, so web.py hands those requests
to this module, which keeps the scores in a small SQLite file next to the
saves and answers in the format the game's parser (kh.mod 0x105734) expects:

    *r|<status>|<uid>~|<entry>|<entry>...        fields split on '|'

  * field 0 must be "*r"; field 1 is the status ("invalidentry" makes the game
    show its error message, anything else is success);
  * field 2 is the player id the server assigns; the game keeps the part before
    the first '~' and sends it back as uid= from then on;
  * rank.php answers with one entry "<level>~<rank>"; the game stores the number
    after the '~' as the rank of the score just posted;
  * rankex.php ("Update" on the HIGH SCORES screen) sends the game's own table as
    comma-separated lists (lid=island,agrabah&s=1500,700) and expects one entry
    "<level>~<rank>" back per level it can rank.

Ranks are positions among every score ever posted for the level (ties share a
place), so a single player still sees how a run compares with their own past
runs; scores from several players sharing one folder rank against each other.
A level nobody has posted to has no rank yet, so it is left out of the reply
and the HIGH SCORES screen shows its rank blank.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

DEFAULT_UID = "local"
_CLEAN = re.compile(r"[^A-Za-z0-9_.-]")     # '|' and '~' would break the reply format


def clean(value: str, default: str = "") -> str:
    return _CLEAN.sub("_", value)[:32] or default


class Leaderboard:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS scores ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, posted REAL NOT NULL,"
            " uid TEXT NOT NULL, aid TEXT NOT NULL, lid TEXT NOT NULL,"
            " score INTEGER NOT NULL, secs INTEGER, u1 INTEGER, u2 TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS scores_lid ON scores (lid, score)")
        self.db.commit()

    # ------------------------------------------------------------- data
    def post(self, uid: str, aid: str, lid: str, score: int, secs: Optional[int],
             u1: Optional[int], u2: str) -> int:
        """Record a score; returns its rank among all scores for the level."""
        self.db.execute(
            "INSERT INTO scores (posted, uid, aid, lid, score, secs, u1, u2)"
            " VALUES (?,?,?,?,?,?,?,?)", (time.time(), uid, aid, lid, score, secs, u1, u2))
        self.db.commit()
        return self.rank_of(lid, score)

    def rank_of(self, lid: str, score: int) -> int:
        (better,) = self.db.execute(
            "SELECT COUNT(*) FROM scores WHERE lid=? AND score>?", (lid, score)).fetchone()
        return better + 1

    def has_score(self, lid: str, score: int) -> bool:
        return self.db.execute("SELECT 1 FROM scores WHERE lid=? AND score=? LIMIT 1",
                               (lid, score)).fetchone() is not None

    def has_scores(self, lid: str) -> bool:
        return self.db.execute("SELECT 1 FROM scores WHERE lid=? LIMIT 1", (lid,)).fetchone() is not None

    # ------------------------------------------------------------- protocol
    @staticmethod
    def _reply(uid: str, entries: list) -> bytes:
        return ("*r|ok|%s~|%s" % (uid, "|".join(entries)) if entries
                else "*r|ok|%s~" % uid).encode()

    def handle(self, url: str) -> Optional[Tuple[int, bytes]]:
        """Answer a game request; None if the URL isn't one of ours."""
        parts = urlparse(url)
        script = parts.path.rsplit("/", 1)[-1].lower()
        if script not in ("rank.php", "rankex.php"):
            return None
        q = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        uid = clean(q.get("uid", ""), DEFAULT_UID)
        lid = clean(q.get("lid", ""))
        if script == "rankex.php":
            entries = []
            for lid_, score_ in zip(q.get("lid", "").split(","), q.get("s", "").split(",")):
                lid_, score_ = clean(lid_), _int(score_)
                if lid_ and score_ is not None and self.has_scores(lid_):
                    entries.append("%s~%d" % (lid_, self.rank_of(lid_, score_)))
            return 200, self._reply(uid, entries)
        try:
            score = int(q["s"])
        except (KeyError, ValueError):
            return 200, b"*r|invalidentry"
        if not lid or score < 0:
            return 200, b"*r|invalidentry"
        secs = _int(q.get("t"))
        rank = self.post(uid, clean(q.get("aid", ""), "KH"), lid, score, secs,
                         _int(q.get("u1")), clean(q.get("u2", "")))
        return 200, self._reply(uid, ["%s~%d" % (lid, rank)])


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
