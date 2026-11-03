// node test.js
//
// Runs the worker against a real SQLite database (node:sqlite) wearing a D1
// interface, so the SQL is exercised, not mocked. The replies printed with
// "PARITY" are compared byte for byte against the Python offline table by
// tests/test_leaderboard_parity.py, because the game's parser is unforgiving.
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import assert from "node:assert";
import worker, { reply, validLevel, validScore, validStats, MAX_SCORE, MAX_SCORES_PER_DAY, SITE_EVENTS } from "./worker.js";
import { ownerEmail } from "./feedback.js";

// the database as it was before the Munny/EXP/level columns (what the live one is until migrated)
const OLD_SCHEMA = `
CREATE TABLE scores (id INTEGER PRIMARY KEY AUTOINCREMENT, posted INTEGER NOT NULL, aid TEXT NOT NULL,
  lid TEXT NOT NULL, score INTEGER NOT NULL, secs INTEGER);
CREATE TABLE recent (k TEXT NOT NULL, seen INTEGER NOT NULL);`;

function makeDb(schema = readFileSync(new URL("./schema.sql", import.meta.url), "utf8")) {
  const db = new DatabaseSync(":memory:");
  db.exec(schema);
  return {
    prepare(sql) {
      const stmt = db.prepare(sql);
      let args = [];
      const api = {
        bind(...a) { args = a.map((v) => (v === undefined ? null : v)); return api; },
        first() { return stmt.get(...args) ?? null; },
        all() { return { results: stmt.all(...args) }; },
        run() { return stmt.run(...args); },
      };
      return api;
    },
  };
}

const env = (schema) => ({ DB: makeDb(schema), IP_SALT: "test-salt" });
const row = (score, secs, munny = null, exp = null, level = null, device = null) => ({ score, secs, munny, exp, level, device });
const plain = (scores) => scores.map(({ posted, ...r }) => r);   // the board's rows without the time each was posted

let nextHost = 0;       // each request is from a new address unless a test says otherwise,
                        // because one address may only post once every ten minutes
async function get(e, path, ip = `10.0.${nextHost >> 8}.${nextHost++ & 255}`) {
  const res = await worker.fetch(
    new Request("https://example.workers.dev" + path, {
      method: "GET",
      headers: { "cf-connecting-ip": ip },
    }), e);
  return { status: res.status, body: await res.text() };
}

// t is the game's own running clock, which the server ignores; pt is the play time the emulator measured
const rank = (lid, s, pt = 600) => `/disney/rank.php?uid=&aid=KH&lid=${lid}&s=${s}&t=55&pt=${pt}&u1=1&u2=`;
// the same with the Munny, EXP and level the emulator read from the Summary screen
const rankStats = (lid, s, mn, ex, lv, pt = 600) => rank(lid, s, pt) + `&mn=${mn}&ex=${ex}` + (lv === undefined ? "" : `&lv=${lv}`);
const rankex = (lids, ss) => `/disney/rankex.php?uid=&aid=KH&lid=${lids}&s=${ss}&t=12&u1=1`;

let failures = 0;
async function check(name, fn) {
  try { await fn(); console.log("  ok   " + name); }
  catch (err) { failures++; console.log("  FAIL " + name + "\n       " + err.message); }
}

const parity = [];
async function recordParity(e, path) {
  const r = await get(e, path);
  parity.push(path + "  =>  " + r.body);
  return r;
}

console.log("worker:");
const board = async (e, lid) => (await top(e)).json.worlds[lid].scores.map((r) => r.score);
const top = async (e) => { const r = await worker.fetch(new Request("https://x/top", { headers: { "cf-connecting-ip": "9.9.9.9" } }), e); return { status: r.status, headers: r.headers, json: await r.json() }; };

await check("a first score ranks first", async () => {
  const e = env();
  assert.deepStrictEqual(await get(e, rank("island", 1500)),
    { status: 200, body: "*r|ok|anon~|island~1" });
});

await check("ranks count every score posted, ties sharing a place", async () => {
  const e = env();
  await get(e, rank("island", 1500));
  assert.strictEqual((await get(e, rank("island", 900, 601))).body, "*r|ok|anon~|island~2");
  assert.strictEqual((await get(e, rank("island", 2000, 602))).body, "*r|ok|anon~|island~1");
  assert.strictEqual((await get(e, rank("island", 900, 601))).body, "*r|ok|anon~|island~3");
  assert.strictEqual((await get(e, rank("island", 2000, 602))).body, "*r|ok|anon~|island~1");
});

await check("levels are ranked separately", async () => {
  const e = env();
  await get(e, rank("island", 5000));
  assert.strictEqual((await get(e, rank("agrabah", 10))).body, "*r|ok|anon~|agrabah~1");
});

await check("rankex ranks the game's own table and skips unposted levels", async () => {
  const e = env();
  await get(e, rank("island", 1500));
  await get(e, rank("island", 2000, 601));
  assert.strictEqual((await get(e, rankex("wonderland,island", "1,1500"))).body,
    "*r|ok|anon~|island~2");
  assert.strictEqual((await get(e, rankex("wonderland", "1"))).body, "*r|ok|anon~");
});

