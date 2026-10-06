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


MANY = [
    ("2026-10-05", "view:home", 30), ("2026-10-05", "view:leaderboard", 4), ("2026-10-05", "dl:win64", 6), ("2026-10-05", "dl:macArm", 1),
    ("2026-10-06", "view:home", 70), ("2026-10-06", "dl:win64", 14), ("2026-10-06", "dl:linux64", 3), ("2026-10-06", "dl:sums", 2),
    ("2026-10-06", "click:repo", 9), ("2026-10-06", "click:soundtrack", 5),
    ("2026-10-05", "hour:14", 12), ("2026-10-06", "hour:14", 20), ("2026-10-06", "hour:03", 5),
    ("2026-10-05", "country:US", 20), ("2026-10-06", "country:US", 40), ("2026-10-06", "country:BR", 12), ("2026-10-06", "country:ZZ", 3),
    ("2026-10-06", "os:windows", 80), ("2026-10-06", "os:mac", 9), ("2026-10-06", "os:linux", 6),
    ("2026-10-06", "ref:reddit", 55), ("2026-10-06", "ref:direct", 30), ("2026-10-06", "ref:khinsider", 7),
    ("2026-10-06", "sec:about", 63), ("2026-10-06", "sec:download", 40), ("2026-10-06", "sec:credits", 8),
]


class DashboardTests(unittest.TestCase):
    def test_text_summary_covers_the_new_tallies(self):
        text = site_stats.summarize(MANY, days=14)
        self.assertRegex(text, r"Reddit\s+55")
        self.assertRegex(text, r"United States \(US\)\s+60")
        self.assertRegex(text, r"Brazil \(BR\)\s+12")
        self.assertRegex(text, r"ZZ\s+3")                                    # a code it has no name for is shown as it is
        self.assertRegex(text, r"Windows\s+80")
        self.assertRegex(text, r"About\s+63\s+90%")                         # 63 of the 70 visits since sections were counted
        self.assertIn("Download clicks: 24 from 100 visits", text)
        self.assertNotIn("hour:", text.split("Last 14 days")[0].split("Totals")[1].split("Download clicks")[0],
                         "the extra tallies are not mixed into the plain totals")

    def test_the_page_has_every_section_and_the_right_numbers(self):
        page = site_stats.build_html(MANY, days=30, generated="2026-10-06 12:00")
        for heading in ("Each day", "Time of day", "Where visitors came from", "Countries", "Kinds of computer",
                        "Download clicks", "How far down the page", "Other clicks", "Reading these numbers"):
            self.assertIn(heading, page)
        for text in ("<b>70</b><span>visits on the latest day", "<b>100</b><span>visits in all", "<b>24</b><span>download clicks (24% of visits)",
                     "Reddit", "United States (US)", "Windows 64-bit", "Checksums file", "Source code (GitHub)", "Wonderland (the lost chapter)"):
            self.assertIn(text, page)
        self.assertIn("Updated 2026-10-06 12:00", page)

    def test_the_page_works_offline_and_cannot_be_hijacked(self):
        import re
        page = site_stats.build_html(MANY + [("2026-10-06", "country:<script>alert(1)</script>", 4)], days=30)
        self.assertNotIn("<script>alert", page, "a name from the table is escaped")
        self.assertIsNone(re.search(r"https?://", page), "nothing is loaded from the internet")
        self.assertNotIn("<script", page)

    def test_an_empty_table_gives_a_readable_page(self):
        page = site_stats.build_html([], generated="now")
        self.assertIn("No counts yet", page)
        self.assertIn("<b>0</b>", page)

    def test_days_with_no_visits_are_shown_as_zero(self):
        page = site_stats.build_html([("2026-10-01", "view:home", 3), ("2026-10-04", "view:home", 5)], days=5, generated="x")
        for day in ("10-01", "10-02", "10-03", "10-04"):
            self.assertIn(f"<span>{day}</span>", page)

    def test_the_report_file_is_written_and_utf8(self):
        import tempfile
        path = site_stats.write_report(MANY, 30, os.path.join(tempfile.mkdtemp(), "r.html"))
        with open(path, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
