"""The client side of the shared leaderboard: khvcemu forwards the game's score
requests to a server and falls back to its own table whenever that doesn't work
out. Served by a real local HTTP server, so the networking is exercised.
"""

import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu.web import share_scores  # noqa: E402

RANK = ("http://swervenet.superscape.com/disney/rank.php"
        "?uid=&aid=KH&lid=island&s=1500&t=55&u1=1&u2=")


class Handler(BaseHTTPRequestHandler):
    status, body, seen = 200, b"*r|ok|anon~|island~7", []

    def do_GET(self):
        Handler.seen.append((self.path, dict(self.headers)))
        self.send_response(Handler.status)
        self.send_header("content-type", "text/plain")
        self.end_headers()
        self.wfile.write(Handler.body)

    def log_message(self, *a):
        pass


class SharedLeaderboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Handler.status, Handler.body, Handler.seen = 200, b"*r|ok|anon~|island~7", []

    def test_the_games_own_path_and_query_are_forwarded_unchanged(self):
        self.assertEqual(share_scores(RANK, self.base), b"*r|ok|anon~|island~7")
        path, headers = Handler.seen[0]
        self.assertEqual(path, "/disney/rank.php?uid=&aid=KH&lid=island&s=1500&t=55&u1=1&u2=")
        self.assertEqual(headers.get("User-Agent"), "khvcemu", "no identifying headers")

    def test_a_trailing_slash_on_the_address_is_harmless(self):
        self.assertIsNotNone(share_scores(RANK, self.base + "/"))
        self.assertTrue(Handler.seen[0][0].startswith("/disney/rank.php"))

    def test_an_error_status_is_refused(self):
        Handler.status = 503
        self.assertIsNone(share_scores(RANK, self.base))

    def test_a_reply_the_game_could_not_parse_is_refused(self):
        for junk in (b"<html>captive portal</html>", b"", b"ok", b" *r|ok|anon~"):
            with self.subTest(junk=junk):
                Handler.body = junk
                self.assertIsNone(share_scores(RANK, self.base))

    def test_an_oversized_reply_is_truncated_not_swallowed(self):
        Handler.body = b"*r|ok|anon~|island~1" + b"|x~1" * 5000
        got = share_scores(RANK, self.base)
        self.assertIsNotNone(got)
        self.assertLessEqual(len(got), 4096)

    def test_an_unreachable_server_gives_up_instead_of_raising(self):
        self.assertIsNone(share_scores(RANK, "http://127.0.0.1:9", timeout=1.0))
        self.assertIsNone(share_scores(RANK, "not a url", timeout=1.0))
        self.assertIsNone(share_scores(RANK, "http://no-such-host.invalid", timeout=2.0))