await check("junk is rejected without being stored", async () => {
  const e = env();
  for (const bad of [rank("island", "abc"), rank("island", -5), rank("", 5),
                     rank("notaworld", 5), rank("island", 99999999999)]) {
    assert.strictEqual((await get(e, bad)).body, "*r|invalidentry", bad);
  }
  assert.strictEqual((await get(e, rank("island", 1))).body, "*r|ok|anon~|island~1",
    "nothing above was stored");
});

await check("one score per address per ten minutes, silently", async () => {
  const e = env();
  const rows = () => e.DB.prepare("SELECT score FROM scores ORDER BY score").all().results.map((r) => r.score);
  assert.strictEqual((await get(e, rank("island", 500), "9.9.9.9")).body, "*r|ok|anon~|island~1");
  const again = await get(e, rank("island", 900), "9.9.9.9");
  assert.strictEqual(again.body, "*r|ok|anon~|island~1", "the game sees a normal answer, with the rank it would have had");
  assert.deepStrictEqual(rows(), [500], "but the second score was not kept");
  assert.deepStrictEqual(await board(e, "island"), [500]);
  assert.ok((await get(e, rank("island", 50, 650), "5.5.5.5")).body.startsWith("*r|ok|anon~|island~"), "another address is unaffected");
  assert.deepStrictEqual(rows(), [50, 500]);
  e.DB.prepare("UPDATE recent SET seen = seen - 601").run();          // ten minutes later
  await get(e, rank("island", 900, 700), "9.9.9.9");
  assert.deepStrictEqual(rows(), [50, 500, 900], "allowed again after the wait");
});

await check("the same score with the same time is stored once, another world is separate", async () => {
  const e = env();
  await get(e, rank("island", 918, 700));
  const again = await get(e, rank("island", 918, 700));
  assert.strictEqual(again.body, "*r|ok|anon~|island~1");
  await get(e, rank("agrabah", 918, 700));
  assert.strictEqual(e.DB.prepare("SELECT COUNT(*) AS n FROM scores").first().n, 2);
  assert.deepStrictEqual(await board(e, "island"), [918]);
});

await check("runs under the world's minimum time, or with no measured time, are answered but not stored", async () => {
  const e = env();
  const slow = (await get(e, rank("island", 500, 360))).body;       // exactly the minimum is fine
  assert.strictEqual(slow, "*r|ok|anon~|island~1");
  const fast = (await get(e, rank("island", 900, 359))).body;       // one second short
  assert.strictEqual(fast, "*r|ok|anon~|island~1", "the game sees an ordinary answer");
  const none = (await get(e, "/disney/rank.php?uid=&aid=KH&lid=island&s=950&t=8526672&u1=1&u2=")).body;
  assert.ok(none.startsWith("*r|ok|anon~|island~"), "no pt: the game's own clock is not trusted");
  assert.strictEqual((await get(e, rank("island", 960, "abc"))).body.startsWith("*r|ok"), true);
  assert.strictEqual((await get(e, rank("island", 970, 90000))).body.startsWith("*r|ok"), true, "over a day is not a run");
  assert.deepStrictEqual(await board(e, "island"), [500], "only the valid run was kept");
});

await check("equal scores are ordered by the faster time, and times are shown", async () => {
  const e = env();
  assert.strictEqual((await get(e, rank("island", 1000, 900))).body, "*r|ok|anon~|island~1");
  assert.strictEqual((await get(e, rank("island", 1000, 600))).body, "*r|ok|anon~|island~1", "faster takes first place");
  assert.strictEqual((await get(e, rank("island", 1000, 1200))).body, "*r|ok|anon~|island~3", "slower goes behind both");
  assert.strictEqual((await get(e, rank("island", 2000, 3000))).body, "*r|ok|anon~|island~1", "a higher score still wins");
  const t = await top(e);
  assert.deepStrictEqual(plain(t.json.worlds.island.scores),
    [row(2000, 3000), row(1000, 600), row(1000, 900), row(1000, 1200)]);
  assert.deepStrictEqual(t.json.minSeconds, { training: 60, island: 360, wonderland: 360, agrabah: 600, castle: 480 });
});

await check("older scores without a time still show, after timed ones of the same score", async () => {
  const e = env();
  e.DB.prepare("INSERT INTO scores (posted, aid, lid, score, secs) VALUES (1, 'KH', 'island', 700, NULL)").run();
  await get(e, rank("island", 700, 500));
  assert.deepStrictEqual(plain((await top(e)).json.worlds.island.scores), [row(700, 500), row(700, null)]);
  const e2 = (await get(e, "/disney/rankex.php?uid=&aid=KH&lid=island&s=700&t=12&u1=1")).body;
  assert.strictEqual(e2, "*r|ok|anon~|island~1", "the Score screen cannot split a tie, so it shares the place");
});

