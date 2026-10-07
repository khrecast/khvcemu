"""Show the website's anonymous visit and download counters.

    python tools/site_stats.py [--days 14]       a text summary
    python tools/site_stats.py --open            a dashboard page, opened in your browser

Reads the `site_stats` table of the live leaderboard database (read-only) through wrangler, so
it needs the Cloudflare login that `npx wrangler` already has. Nothing here identifies anyone:
the table holds only a day, a name and a count (see server/schema.sql). The tallies for the hour,
country, kind of computer and where visitors came from are separate counts, never stored per visit (on a very
quiet day, a visit or two, they could still be matched up by eye). `tools/show_site_stats.bat` is the
double-click button for `--open`.
"""
import argparse
import datetime
import html
import json
import os
import subprocess
import sys
import tempfile
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERY = "SELECT day, name, n FROM site_stats ORDER BY day, name"
DOWNLOADS = ("dl:win64", "dl:win32", "dl:macArm", "dl:macIntel", "dl:linux64", "dl:linuxArm")
SECTIONS = ("about", "features", "screens", "launcher", "composer", "download", "help", "wonderland", "credits")

DOWNLOAD_NAMES = {"dl:win64": "Windows 64-bit", "dl:win32": "Windows 32-bit", "dl:macArm": "Mac, Apple Silicon",
                  "dl:macIntel": "Mac, Intel", "dl:linux64": "Linux, x86-64", "dl:linuxArm": "Linux, ARM64",
                  "dl:sums": "Checksums file"}
CLICK_NAMES = {"click:repo": "Source code (GitHub)", "click:issues": "Report a problem (GitHub)",
               "click:soundtrack": "Soundtrack (KHInsider)", "click:email": "Contact email"}
SECTION_NAMES = {"about": "About", "features": "Features", "screens": "Screenshots", "launcher": "The launcher",
                 "composer": "The music", "download": "Download", "help": "Help", "wonderland": "Wonderland (the lost chapter)",
                 "credits": "Credits"}
REF_NAMES = {"direct": "Direct, no referrer, or from inside the site", "reddit": "Reddit", "google": "Google", "bing": "Bing",
             "duckduckgo": "DuckDuckGo", "youtube": "YouTube", "x": "X (Twitter)", "bluesky": "Bluesky", "facebook": "Facebook",
             "discord": "Discord", "khinsider": "KHInsider", "kh13": "KH13", "khwiki": "KH Wiki / KH Database",
             "lostmedia": "Lost Media Wiki", "archive": "Internet Archive", "github": "GitHub", "hackernews": "Hacker News",
             "other": "Another website"}
OS_NAMES = {"windows": "Windows", "mac": "Mac", "linux": "Linux", "android": "Android", "ios": "iPhone / iPad",
            "chromeos": "ChromeOS", "other": "Something else"}
COUNTRIES = {
    "US": "United States", "GB": "United Kingdom", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand", "IE": "Ireland",
    "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy", "PT": "Portugal", "NL": "Netherlands", "BE": "Belgium",
    "CH": "Switzerland", "AT": "Austria", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland", "PL": "Poland",
    "CZ": "Czechia", "RU": "Russia", "UA": "Ukraine", "TR": "Turkey", "GR": "Greece", "RO": "Romania", "HU": "Hungary",
    "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru", "VE": "Venezuela",
    "JP": "Japan", "KR": "South Korea", "CN": "China", "TW": "Taiwan", "HK": "Hong Kong", "SG": "Singapore", "MY": "Malaysia",
    "TH": "Thailand", "VN": "Vietnam", "ID": "Indonesia", "PH": "Philippines", "IN": "India", "PK": "Pakistan", "IL": "Israel",
    "SA": "Saudi Arabia", "AE": "United Arab Emirates", "EG": "Egypt", "ZA": "South Africa", "NG": "Nigeria", "XX": "Unknown",
    "T1": "Tor network",
}


# ------------------------------------------------------------------ reading
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


def aggregate(rows: list):
    """(totals {name: n}, by_day {day: {name: n}})."""
    totals, by_day = {}, {}
    for day, name, n in rows:
        by_day.setdefault(day, {})[name] = by_day.get(day, {}).get(name, 0) + n
        totals[name] = totals.get(name, 0) + n
    return totals, by_day


