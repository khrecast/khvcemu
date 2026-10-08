// node test.js
//
// Runs the worker against a real SQLite database (node:sqlite) wearing a D1
// interface, so the SQL is exercised, not mocked. The replies printed with
// "PARITY" are compared byte for byte against the Python offline table by
// tests/test_leaderboard_parity.py, because the game's parser is unforgiving.
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import assert from "node:assert";
import worker, { reply, validLevel, validScore, validStats, MAX_SCORE, SITE_EVENTS } from "./worker.js";

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
const row = (score, secs, munny = null, exp = null, level = null) => ({ score, secs, munny, exp, level });

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
  assert.strictEqual((await get(e, rank("island", 900))).body, "*r|ok|anon~|island~2");
  assert.strictEqual((await get(e, rank("island", 2000))).body, "*r|ok|anon~|island~1");
  assert.strictEqual((await get(e, rank("island", 900))).body, "*r|ok|anon~|island~3");
  assert.strictEqual((await get(e, rank("island", 2000))).body, "*r|ok|anon~|island~1");
});

await check("levels are ranked separately", async () => {
  const e = env();
  await get(e, rank("island", 5000));
  assert.strictEqual((await get(e, rank("agrabah", 10))).body, "*r|ok|anon~|agrabah~1");
});

await check("rankex ranks the game's own table and skips unposted levels", async () => {
  const e = env();
  await get(e, rank("island", 1500));
  await get(e, rank("island", 2000));
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
  assert.ok((await get(e, rank("island", 50), "5.5.5.5")).body.startsWith("*r|ok|anon~|island~"), "another address is unaffected");
  assert.deepStrictEqual(rows(), [50, 500]);
  e.DB.prepare("UPDATE recent SET seen = seen - 601").run();          // ten minutes later
  await get(e, rank("island", 900), "9.9.9.9");
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
  assert.deepStrictEqual(t.json.worlds.island.scores,
    [row(2000, 3000), row(1000, 600), row(1000, 900), row(1000, 1200)]);
  assert.deepStrictEqual(t.json.minSeconds, { training: 60, island: 360, wonderland: 360, agrabah: 600, castle: 480 });
});

await check("older scores without a time still show, after timed ones of the same score", async () => {
  const e = env();
  e.DB.prepare("INSERT INTO scores (posted, aid, lid, score, secs) VALUES (1, 'KH', 'island', 700, NULL)").run();
  await get(e, rank("island", 700, 500));
  assert.deepStrictEqual((await top(e)).json.worlds.island.scores, [row(700, 500), row(700, null)]);
  const e2 = (await get(e, "/disney/rankex.php?uid=&aid=KH&lid=island&s=700&t=12&u1=1")).body;
  assert.strictEqual(e2, "*r|ok|anon~|island~1", "the Score screen cannot split a tie, so it shares the place");
});

await check("a refused repeat does not extend the wait", async () => {
  const e = env();
  await get(e, rank("island", 500), "7.7.7.7");
  e.DB.prepare("UPDATE recent SET seen = seen - 400").run();
  await get(e, rank("island", 600), "7.7.7.7");                      // dropped, must not reset the clock
  e.DB.prepare("UPDATE recent SET seen = seen - 250").run();         // 650 s after the first
  await get(e, rank("island", 700), "7.7.7.7");
  assert.deepStrictEqual(e.DB.prepare("SELECT score FROM scores ORDER BY score").all().results.map((r) => r.score), [500, 700]);
});

await check("no identity is stored", async () => {
  const e = env();
  await get(e, rank("island", 1500));
  const cols = e.DB.prepare("SELECT * FROM scores").all().results[0];
  assert.deepStrictEqual(Object.keys(cols).sort(),
    ["aid", "exp", "id", "level", "lid", "munny", "posted", "score", "secs"]);
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
  assert.deepStrictEqual(t.json.worlds.island.scores, [row(2880, 1312, 1480, 14, 3), row(1531, 600, 931, 6, 2)]);
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
  assert.deepStrictEqual((await top(e)).json.worlds.island.scores, [row(1531, 600, 931, 6, null)], "level is optional");
});

await check("older clients that send no Munny or EXP are still accepted", async () => {
  const e = env();
  await get(e, rank("island", 1000));
  assert.deepStrictEqual((await top(e)).json.worlds.island.scores, [row(1000, 600)]);
});

await check("a database without the new columns still works, in either deploy order", async () => {
  const e = env(OLD_SCHEMA);
  const first = await get(e, rankStats("island", 1531, 931, 6, 2)); assert.ok(first.body.endsWith("island~1"), first.status + " " + first.body);
  assert.deepStrictEqual((await top(e)).json.worlds.island.scores, [{ score: 1531, secs: 600, munny: null, exp: null, level: null }],
    "the score is kept, without the numbers it could not store");
  // ...then the migration is run, and from the next score on they are kept
  for (const col of ["munny", "exp", "level"]) e.DB.prepare(`ALTER TABLE scores ADD COLUMN ${col} INTEGER`).run();
  await get(e, rankStats("island", 2880, 1480, 14, 3, 700));
  assert.deepStrictEqual((await top(e)).json.worlds.island.scores, [row(2880, 700, 1480, 14, 3), row(1531, 600)]);
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
  assert.ok(total < 65000, "writes a day at the ceilings: " + total);
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

// the exact exchanges the Python side replays, for a byte-for-byte comparison
const e = env();
for (const p of [rank("island", 1500), rank("island", 2000), rank("island", 900),
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