await check("a refused repeat does not extend the wait", async () => {
  const e = env();
  await get(e, rank("island", 500), "7.7.7.7");
  e.DB.prepare("UPDATE recent SET seen = seen - 400").run();
  await get(e, rank("island", 600, 610), "7.7.7.7");                 // dropped, must not reset the clock
  e.DB.prepare("UPDATE recent SET seen = seen - 250").run();         // 650 s after the first
  await get(e, rank("island", 700, 620), "7.7.7.7");
  assert.deepStrictEqual(e.DB.prepare("SELECT score FROM scores ORDER BY score").all().results.map((r) => r.score), [500, 700]);
});

await check("no identity is stored", async () => {
  const e = env();
  await get(e, rank("island", 1500));
  const cols = e.DB.prepare("SELECT * FROM scores").all().results[0];
  assert.deepStrictEqual(Object.keys(cols).sort(),
    ["aid", "device", "exp", "id", "level", "lid", "munny", "posted", "score", "secs", "version"]);
});

await check("a replayed time (a save state at a Summary) is not stored, a new time is", async () => {
  const e = env();
  const rows = () => e.DB.prepare("SELECT score, secs FROM scores ORDER BY id").all().results.map((r) => [r.score, r.secs]);
  await get(e, rank("island", 939, 1590));
  const again = await get(e, rank("island", 918, 1590));                  // another score with the very same time
  assert.ok(again.body.startsWith("*r|ok|anon~|island~"), "answered like any post");
  assert.deepStrictEqual(rows(), [[939, 1590]], "the replay is not kept");
  await get(e, rank("agrabah", 24005, 1590));                             // another world may share the time
  await get(e, rank("island", 944, 1591));                                // a different time is a different run
  assert.deepStrictEqual(rows(), [[939, 1590], [24005, 1590], [944, 1591]]);
  e.DB.prepare("UPDATE scores SET posted = posted - 8 * 86400").run();    // more than a week later
  await get(e, rank("island", 930, 1590));
  assert.deepStrictEqual(rows().length, 4, "an old time no longer blocks");
});

await check("at most MAX_SCORES_PER_DAY are stored a day", async () => {
  const e = env();
  const now = Math.floor(Date.now() / 1000);
  for (let i = 0; i < MAX_SCORES_PER_DAY; i++) {
    e.DB.prepare("INSERT INTO scores (posted, aid, lid, score, secs) VALUES (?, 'KH', 'castle', ?, ?)").bind(now - 60, i, 10000 + i).run();
  }
  const r = await get(e, rank("island", 939, 1590));
  assert.ok(r.body.startsWith("*r|ok|anon~|island~"), "answered as usual");
  assert.strictEqual(e.DB.prepare("SELECT COUNT(*) AS n FROM scores WHERE lid = 'island'").first().n, 0, "and not stored");
  e.DB.prepare("UPDATE scores SET posted = posted - 86400").run();        // a day later
  await get(e, rank("island", 939, 1590));
  assert.strictEqual(e.DB.prepare("SELECT COUNT(*) AS n FROM scores WHERE lid = 'island'").first().n, 1);
});

await check("the device and version are stored when sent and believable; the board shows only the device", async () => {
  const e = env();
  await get(e, rank("island", 939, 1590) + "&pl=android&vr=0.2.0");
  await get(e, rank("agrabah", 24005, 3235) + "&pl=toaster&vr=<script>");
  await get(e, rank("castle", 51282, 2556));
  const got = e.DB.prepare("SELECT lid, device, version FROM scores ORDER BY id").all().results;
  assert.deepStrictEqual(got.map((r) => [r.lid, r.device, r.version]),
    [["island", "android", "0.2.0"], ["agrabah", null, null], ["castle", null, null]]);
  const shown = (await top(e)).json.worlds;
  assert.deepStrictEqual([shown.island.scores[0].device, shown.agrabah.scores[0].device, shown.castle.scores[0].device],
    ["android", null, null], "/top shows the device, null when not sent");
  assert.ok(!/0\.2\.0/.test(JSON.stringify(shown)), "/top does not show the version");
  const old = env(OLD_SCHEMA);                                            // a database before migrate_001 and 003
  await get(old, rank("island", 939, 1590) + "&pl=windows&vr=0.2.0");
  assert.strictEqual(old.DB.prepare("SELECT COUNT(*) AS n FROM scores").first().n, 1, "still stored without the columns");
  const oldRow = (await top(old)).json.worlds.island.scores[0];
  assert.strictEqual(oldRow.device, null, "without the column /top still answers, with no device");
  assert.strictEqual(typeof oldRow.posted, "number");
});

await check("other paths and methods are refused", async () => {
  const e = env();
  assert.strictEqual((await get(e, "/disney/download.php?f=wonderland.dat")).status, 404);
  const res = await worker.fetch(new Request("https://x/disney/rank.php", { method: "POST" }), e);
  assert.strictEqual(res.status, 405);
});

await check("scores above the ceiling are refused and never shown", async () => {
  const e = env();
  assert.strictEqual((await get(e, rank("island", MAX_SCORE + 1))).body, "*r|invalidentry");
  assert.match((await get(e, rank("island", MAX_SCORE))).body, /island~1/);
  e.DB.prepare("INSERT INTO scores (posted, aid, lid, score, secs) VALUES (1, 'KH', 'island', 1000001, NULL)").run();
  const t = await top(e);
  assert.deepStrictEqual(t.json.worlds.island.scores.map((r) => r.score), [MAX_SCORE]);
  assert.strictEqual(t.json.worlds.island.total, 1);
});