class FallbackTests(unittest.TestCase):
    """What the game is handed when the shared leaderboard is or isn't working."""

    def setUp(self):
        from khvcemu.leaderboard import Leaderboard
        from khvcemu.runtime import Emulator
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = []
        self.emu = Emulator.__new__(Emulator)       # no game files needed for this
        self.emu.leaderboard = Leaderboard(os.path.join(self.tmp.name, "leaderboard.db"))
        self.emu.leaderboard_url = ""
        self.emu.log = self.logs.append

    def tearDown(self):
        self.emu.leaderboard.db.close()
        self.tmp.cleanup()

    def rows(self):
        return self.emu.leaderboard.db.execute("SELECT lid, score FROM scores").fetchall()

    def test_offline_only_by_default(self):
        code, body = self.emu.web_request(RANK)
        self.assertEqual((code, body), (200, b"*r|ok|local~|island~1"))
        self.assertEqual(self.rows(), [("island", 1500)])

    def test_the_shared_ranking_is_shown_and_the_score_still_kept_offline(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~42"):
            code, body = self.emu.web_request(RANK)
        self.assertEqual(body, b"*r|ok|anon~|island~42", "the shared rank is what the game sees")
        self.assertEqual(self.rows(), [("island", 1500)], "and it is still in your own table")

    def test_a_server_that_fails_falls_back_to_your_own_scores(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        with mock.patch("khvcemu.web.share_scores", return_value=None):
            code, body = self.emu.web_request(RANK)
        self.assertEqual((code, body), (200, b"*r|ok|local~|island~1"))
        self.assertEqual(self.rows(), [("island", 1500)])
        self.assertTrue(any("didn't answer" in m for m in self.logs), self.logs)

    WONDER = RANK.replace("lid=island", "lid=wonderland")

    def test_a_wonderland_score_is_shared_as_an_island_score(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            code, body = self.emu.web_request(self.WONDER)
        self.assertIn("lid=island", shared.call_args[0][0], "sent to the server as the Island")
        self.assertEqual(body, b"*r|ok|anon~|wonderland~3", "but the game is answered as Wonderland")
        self.assertEqual(self.rows(), [("wonderland", 1500)], "and your own table is unchanged")

    def test_the_same_run_is_not_shared_twice(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3"):
            self.emu.web_request(RANK)                    # the Island prompt
        with mock.patch("khvcemu.web.share_scores") as shared:
            code, body = self.emu.web_request(self.WONDER)   # the Wonderland prompt, same score
        shared.assert_not_called()
        self.assertEqual(code, 200)
        self.assertTrue(body.startswith(b"*r|ok|"), body)

    class _Timer:
        def __init__(self, seconds, stats=None):
            self.seconds, self.stats = seconds, stats

        def on_post(self, url):
            pass

        def seconds_for_url(self, url):
            return self.seconds

        def stats_for_url(self, url):
            return self.stats

    def test_munny_exp_and_level_are_sent_with_the_score(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        self.emu.playtime = self._Timer(754, {"munny": 931, "exp": 6, "level": 2})
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            self.emu.web_request(RANK)
        sent = shared.call_args[0][0]
        for part in ("pt=754", "mn=931", "ex=6", "lv=2"):
            self.assertIn(part, sent)
        self.assertEqual(self.rows(), [("island", 1500)], "your own table is unchanged")

    def test_no_stats_means_none_are_sent(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        self.emu.playtime = self._Timer(754, None)
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            self.emu.web_request(RANK)
        for part in ("mn=", "ex=", "lv="):
            self.assertNotIn(part, shared.call_args[0][0])

    def test_a_wonderland_post_carries_the_stats_as_the_island_run(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        self.emu.playtime = self._Timer(754, {"munny": 931, "exp": 6})
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            self.emu.web_request(self.WONDER)
        self.assertIn("lid=island", shared.call_args[0][0])
        self.assertIn("mn=931", shared.call_args[0][0])
        self.assertNotIn("lv=", shared.call_args[0][0], "no level read: none sent")

    def test_the_measured_time_is_sent_with_the_score(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        self.emu.playtime = self._Timer(754)
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            self.emu.web_request(RANK)
        self.assertIn("pt=754", shared.call_args[0][0])
        self.assertIn("t=55", shared.call_args[0][0], "the game's own value is left as it was")

    def test_a_wonderland_post_carries_the_time_too(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        self.emu.playtime = self._Timer(754)
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            self.emu.web_request(self.WONDER)
        self.assertIn("lid=island", shared.call_args[0][0])
        self.assertIn("pt=754", shared.call_args[0][0])

    def test_an_unmeasured_run_is_sent_without_a_time(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        self.emu.playtime = self._Timer(None)
        with mock.patch("khvcemu.web.share_scores", return_value=b"*r|ok|anon~|island~3") as shared:
            self.emu.web_request(RANK)
        self.assertNotIn("pt=", shared.call_args[0][0])

    def test_the_dead_episode_server_is_never_forwarded(self):
        from unittest import mock
        self.emu.leaderboard_url = "http://example.invalid"
        with mock.patch("khvcemu.web.share_scores") as shared:
            code, body = self.emu.web_request(
                "http://swervenet.superscape.com/disney/download.php?f=wonderland.dat")
        self.assertEqual((code, body), (404, b""))
        shared.assert_not_called()


if __name__ == "__main__":
    unittest.main()
