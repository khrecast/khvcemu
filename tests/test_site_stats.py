"""tools/site_stats.py: reading wrangler's output and summarising the anonymous counters (no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import site_stats  # noqa: E402

WRANGLER = """
 ⛅️ wrangler 4.147.0
Resource location: remote

[
  {"results": [
      {"day": "2026-10-06", "name": "view:home", "n": 40},
      {"day": "2026-10-06", "name": "dl:win64", "n": 10},
      {"day": "2026-10-06", "name": "dl:linux64", "n": 2},
      {"day": "2026-10-07", "name": "view:home", "n": 10},
      {"day": "2026-10-07", "name": "view:leaderboard", "n": 4},
      {"day": "2026-10-07", "name": "dl:sums", "n": 1}
    ], "success": true, "meta": {}}
]
"""


class SiteStatsTests(unittest.TestCase):
    def test_parse_skips_wranglers_banner(self):
        rows = site_stats.parse(WRANGLER)
        self.assertEqual(len(rows), 6)
        self.assertIn(("2026-10-06", "dl:win64", 10), rows)

    def test_summary(self):
        text = site_stats.summarize(site_stats.parse(WRANGLER), days=14)
        self.assertIn("Counted from 2026-10-06 to 2026-10-07", text)
        self.assertRegex(text, r"view:home\s+50")
        self.assertIn("Download clicks: 12 from 50 visits", text)      # win64 + linux64, not the checksums file
        self.assertRegex(text, r"2026-10-06\s+40 /\s+0 /\s+12")
        self.assertRegex(text, r"2026-10-07\s+10 /\s+4 /\s+0")

    def test_days_limit_and_empty(self):
        text = site_stats.summarize(site_stats.parse(WRANGLER), days=1)
        self.assertNotIn("2026-10-06  ", text.split("Last 1 days")[1])
        self.assertIn("No counts yet", site_stats.summarize([]))


if __name__ == "__main__":
    unittest.main()