await check("/top lists the best hundred per world, highest first, and is public", async () => {
  const e = env();
  for (let i = 1; i <= 120; i++) {
    e.DB.prepare("INSERT INTO scores (posted, aid, lid, score, secs) VALUES (1, 'KH', 'castle', ?, NULL)").bind(i * 100).run();
  }
  const t = await top(e);
  assert.strictEqual(t.status, 200);
  assert.strictEqual(t.headers.get("access-control-allow-origin"), "*");
  const got = t.json.worlds.castle.scores.map((r) => r.score);
  assert.strictEqual(got.length, 100);
  assert.deepStrictEqual(got.slice(0, 3), [12000, 11900, 11800]);
  assert.strictEqual(got[99], 2100, "the 100th is the 21st-lowest of 120");
  assert.strictEqual(t.json.worlds.castle.scores[0].posted, 1, "each score says when it was posted");
  assert.strictEqual(t.json.worlds.castle.total, 120, "the total counts them all");
  const few = await worker.fetch(new Request("https://x/top?n=10", { headers: { "cf-connecting-ip": "9.9.9.9" } }), e);
  assert.strictEqual((await few.json()).worlds.castle.scores.length, 10, "?n= asks for fewer");
  const many = await worker.fetch(new Request("https://x/top?n=5000", { headers: { "cf-connecting-ip": "9.9.9.9" } }), e);
  assert.strictEqual((await many.json()).worlds.castle.scores.length, 100, "but never more than 100");
  assert.deepStrictEqual(t.json.worlds.island, { scores: [], total: 0 });
  assert.ok(!("wonderland" in t.json.worlds) && !("training" in t.json.worlds));
  assert.deepStrictEqual(Object.keys(t.json).sort(), ["max", "minSeconds", "updated", "worlds"]);
});

await check("Munny, EXP and level are stored and shown with the score", async () => {
  const e = env();
  const r = await get(e, rankStats("island", 1531, 931, 6, 2));
  assert.strictEqual(r.body, "*r|ok|anon~|island~1", "the game's reply is unchanged");
  await get(e, rankStats("island", 2880, 1480, 14, 3, 1312));
  const t = await top(e);
  assert.deepStrictEqual(plain(t.json.worlds.island.scores), [row(2880, 1312, 1480, 14, 3), row(1531, 600, 931, 6, 2)]);
  assert.strictEqual(t.json.worlds.island.scores[0].munny + 100 * t.json.worlds.island.scores[0].exp, 2880);
});

await check("Munny and EXP that do not make the score are dropped silently", async () => {
  const e = env();
  const wrong = await get(e, rankStats("island", 1531, 931, 7, 2));            // 931 + 700 is not 1531
  assert.ok(wrong.body.startsWith("*r|ok|anon~|island~"), "the game sees an ordinary answer");
  for (const p of [rankStats("island", 1531, 931, "x", 2), rankStats("island", 1531, -69, 16, 2),
                   rankStats("island", 1531, 931, 6, 100), rankStats("island", 1531, 931, 6, -1),
                   rankStats("island", 1531, 931.5, 6, 2), `${rank("island", 1531)}&mn=931`, `${rank("island", 1531)}&ex=6`]) {
    assert.ok((await get(e, p)).body.startsWith("*r|ok"));
  }
  assert.deepStrictEqual(await board(e, "island"), [], "nothing was kept");
  assert.ok((await get(e, rankStats("island", 1531, 931, 6))).body.endsWith("island~1"));
  assert.deepStrictEqual(plain((await top(e)).json.worlds.island.scores), [row(1531, 600, 931, 6, null)], "level is optional");
});

await check("older clients that send no Munny or EXP are still accepted", async () => {
  const e = env();
  await get(e, rank("island", 1000));
  assert.deepStrictEqual(plain((await top(e)).json.worlds.island.scores), [row(1000, 600)]);
});

await check("a database without the new columns still works, in either deploy order", async () => {
  const e = env(OLD_SCHEMA);
  const first = await get(e, rankStats("island", 1531, 931, 6, 2)); assert.ok(first.body.endsWith("island~1"), first.status + " " + first.body);
  assert.deepStrictEqual(plain((await top(e)).json.worlds.island.scores), [{ score: 1531, secs: 600, munny: null, exp: null, level: null, device: null }],
    "the score is kept, without the numbers it could not store");
  // ...then the migration is run, and from the next score on they are kept
  for (const col of ["munny", "exp", "level"]) e.DB.prepare(`ALTER TABLE scores ADD COLUMN ${col} INTEGER`).run();
  await get(e, rankStats("island", 2880, 1480, 14, 3, 700));
  assert.deepStrictEqual(plain((await top(e)).json.worlds.island.scores), [row(2880, 700, 1480, 14, 3), row(1531, 600)]);
});

