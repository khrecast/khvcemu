"""Show the website's anonymous visit and download counters.

    python tools/site_stats.py [--days 14]

Reads the `site_stats` table of the live leaderboard database (read-only) through wrangler, so
it needs the Cloudflare login that `npx wrangler` already has. Nothing here identifies anyone:
the table holds only a day, an event name and a count (see server/schema.sql).
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERY = "SELECT day, name, n FROM site_stats ORDER BY day, name"
DOWNLOADS = ("dl:win64", "dl:win32", "dl:macArm", "dl:macIntel", "dl:linux64", "dl:linuxArm")


def fetch_rows() -> list:
    """[(day, name, n)] from the live database (read-only SELECT)."""
    cmd = "npx wrangler d1 execute khvcemu-leaderboard --remote --json --command \"" + QUERY + "\""
    r = subprocess.run(cmd, cwd=os.path.join(ROOT, "server"), capture_output=True, text=True, shell=True, timeout=120)
    if r.returncode:
        raise SystemExit("wrangler failed:\n" + (r.stderr or r.stdout)[-600:])
    return parse(r.stdout)


def parse(text: str) -> list:
    """The rows out of wrangler's --json output (it may print other lines before the JSON)."""
    start = text.find("[")
    data = json.loads(text[start:])
    out = []
    for block in data:
        for row in block.get("results", []):
            out.append((row["day"], row["name"], int(row["n"])))
    return out


def summarize(rows: list, days: int = 14) -> str:
    if not rows:
        return "No counts yet (the table is empty, or nobody has opened the public site)."
    by_day, totals = {}, {}
    for day, name, n in rows:
        by_day.setdefault(day, {})[name] = by_day.get(day, {}).get(name, 0) + n
        totals[name] = totals.get(name, 0) + n
    lines = []
    first, last = min(by_day), max(by_day)
    lines.append(f"Counted from {first} to {last} (UTC days)")
    lines.append("")
    lines.append("Totals")
    for name in sorted(totals, key=lambda k: (-totals[k], k)):
        lines.append(f"  {name:18} {totals[name]:>7}")
    views = totals.get("view:home", 0)
    dls = sum(totals.get(k, 0) for k in DOWNLOADS)
    if views:
        lines.append("")
        lines.append(f"Download clicks: {dls} from {views} visits to the main page ({100 * dls / views:.0f}%)")
        lines.append("(a click on a Download button is not a finished download: it only opens the mirror)")
    lines.append("")
    lines.append(f"Last {days} days: visits (main page) / leaderboard views / download clicks")
    for day in sorted(by_day)[-days:]:
        d = by_day[day]
        lines.append(f"  {day}  {d.get('view:home', 0):>6} / {d.get('view:leaderboard', 0):>5} / {sum(d.get(k, 0) for k in DOWNLOADS):>5}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=14, help="how many recent days to list (default 14)")
    args = ap.parse_args(argv)
    print(summarize(fetch_rows(), args.days))


if __name__ == "__main__":
    sys.exit(main())