def group(totals: dict, prefix: str) -> list:
    """[(label after the prefix, count)] for one kind of tally, biggest first."""
    items = [(k[len(prefix):], v) for k, v in totals.items() if k.startswith(prefix)]
    return sorted(items, key=lambda kv: (-kv[1], kv[0]))


def country_name(code: str) -> str:
    return f"{COUNTRIES[code]} ({code})" if code in COUNTRIES else code


def group_total(totals: dict, prefix: str) -> int:
    return sum(v for k, v in totals.items() if k.startswith(prefix))


def views_since(by_day: dict, prefix: str) -> int:
    """Main-page visits from the first day a kind of tally (such as sec:) exists: it began later than the visit
    count did, so its shares must be of the visits it could have counted."""
    firsts = [d for d, names in by_day.items() if any(k.startswith(prefix) for k in names)]
    if not firsts:
        return 0
    start = min(firsts)
    return sum(names.get("view:home", 0) for d, names in by_day.items() if d >= start)


def downloads_of(d: dict) -> int:
    return sum(d.get(k, 0) for k in DOWNLOADS)


def recent_days(by_day: dict, days: int) -> list:
    """The last `days` calendar days up to the newest day with data, zeros included."""
    if not by_day:
        return []
    last = datetime.date.fromisoformat(max(by_day))
    return [(last - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


# ------------------------------------------------------------------ the text summary
def summarize(rows: list, days: int = 14) -> str:
    if not rows:
        return "No counts yet (the table is empty, or nobody has opened the public site)."
    totals, by_day = aggregate(rows)
    lines = [f"Counted from {min(by_day)} to {max(by_day)} (UTC days)", "", "Totals"]
    main = {k: v for k, v in totals.items() if not k.startswith(("hour:", "country:", "os:", "ref:", "sec:"))}
    for name in sorted(main, key=lambda k: (-main[k], k)):
        lines.append(f"  {name:18} {main[name]:>7}")
    views = totals.get("view:home", 0)
    dls = downloads_of(totals)
    if views:
        lines += ["", f"Download clicks: {dls} from {views} visits to the main page ({100 * dls / views:.0f}%)",
                  "(a click on a Download button is not a finished download: it only opens the mirror)"]
    for title, prefix, names in (("Where visitors came from", "ref:", REF_NAMES), ("Kinds of computer", "os:", OS_NAMES)):
        items = group(totals, prefix)
        if items:
            lines += ["", title] + [f"  {names.get(k, k):32} {v:>6}" for k, v in items]
    countries = group(totals, "country:")
    if countries:
        lines += ["", "Countries (top 10)"] + [f"  {country_name(k):32} {v:>6}" for k, v in countries[:10]]
    secs = [(s, totals.get("sec:" + s, 0)) for s in SECTIONS if totals.get("sec:" + s)]
    sec_views = views_since(by_day, "sec:")
    if secs and sec_views:
        lines += ["", "Parts of the page scrolled to (share of main-page visits since this was first counted)"]
        lines += [f"  {SECTION_NAMES.get(s, s):32} {v:>6}  {100 * v / sec_views:3.0f}%" for s, v in secs]
    lines += ["", f"Last {days} days: visits (main page) / leaderboard views / download clicks"]
    for day in sorted(by_day)[-days:]:
        d = by_day[day]
        lines.append(f"  {day}  {d.get('view:home', 0):>6} / {d.get('view:leaderboard', 0):>5} / {downloads_of(d):>5}")
    return "\n".join(lines)


# ------------------------------------------------------------------ the dashboard page
CSS = """
:root { color-scheme: light dark; --bg:#f4f6fa; --panel:#fff; --text:#1b2433; --muted:#5b6b82; --line:#d9e0ea;
  --visits:#2f6fe0; --board:#6f7f99; --downloads:#d9730d; --bar:#2f6fe0; }
@media (prefers-color-scheme: dark) { :root { --bg:#0b1626; --panel:#13253c; --text:#e9f0fa; --muted:#8ea4bf; --line:#24405f;
  --visits:#5b9bff; --board:#8ea4bf; --downloads:#f2994a; --bar:#5b9bff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 "Segoe UI", system-ui, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { margin: 0 0 4px; font-size: 26px; } h2 { margin: 0 0 12px; font-size: 17px; }
.sub { color: var(--muted); margin: 0 0 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 12px; margin-bottom: 18px; }
.tile, section { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
.tile b { display:block; font-size: 30px; line-height: 1.1; } .tile span { color: var(--muted); font-size: 13px; }
section { margin-bottom: 14px; } .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 14px; }
.grid2 section { margin: 0; }
.row { display: grid; grid-template-columns: minmax(120px, 210px) 1fr 86px; gap: 10px; align-items: center; margin: 5px 0; }
.row .lab { overflow-wrap: anywhere; } .row .val { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
.track { background: color-mix(in srgb, var(--line) 55%, transparent); border-radius: 4px; height: 14px; }
.track i { display:block; height: 100%; border-radius: 4px; background: var(--bar); min-width: 2px; }
.days { display:flex; align-items:flex-end; gap: 4px; height: 170px; padding-top: 8px; overflow-x:auto; }
.day { flex: 1 0 34px; white-space: nowrap; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%; font-size:11px; color:var(--muted); }
.cols { display:flex; align-items:flex-end; gap:2px; height: 130px; width:100%; justify-content:center; }
.cols i { display:block; width: 7px; border-radius: 3px 3px 0 0; min-height: 1px; }
.legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:13px; margin-bottom:6px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }
.hours { display:grid; grid-template-columns: repeat(24, 1fr); gap:2px; align-items:end; height:120px; }
.hours div { display:flex; flex-direction:column; justify-content:flex-end; align-items:center; height:100%; font-size:10px; color:var(--muted); }
.hours i { display:block; width:100%; background:var(--bar); border-radius:3px 3px 0 0; min-height:1px; }
.note { color: var(--muted); font-size: 13px; } .empty { color: var(--muted); }
"""


def _bars(items: list, total: int = None, names: dict = None, limit: int = None) -> str:
    items = items[:limit] if limit else items
    if not items:
        return '<p class="empty">Nothing counted yet.</p>'
    top = max(v for _, v in items) or 1
    out = []
    for key, v in items:
        label = (names or {}).get(key, key)
        pct = f" ({100 * v / total:.0f}%)" if total else ""
        out.append(f'<div class="row"><span class="lab">{html.escape(str(label))}</span>'
                   f'<span class="track" role="img" aria-label="{v}"><i style="width:{100 * v / top:.1f}%"></i></span>'
                   f'<span class="val">{v}{pct}</span></div>')
    return "\n".join(out)


def build_html(rows: list, days: int = 30, generated: str = None) -> str:
    totals, by_day = aggregate(rows)
    generated = generated or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    views, board, dls = totals.get("view:home", 0), totals.get("view:leaderboard", 0), downloads_of(totals)
    today = max(by_day) if by_day else ""
    last7 = recent_days(by_day, 7)
    week = sum(by_day.get(d, {}).get("view:home", 0) for d in last7)
    today_n = by_day.get(today, {}).get("view:home", 0) if today else 0
    rate = f"{100 * dls / views:.0f}% of visits" if views else "no visits yet"

    parts = [f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
             f"<title>Re:Cast site stats</title><style>{CSS}</style></head><body><main>",
             "<h1>Re:Cast site stats</h1>",
             f"<p class=\"sub\">Anonymous, rough counts. Updated {html.escape(generated)}. Days and hours are UTC."
             f"{' Latest day with data: ' + html.escape(today) + '.' if today else ''}</p>"]
    if not rows:
        parts.append('<section><p class="empty">No counts yet. The table is empty, or nobody has opened the public site since counting began.</p></section>')
    parts.append('<div class="tiles">'
                 f'<div class="tile"><b>{today_n}</b><span>visits on the latest day</span></div>'
                 f'<div class="tile"><b>{week}</b><span>visits in the last 7 days</span></div>'
                 f'<div class="tile"><b>{views}</b><span>visits in all</span></div>'
                 f'<div class="tile"><b>{dls}</b><span>download clicks ({html.escape(rate)})</span></div>'
                 f'<div class="tile"><b>{board}</b><span>leaderboard page views</span></div></div>')

    # visits per day
    span = (datetime.date.fromisoformat(max(by_day)) - datetime.date.fromisoformat(min(by_day))).days + 1 if by_day else 0
    series = recent_days(by_day, min(days, max(7, span)))      # since counting began (at least a week, at most `days`)
    if series:
        peak = max(1, max(max(by_day.get(d, {}).get("view:home", 0), by_day.get(d, {}).get("view:leaderboard", 0),
                              downloads_of(by_day.get(d, {}))) for d in series))
        cols = []
        for d in series:
            vals = (by_day.get(d, {}).get("view:home", 0), by_day.get(d, {}).get("view:leaderboard", 0), downloads_of(by_day.get(d, {})))
            bars = "".join(f'<i style="height:{100 * v / peak:.1f}%;background:var({c})" title="{html.escape(d)}: {v}"></i>'
                           for v, c in zip(vals, ("--visits", "--board", "--downloads")))
            cols.append(f'<div class="day"><div class="cols">{bars}</div><span>{html.escape(d[5:])}</span>'
                        f'<span>{vals[0]}</span></div>')
        parts.append('<section><h2>Each day</h2><div class="legend"><span><i style="background:var(--visits)"></i>main page visits</span>'
                     '<span><i style="background:var(--board)"></i>leaderboard views</span>'
                     '<span><i style="background:var(--downloads)"></i>download clicks</span></div>'
                     f'<div class="days">{"".join(cols)}</div><p class="note">The number under each day is its main page visits.</p></section>')

    # hour of day
    hours = {k: v for k, v in group(totals, "hour:")}
    if hours:
        hp = max(hours.values())
        cells = "".join(f'<div title="{h}:00 UTC: {hours.get(h, 0)}"><i style="height:{100 * hours.get(h, 0) / hp:.1f}%"></i>{h[:2] if int(h) % 3 == 0 else ""}</div>'
                        for h in (f"{i:02d}" for i in range(24)))
        parts.append(f'<section><h2>Time of day (UTC, all days together)</h2><div class="hours">{cells}</div></section>')

    parts.append('<div class="grid2">'
                 f'<section><h2>Where visitors came from</h2>{_bars(group(totals, "ref:"), group_total(totals, "ref:"), REF_NAMES)}</section>'
                 f'<section><h2>Countries</h2>{_bars([(country_name(k), v) for k, v in group(totals, "country:")], group_total(totals, "country:"), None, 15)}</section>'
                 f'<section><h2>Kinds of computer</h2>{_bars(group(totals, "os:"), group_total(totals, "os:"), OS_NAMES)}</section>'
                 f'<section><h2>Download clicks</h2>{_bars([(k, totals.get(k, 0)) for k in (*DOWNLOADS, "dl:sums") if totals.get(k)], None, DOWNLOAD_NAMES)}</section>'
                 '</div>')

    secs = [(s, totals.get("sec:" + s, 0)) for s in SECTIONS]
    parts.append('<section><h2>How far down the page people got</h2>'
                 f'{_bars(secs if any(v for _, v in secs) else [], views_since(by_day, "sec:"), SECTION_NAMES)}'
                 '<p class="note">A section counts once per visit, when it is in the middle part of the window. '
                 'The share is of the main page visits since this was first counted.</p></section>')
    parts.append(f'<section><h2>Other clicks</h2>{_bars([(k, totals.get(k, 0)) for k in CLICK_NAMES if totals.get(k)], None, CLICK_NAMES)}</section>')
    parts.append('<section><h2>Reading these numbers</h2><p class="note">A download click only opens the mirror; it is not a finished download. '
                 'Browsers that send Do Not Track or Global Privacy Control are not counted, so real numbers are somewhat higher. '
                 'Each count stops at a daily ceiling. The hour, country, computer, referrer and section counts began later than the visit '
                 'totals, so their shares are of what they could have counted, and each group of shares is of that group. They are separate '
                 'counts and nothing is stored per visit, though on a very quiet day a visit or two could still be matched up by eye. There '
                 'are no unique-visitor numbers on purpose: that would need an identifier.</p></section>')
    parts.append("</main></body></html>")
    return "".join(parts)


def write_report(rows: list, days: int = 30, path: str = None) -> str:
    path = path or os.path.join(tempfile.gettempdir(), "khvcemu_site_stats.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(rows, days))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=14, help="how many recent days to list (default 14; the page shows 30)")
    ap.add_argument("--open", action="store_true", help="write the dashboard page and open it in your browser")
    args = ap.parse_args(argv)
    print("Reading the counters (takes a few seconds)...", flush=True)
    rows = fetch_rows()
    if args.open:
        path = write_report(rows, max(args.days, 30))
        print("Opening", path)
        webbrowser.open("file:///" + path.replace("\\", "/"))
    else:
        print(summarize(rows, args.days))


if __name__ == "__main__":
    sys.exit(main())