// the website's anonymous counters
async function hit(e, name, headers = {}, method = "GET", { query = "", country } = {}) {
  const req = new Request("https://scores.khrecast.com/hit?e=" + encodeURIComponent(name) + query,
    { method, headers: { "cf-connecting-ip": "10.9.9.9", ...headers } });
  if (country !== undefined) Object.defineProperty(req, "cf", { value: { country } });   // what Cloudflare adds in production
  return await worker.fetch(req, e);
}
const allCounts = (e) => Object.fromEntries(e.DB.prepare("SELECT day, name, n FROM site_stats ORDER BY name").all().results
  .map((r) => [r.day + " " + r.name, r.n]));
const DIMENSIONS = /^(hour|country|os|ref):/;
const counts = (e) => Object.fromEntries(Object.entries(allCounts(e)).filter(([k]) => !DIMENSIONS.test(k.slice(11))));   // the main counters
const dims = (e) => Object.fromEntries(Object.entries(allCounts(e)).filter(([k]) => DIMENSIONS.test(k.slice(11))).map(([k, v]) => [k.slice(11), v]));
const today = () => new Date().toISOString().slice(0, 10);

await check("page views and button clicks are counted per day, per name", async () => {
  const e = env();
  const day = today();
  for (let i = 0; i < 3; i++) assert.strictEqual((await hit(e, "view:home")).status, 204);
  await hit(e, "dl:win64");
  assert.deepStrictEqual(counts(e), { [day + " dl:win64"]: 1, [day + " view:home"]: 3 });
  const res = await hit(e, "view:home");
  assert.strictEqual(res.headers.get("cache-control"), "no-store");
  assert.strictEqual(res.headers.get("set-cookie"), null, "no cookie");
  assert.strictEqual(await res.text(), "");
});

await check("only the known names are counted, so the table cannot be filled", async () => {
  const e = env();
  for (const bad of ["", "view:other", "dl:../../x", "<script>", "x".repeat(500), "dl:win64 ", "VIEW:HOME", "hour:00", "country:US", "ref:reddit", "sec:other"]) {
    assert.strictEqual((await hit(e, bad)).status, 204, "the page is never told off");
  }
  assert.deepStrictEqual(allCounts(e), {});
  assert.ok(Object.keys(SITE_EVENTS).length < 40);
  // the most the counters can write in a day: every name to its ceiling, plus the four extra tallies of each home view
  const bound = Object.values(SITE_EVENTS).reduce((a, b) => a + b, 0) + 4 * SITE_EVENTS["view:home"];
  assert.ok(bound <= 66500, `the counters can write up to ${bound} rows a day; the comments in worker.js and README say about 66,000`);
});

await check("a probe, a wrong method or another site does not count; one of ours, or no referrer, does", async () => {
  const e = env();
  await hit(e, "view:home", {}, "HEAD");
  assert.strictEqual((await hit(e, "view:home", {}, "POST")).status, 405);
  await hit(e, "view:home", { referer: "https://evil.example/page" });
  await hit(e, "view:home", { referer: "not a url" });
  assert.deepStrictEqual(allCounts(e), {});
  await hit(e, "view:home", { referer: "https://khrecast.com/" });
  await hit(e, "view:leaderboard", { referer: "https://www.khrecast.com/leaderboard" });
  await hit(e, "dl:sums");                                  // fetch with no referrer (privacy settings)
  assert.strictEqual(Object.values(counts(e)).reduce((a, b) => a + b, 0), 3);
});

await check("a section scrolled to counts under its own name", async () => {
  const e = env();
  for (const sec of ["about", "download", "wonderland", "credits"]) await hit(e, "sec:" + sec);
  await hit(e, "sec:download");
  const c = counts(e), day = today();
  assert.strictEqual(c[day + " sec:download"], 2);
  assert.strictEqual(c[day + " sec:about"], 1);
  assert.deepStrictEqual(dims(e), {}, "only an opening of the main page adds the other tallies");
});

await check("an opening of the main page also tallies hour, country, system and where from, as separate counts", async () => {
  const e = env();
  const hour = String(new Date().getUTCHours()).padStart(2, "0");
  await hit(e, "view:home", {}, "GET", { query: "&o=windows&r=reddit", country: "us" });
  await hit(e, "view:home", {}, "GET", { query: "&o=windows&r=direct", country: "GB" });
  assert.deepStrictEqual(dims(e), {
    ["hour:" + hour]: 2, "country:US": 1, "country:GB": 1, "os:windows": 2, "ref:reddit": 1, "ref:direct": 1,
  });
  assert.strictEqual(counts(e)[today() + " view:home"], 2);
});

await check("the extra tallies cannot be filled with made-up values, and a missing value is simply skipped", async () => {
  const e = env();
  await hit(e, "view:home", {}, "GET", { query: "&o=<script>&r=evil.example", country: "USA" });
  await hit(e, "view:home", {}, "GET", { query: "&o=windows" });                              // no referrer bucket, no country (local test)
  await hit(e, "view:home", {}, "GET", { query: "&o=" + "x".repeat(300) + "&r=" + "y".repeat(300), country: "" });
  await hit(e, "view:home", {}, "GET", { query: "&o=mac&r=google", country: "XX" });
  await hit(e, "view:home", {}, "GET", { query: "&o=mac&r=google", country: "T1" });          // Tor: a real value Cloudflare may send
  const d = dims(e);
  assert.deepStrictEqual(Object.keys(d).filter((k) => !k.startsWith("hour:")).sort(),
    ["country:T1", "country:XX", "os:mac", "os:windows", "ref:google"]);
  assert.strictEqual(d["os:mac"], 2);
  assert.strictEqual(Object.keys(allCounts(e)).length < 12, true, "a handful of rows, not one per request");
});

