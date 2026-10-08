# Shared leaderboard

A small Cloudflare Worker that answers the two requests the 2005 game makes of
its ranking server, so **Score** and the end-of-world ranking can compare your
runs against other people's instead of only your own.

It is optional. khvcemu keeps every score in its own file either way, and falls
back to that the moment this server can't be reached.

## There are no accounts

The game has no name entry and never shows you another player: the only thing it
draws is a rank number next to your own score. So this server doesn't know who
anyone is, and doesn't try to.

* A row is **(level, score, seconds, Munny, EXP, level reached)**. There is no player column.
* The game needs a player-id field in the reply, so everybody is told `anon`.
* The only value derived from an address is a salted, truncated hash used to
  limit each address to one score every ten minutes (a world takes far longer, so a
  real player never notices; a second post inside the window is quietly not stored). It
  is deleted after ten minutes.

Scores come from the player's own machine, so they can be made up. Levels and
scores are range-checked, an identical score for the same world is stored once, and posting is limited to one score per address per ten minutes, which is enough to keep
the table tidy; it is not, and can't be, a competitive ranking.

## Deploying

You need a free Cloudflare account and
[Wrangler](https://developers.cloudflare.com/workers/wrangler/install-and-update/).

```sh
cd server
npx wrangler login
npx wrangler d1 create khvcemu-leaderboard     # paste the id it prints into wrangler.toml
npx wrangler d1 execute khvcemu-leaderboard --remote --file=schema.sql
npx wrangler secret put IP_SALT                # any random string
npx wrangler deploy
```

Wrangler prints the address, something like
`https://khvcemu-leaderboard.<you>.workers.dev`. Check it:

```sh
curl "https://khvcemu-leaderboard.<you>.workers.dev/disney/rank.php?lid=island&s=1500&t=60"
# *r|ok|anon~|island~1
```

To use your own domain instead (this project uses `scores.khrecast.com`), add to
`wrangler.toml` `routes = [{ pattern = "scores.example.com", custom_domain = true }]` and
run `npx wrangler deploy` again; the domain must be on the same Cloudflare account.

**Public top scores.** `GET /top` returns the best 100 scores per world (Island, Agrabah and Castle; the Obstacle Course has no score; `?n=10` asks for fewer) and how many were
posted, as JSON that any web page may read (`site/leaderboard.html` shows it). Each row is
`{score, secs, munny, exp, level}`: the score, how long the run took, and the Munny, EXP and
level it was made of (`null` for scores posted before those were sent). It carries no
addresses and nothing that says who. Scores above 1,000,000 (about twenty times
the best of a full playthrough; kept loose on purpose while it is seen how far farming enemy waves goes) are refused when posted and ignored by `/top`; the number is
`MAX_SCORE` in `worker.js`. It stops trolling, not careful cheating, because scores come from
the player's own computer and cannot be verified.

**Removing a score.** There are no accounts, so you are the moderator. From the `server`
folder, list the newest scores, then delete one by its `id`:

```sh
npx wrangler d1 execute khvcemu-leaderboard --remote --command "SELECT id, lid, score FROM scores ORDER BY id DESC LIMIT 20"
npx wrangler d1 execute khvcemu-leaderboard --remote --command "DELETE FROM scores WHERE id = 123"
```

To remove everything above some number in one go (for example after lowering `MAX_SCORE`):
`DELETE FROM scores WHERE lid = 'island' AND score > 60000`. The board refreshes within a
minute.

**Play time.** The game's own time value is a running clock, so it is ignored. The emulator
measures how long the world took and sends it as `pt` (seconds). A score with no `pt`, or a
`pt` under the minimum for that world (`MIN_SECONDS` in `worker.js`: Island 6 minutes, Agrabah 10,
Castle 8, about a quarter of a careful first clear), is answered like any other score but not stored, so the player sees no
error. Equal scores are ranked by the faster time; the same score with the same time is stored
once. The emulator sends no `pt` for a run in which a save state was loaded (or after loading one), so such a score is
not stored: this keeps save-state farming off the board, but it is the client's word, like everything else here.
Older scores that have no time still show, after timed ones. The minimums come from real first clears
(Island 26:30, Agrabah 54:00, Castle 42:30); the emulator logs times in `clear_times.csv`.

Free-tier limits are far above what this needs: a score is a few dozen bytes and
a busy day is a few hundred requests. Verify the current limits yourself before
relying on them.

## Pointing khvcemu at it

In the launcher, under **Options**, tick **Share high scores with:** and paste
the address. On the command line:

```sh
python -m khvcemu <dump> --leaderboard https://khvcemu-leaderboard.<you>.workers.dev
```

What leaves your machine is the level name, the score, how long the run took, and
the Munny, EXP and level that the game's own Summary screen showed for it. No identifier is
sent or stored, by you or by the server.

### Munny, EXP and level

Newer clients add `mn`, `ex` and `lv` to a score post. In the game, Score = Munny + 100 x EXP,
so the server drops (silently, like every other refusal) any post whose numbers do not add up
to the score, that has only one of Munny and EXP, or whose level is outside 0 to 99. A post
with none of them (an older client) is accepted as before and shows dashes on the board.

The database needs three new columns, once, from this folder:

```sh
npx wrangler d1 execute khvcemu-leaderboard --remote --file migrate_001_stats.sql
```

It only adds empty columns, so no score is changed. The worker works with or without them
(it stores the numbers only once the columns exist), so it does not matter whether this or
`npx wrangler deploy` is done first. A new database made from `schema.sql` has them already.
Errors are written to the Worker's log (`npx wrangler tail`), nothing identifying.

### Website counters

The project website counts, anonymously, how often its two pages are opened, which parts of the main page are
scrolled to, and which buttons are clicked (the six downloads, the checksums file, the source and issue links, the
soundtrack link, the contact link). The page asks `GET /hit?e=<name>` and the worker adds one to today's count for
that name in the `site_stats` table: a UTC day, a name and a number, nothing else. This project's server
reads and stores no address, cookie or browser string (Cloudflare, which hosts it, keeps its usual request
logs, as it does for every site).

Each opening of the main page (`view:home`) also adds one to four **separate** tallies, kept apart and never stored per visit, though on a very quiet day (a visit or two) the counts could still be matched up by eye: `hour:HH` (the UTC hour), `country:XX` (the country code Cloudflare gives
the worker for the connection; the address itself is neither read nor stored), `os:<kind>` (windows, mac, linux,
android, ios, chromeos or other, worked out by the page from the browser and sent as a word, never the browser
string) and `ref:<site>` (where the visitor came from, as a word from a fixed list such as reddit, google,
khinsider or direct; the page reduces the referrer to the website's name, never the address). A value that is not
on the fixed list is ignored. The sections scrolled to are `sec:about`, `sec:download` and so on, counted once per
visit.

Only the names in `SITE_EVENTS` (`worker.js`) count; anything else, a `HEAD` request, or a request that says it
came from another website, is answered `204` and ignored (a request with no `Referer` is accepted, because some
browsers send none), so the table cannot be filled with junk. Each name also stops counting at a daily ceiling
(`SITE_EVENTS`: 8,000 for the main page, 1,500 for the leaderboard, 1,000 for each section, 600 for each button;
the extra tallies stop with the main page's ceiling), which bounds the database writes the counters can cause to
about 57,000 a day, so calling the address in a loop cannot use up the free plan's daily writes and stop scores
being saved; it can still inflate a day's counts or stop them there, so these are rough counts, not proof. For
real protection add a Cloudflare rate-limiting rule for `/hit` in the dashboard. A browser that sends Do Not Track
(or Global Privacy Control) never asks. A missing table never breaks the page: the worker answers anyway. There
are no unique-visitor counts on purpose: they would need an identifier.

The database needs the table, once, from this folder:

```sh
npx wrangler d1 execute khvcemu-leaderboard --remote --file migrate_002_site_stats.sql
```

Read the totals with `tools/show_site_stats.bat` (double-click: it opens a page in your browser) or
`python tools/site_stats.py` (text); both are read-only queries through wrangler. A download click only opens
the mirror; it is not a finished download.

## Running the tests

```sh
node test.js
```

This runs the worker against a real SQLite database wearing a D1 interface, so
the SQL is exercised rather than mocked. It also writes `parity.txt`, which
`tests/test_leaderboard_parity.py` uses to check that this server and khvcemu's
offline table answer the game identically: the game's parser accepts exactly
one shape of reply, so the two must not drift apart.

## Files

| File | |
| --- | --- |
| `worker.js` | the whole server |
| `schema.sql` | the tables (scores, the rate limit, the website counters) |
| `migrate_001_stats.sql`, `migrate_002_site_stats.sql` | one-time additions for a database made before them |
| `wrangler.toml` | deployment config; paste your database id here |
| `test.js` | tests, and generates `parity.txt` |
