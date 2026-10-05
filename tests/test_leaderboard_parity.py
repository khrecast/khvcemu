"""The shared leaderboard (server/worker.js) and the offline one (leaderboard.py)
must answer the game identically, because the game's parser accepts exactly one
shape. This replays the exchanges server/test.js recorded and compares them.

    cd server && node test.js        # writes parity.txt
    python -m unittest tests.test_leaderboard_parity

Skipped when node isn't installed or parity.txt hasn't been generated.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu.leaderboard import Leaderboard  # noqa: E402

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
PARITY = os.path.join(SERVER, "parity.txt")


def _parity_lines():
    """[(path, worker reply)], regenerating parity.txt with node when possible."""
    if not os.path.isfile(PARITY) and shutil.which("node"):
        from khvcemu.paths import no_window
        try:
            subprocess.run([shutil.which("node"), "test.js"], cwd=SERVER, timeout=120,
                           capture_output=True, **no_window())
        except (OSError, subprocess.SubprocessError):
            pass
    if not os.path.isfile(PARITY):
        return []
    out = []
    with open(PARITY, encoding="utf-8") as f:
        for line in f:
            if "  =>  " in line:
                path, body = line.rstrip("\n").split("  =>  ", 1)
                out.append((path, body))
    return out


@unittest.skipUnless(_parity_lines(), "run 'node test.js' in server/ first")
class ParityTests(unittest.TestCase):
    """Worker and offline table, same inputs, same replies."""

    # the two deliberately differ in one field: neither issues a real identity, so
    # the offline table calls every player "local" and the shared one "anon". The
    # game stores whatever it is told and sends it back; nothing reads it.
    def normalise(self, body):
        return body.replace("|local~", "|ID~").replace("|anon~", "|ID~")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = Leaderboard(os.path.join(self.tmp.name, "leaderboard.db"))

    def tearDown(self):
        self.lb.db.close()
        self.tmp.cleanup()

    def test_same_replies_for_the_same_exchanges(self):
        # the worker rejects levels the game could never send; the offline table is
        # your own file and stays permissive, so those two lines are compared only
        # for shape, not for content
        worker_only_rejects = ("notaworld",)
        checked = 0
        for path, worker_body in _parity_lines():
            with self.subTest(path=path):
                got = self.lb.handle("http://swervenet.superscape.com" + path)
                self.assertIsNotNone(got, "the offline table must recognise this URL")
                body = got[1].decode()
                if any(w in path for w in worker_only_rejects):
                    self.assertTrue(body.startswith("*r|"), body)
                    continue
                self.assertEqual(self.normalise(body), self.normalise(worker_body),
                                 f"replies differ for {path}")
                checked += 1
        self.assertGreater(checked, 4, "the recorded exchanges look empty")

    def test_every_reply_is_shaped_the_way_the_game_parses(self):
        for path, worker_body in _parity_lines():
            with self.subTest(path=path):
                fields = worker_body.split("|")
                self.assertEqual(fields[0], "*r", "field 0 is the tag the parser looks for")
                if fields[1] == "invalidentry":
                    continue
                self.assertGreaterEqual(len(fields), 3, "a player id field must exist")
                self.assertIn("~", fields[2], "the game keeps field 2 up to the first ~")
                for entry in fields[3:]:
                    level, _, rank = entry.partition("~")
                    self.assertTrue(level and rank.isdigit(), entry)


if __name__ == "__main__":
    unittest.main()