await check("a name stops counting at its daily ceiling, and the extra tallies stop with it", async () => {
  const e = env();
  const day = today();
  const cap = SITE_EVENTS["dl:sums"];
  assert.strictEqual(cap, 600);
  for (let i = 0; i < cap + 25; i++) await hit(e, "dl:sums");
  assert.strictEqual(counts(e)[day + " dl:sums"], cap, "it stops at the ceiling");
  await hit(e, "view:home");
  assert.strictEqual(counts(e)[day + " view:home"], 1, "the other names are not affected");
  // the main page, with a small ceiling: past it neither the count nor its tallies move
  const real = SITE_EVENTS["view:home"];
  SITE_EVENTS["view:home"] = 3;
  try {
    for (let i = 0; i < 10; i++) await hit(e, "view:home", {}, "GET", { query: "&o=linux&r=github", country: "DE" });
  } finally { SITE_EVENTS["view:home"] = real; }
  assert.strictEqual(counts(e)[day + " view:home"], 3);
  assert.strictEqual(dims(e)["os:linux"], 2, "3 views counted (one earlier, without a system type): the 7 above the ceiling add nothing");
  // the worst case of all the ceilings together stays well under the free plan's daily writes
  const total = Object.entries(SITE_EVENTS).reduce((a, [n, c]) => a + c * (n === "view:home" ? 5 : 1), 0);
  assert.ok(total < 66500, "writes a day at the ceilings: " + total);
});

await check("if the database does not say whether a row changed, the extra tallies are not written (the ceiling is never skipped)", async () => {
  const e = env();
  const real = e.DB.prepare.bind(e.DB);
  e.DB = { prepare(sql) { const api = real(sql); const run = api.run; api.run = () => { run(); return {}; }; return api; } };   // a run() with no change count
  await hit(e, "view:home", {}, "GET", { query: "&o=windows&r=reddit", country: "US" });
  const rows = Object.keys(allCounts(e));
  assert.deepStrictEqual(rows, [today() + " view:home"], "the main count is written, nothing extra");
});

await check("no identity is stored with the counters, and a database without the table still answers", async () => {
  const e = env();
  await hit(e, "view:home", { "user-agent": "Mozilla/5.0 secret", cookie: "a=b" }, "GET", { query: "&o=mac&r=reddit", country: "US" });
  const cols = e.DB.prepare("SELECT * FROM site_stats").all().results[0];
  assert.deepStrictEqual(Object.keys(cols).sort(), ["day", "n", "name"]);
  const everything = JSON.stringify(e.DB.prepare("SELECT * FROM site_stats").all().results);
  assert.ok(!/secret|a=b|10\.9\.9\.9/.test(everything), "nothing from the request itself is kept");
  const old = env(OLD_SCHEMA);                              // the live database until migrate_002 is run
  assert.strictEqual((await hit(old, "view:home", {}, "GET", { query: "&o=mac", country: "US" })).status, 204, "the page is not hurt by a missing table");
});

await check("helpers", () => {
  const q = (s) => new URLSearchParams(s);
  assert.strictEqual(validStats(q(""), 500), null);
  assert.deepStrictEqual(validStats(q("mn=100&ex=4&lv=1"), 500), { munny: 100, exp: 4, level: 1 });
  assert.deepStrictEqual(validStats(q("mn=500&ex=0"), 500), { munny: 500, exp: 0, level: null });
  assert.strictEqual(validStats(q("mn=100&ex=3"), 500), false);
  assert.strictEqual(validStats(q("mn=100"), 500), false);
  assert.strictEqual(validStats(q("mn=100&ex=4&lv=abc"), 500), false);
  assert.strictEqual(reply([]), "*r|ok|anon~");
  assert.strictEqual(validLevel("ISLAND"), "island");
  assert.strictEqual(validLevel("island|evil"), null);
  assert.strictEqual(validScore("12"), 12);
  assert.strictEqual(validScore("1.5"), null);
});

// ------------------------------------------------------------------ the feedback board (feedback.js)
console.log("feedback:");
const SITE = "https://khrecast.com";
let fbHost = 0;
async function fb(e, method, path, { body = null, origin = SITE, key = null, ip = `10.8.${fbHost >> 8}.${fbHost++ & 255}` } = {}) {
  const headers = { "cf-connecting-ip": ip, "content-type": "application/x-www-form-urlencoded" };
  if (origin) headers.origin = origin;
  if (key !== null) headers["x-feedback-key"] = key;
  const res = await worker.fetch(new Request("https://scores.khrecast.com" + path, { method, headers,
    body: body === null ? undefined : new URLSearchParams(body).toString() }), e);
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { /* the admin page is HTML */ }
  return { status: res.status, headers: res.headers, text, data };
}
const entry = (extra = {}) => ({ kind: "bug", message: "The sound stops in the lava cave.", nick: "Sora", device: "android",
  version: "0.2.0", email: "", website: "", t: String(Date.now() - 60000), s: String(Date.now()), ...extra });
const fbEnv = () => ({ ...env(), FEEDBACK_KEY: "k".repeat(32) });

await check("a post from the website is stored and shown at once, without its email", async () => {
  const e = fbEnv();
  const r = await fb(e, "POST", "/feedback", { body: entry({ email: "sora@example.com" }) });
  assert.strictEqual(r.status, 200);
  assert.deepStrictEqual(r.data, { ok: true, id: 1 });
  assert.strictEqual(r.headers.get("access-control-allow-origin"), SITE);
  const list = await fb(e, "GET", "/feedback");
  assert.strictEqual(list.data.total, 1);
  const p = list.data.posts[0];
  assert.deepStrictEqual([p.kind, p.nick, p.device, p.version, p.message, p.fixed, p.reply],
    ["bug", "Sora", "android", "0.2.0", "The sound stops in the lava cave.", false, null]);
  assert.ok(!list.text.includes("sora@example.com"), "the email is never shown");
  assert.strictEqual(list.headers.get("access-control-allow-origin"), "*");
});

await check("feedback refuses junk, and robots are told it worked", async () => {
  const e = fbEnv();
  const count = () => e.DB.prepare("SELECT COUNT(*) AS n FROM feedback").first().n;
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry(), origin: "https://evil.example" })).status, 403);
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry(), origin: null })).status, 403);
  assert.deepStrictEqual((await fb(e, "POST", "/feedback", { body: entry({ website: "http://spam" }) })).data, { ok: true, id: null }, "the hidden field");
  assert.deepStrictEqual((await fb(e, "POST", "/feedback", { body: entry({ t: String(Date.now() - 500) }) })).data, { ok: true, id: null }, "sent too fast");
  const skewed = await fb(e, "POST", "/feedback", { body: entry({ t: "5000", s: "65000" }) });        // a clock set far wrong: only the gap counts
  assert.strictEqual(skewed.status, 200);
  assert.ok(skewed.data.id > 0, "a visitor whose clock is wrong still gets in");
  e.DB.prepare("DELETE FROM feedback").run();
  assert.deepStrictEqual((await fb(e, "POST", "/feedback", { body: entry({ t: "" }) })).data, { ok: true, id: null }, "no clock");
  const stale = await fb(e, "POST", "/feedback", { body: entry({ t: "1000", s: String(3 * 86400 * 1000) }) });
  assert.strictEqual(stale.status, 400, "a page open for days is told to reload, not silently dropped");
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry({ kind: "spam" }) })).status, 400);
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry({ message: "short" }) })).status, 400);
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry({ message: "x".repeat(3001) }) })).status, 400);
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry({ message: "see http://a.b http://c.d http://e.f www.g.h" }) })).status, 400);
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry({ email: "not an email" }) })).status, 400);
  assert.strictEqual(count(), 0);
  const ok = await fb(e, "POST", "/feedback", { body: entry({ device: "toaster", version: "<b>", nick: "Ri\r\nku\u0007", message: "Line one\nline two is here" }) });
  assert.strictEqual(ok.status, 200);
  const row = e.DB.prepare("SELECT nick, device, version, message FROM feedback").first();
  assert.deepStrictEqual({ ...row }, { nick: "Ri ku", device: null, version: null, message: "Line one\nline two is here" });
});

await check("an address may post three entries an hour", async () => {
  const e = fbEnv();
  for (let i = 0; i < 3; i++) assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry(), ip: "7.7.7.7" })).status, 200);
  const fourth = await fb(e, "POST", "/feedback", { body: entry(), ip: "7.7.7.7" });
  assert.strictEqual(fourth.status, 429);
  assert.ok(fourth.data.error.length > 0);
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry(), ip: "8.8.8.8" })).status, 200, "others are not affected");
  e.DB.prepare("UPDATE feedback_recent SET seen = seen - 3601").run();
  assert.strictEqual((await fb(e, "POST", "/feedback", { body: entry(), ip: "7.7.7.7" })).status, 200, "an hour later");
  const keys = JSON.stringify(e.DB.prepare("SELECT * FROM feedback_recent").all().results);
  assert.ok(!keys.includes("7.7.7.7"), "the address itself is not kept");
});

await check("the owner's page: key, list with emails, reply, fix, hide, delete", async () => {
  const e = fbEnv();
  await fb(e, "POST", "/feedback", { body: entry({ email: "sora@example.com" }) });
  await fb(e, "POST", "/feedback", { body: entry({ kind: "idea", message: "A New Game Plus mode please." }) });
  const page = await fb(e, "GET", "/feedback/admin");
  assert.strictEqual(page.status, 200);
  assert.ok(page.text.includes("Re:Cast journal") && !page.text.includes("sora@example.com"), "the page holds no data");
  assert.strictEqual((await fb(e, "POST", "/feedback/admin/list", { key: "wrong" })).status, 403);
  assert.strictEqual((await fb({ ...e, FEEDBACK_KEY: "" }, "POST", "/feedback/admin/list", { key: "" })).status, 503, "no key set: closed");
  const K = e.FEEDBACK_KEY;
  const all = await fb(e, "POST", "/feedback/admin/list", { key: K });
  assert.deepStrictEqual(all.data.posts.map((p) => [p.id, p.email]), [[2, null], [1, "sora@example.com"]]);
  const act = (id, action, text) => fb(e, "POST", "/feedback/admin/act", { key: K, body: { id, action, ...(text ? { text } : {}) } });
  assert.strictEqual((await act(1, "reply", "Fixed in 0.2.1, thank you!")).status, 200);
  assert.strictEqual((await act(1, "fix")).status, 200);
  assert.strictEqual((await act(2, "hide")).status, 200);
  assert.strictEqual((await act(2, "explode")).status, 400);
  let pub = (await fb(e, "GET", "/feedback")).data;
  assert.deepStrictEqual([pub.total, pub.squashed, pub.posts.length], [1, 1, 1]);
  assert.strictEqual(pub.posts[0].reply, "Fixed in 0.2.1, thank you!");
  assert.ok(pub.posts[0].replied > 0 && pub.posts[0].fixed);
  await act(2, "show");
  await act(1, "delete");
  pub = (await fb(e, "GET", "/feedback")).data;
  assert.deepStrictEqual(pub.posts.map((p) => p.id), [2]);
  assert.strictEqual((await fb(e, "POST", "/feedback/admin/act", { key: "nope", body: { id: 2, action: "delete" } })).status, 403);
});

await check("the list pages backwards, and a database without the tables still answers", async () => {
  const e = fbEnv();
  for (let i = 0; i < 25; i++) {
    e.DB.prepare("INSERT INTO feedback (posted, kind, message) VALUES (?, 'review', ?)").bind(1000 + i, "Entry number " + i).run();
  }
  const first = (await fb(e, "GET", "/feedback")).data;
  assert.deepStrictEqual([first.posts.length, first.more, first.posts[0].id], [20, true, 25]);
  const next = (await fb(e, "GET", "/feedback?before=" + first.posts.at(-1).id)).data;
  assert.deepStrictEqual([next.posts.length, next.more, next.posts.at(-1).id], [5, false, 1]);
  const old = { ...env(OLD_SCHEMA), FEEDBACK_KEY: "x" };                  // the live database until migrate_003 is run
  assert.deepStrictEqual((await fb(old, "GET", "/feedback")).data.posts, []);
  assert.strictEqual((await fb(old, "POST", "/feedback", { body: entry() })).status, 503);
  assert.strictEqual((await get(old, rank("island", 939, 1590))).status, 200, "scores are not affected");
});

await check("the owner's email: reply-to the poster, readable subject, the message intact", async () => {
  const post = { kind: "wonderland", message: "I still have a VX8100 with Wonderland on it!\nHow do I dump it?",
    nick: "Kairi ❤", device: "android", version: "0.2.0", email: "kairi@example.com" };
  const raw = ownerEmail(post, 7, 1793600000, "feedback@khrecast.com", "khrecast@gmail.com");
  assert.ok(raw.includes("Reply-To: <kairi@example.com>"));
  assert.ok(/^Subject: =\?UTF-8\?B\?[A-Za-z0-9+/=]+\?=$/m.test(raw), "a non-ASCII subject is encoded");
  assert.ok(Buffer.from(raw.match(/^Subject: =\?UTF-8\?B\?(.+)\?=$/m)[1], "base64").toString("utf8").includes("WONDERLAND INFO from Kairi"));
  const body = Buffer.from(raw.split("\r\n\r\n")[1].replace(/\r\n/g, ""), "base64").toString("utf8");
  assert.ok(body.includes("How do I dump it?") && body.includes("https://scores.khrecast.com/feedback/admin#7"));
  assert.ok(raw.includes('From: "Re:Cast journal" <feedback@khrecast.com>'), "the colon in the name is quoted");
  const none = ownerEmail({ ...post, email: null, nick: null }, 8, 1793600000, "a@b.c", "d@e.f");
  assert.ok(!none.includes("Reply-To") && none.includes("from A player"));
});

// the exact exchanges the Python side replays, for a byte-for-byte comparison
const e = env();
for (const p of [rank("island", 1500), rank("island", 2000, 601), rank("island", 900, 602),
                 rank("agrabah", 10), rankex("wonderland,island", "1,1500"),
                 rankex("island,agrabah", "2000,10"), rank("island", "abc"),
                 rank("notaworld", 5)]) {
  await recordParity(e, p);
}
const { writeFileSync } = await import("node:fs");
writeFileSync(new URL("./parity.txt", import.meta.url), parity.join("\n") + "\n");
console.log("\nwrote parity.txt (" + parity.length + " exchanges)");
console.log(failures ? `\n${failures} FAILED` : "\nall worker tests passed");
process.exit(failures ? 1 : 0);
