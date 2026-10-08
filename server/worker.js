// Shared leaderboard for Kingdom Hearts Re:Cast (khvcemu), on Cloudflare Workers + D1.
//
// It answers the two requests the 2005 game makes of its (long dead) ranking
// server, which khvcemu forwards here:
//
//   GET /disney/rank.php?uid=&aid=KH&lid=island&s=1500&t=55&u1=1&u2=
//   GET /disney/rankex.php?uid=&aid=KH&lid=island,agrabah&s=1500,700&t=12&u1=1
//
// and replies in the pipe-delimited format the game's parser expects:
//
//   *r|ok|anon~|island~3        field 0 is a tag, 1 a status, 2 the player id,
//                              then one "<level>~<rank>" entry per level
//
// Nothing here identifies anybody. No player id is issued or stored: the game
// needs field 2 to exist, so every client is told it is "anon" and sends that
// back. A row is (level, score, seconds, and the Munny, EXP and level the score was made of)
// and nothing else, so a rank is simply "where this score falls among all scores posted for
// that level".
//
// The only IP-derived value is a salted hash used to rate-limit posts, kept for
// ten minutes and then deleted. See server/README.md.

const WORLDS = ["training", "island", "wonderland", "agrabah", "castle"];
// Score is Munny + 100 x EXP. A full human playthrough in the emulator scored 939 (Island),
// 24,005 (Agrabah) and 51,282 (Castle). The limit is a million on purpose, for now: waves of
// enemies can be farmed for EXP, so honest-looking scores can run far past a normal clear, and
// the first weeks will show where the real top is. Anything above it is rejected, and /top
// ignores it too, so lowering this later also hides old junk (see server/README.md). It stops
// trolling, not careful cheating: scores come from the player's own computer and cannot be
// verified.
export const MAX_SCORE = 1_000_000;
const TOP_N = 100;                                    // rows per world on the public board
const MAX_LEVEL = 99;                                 // the game's own level, read from its Summary screen
const TOP_WORLDS = ["island", "agrabah", "castle"];   // the Obstacle Course has no score, and Wonderland is lost
const MAX_SECONDS = 24 * 60 * 60; // a world taking over a day is not a real run
// The emulator measures how long the world took and sends it as `pt` (seconds); the game's
// own `t` is a running clock and is ignored. A run shorter than the minimum, or without a
// time, is answered normally and not stored, like the other refusals, so the player sees no
// error. Per world: about a quarter of a careful first clear (measured on 2026-10-05: Obstacle
// Course 2:45, Island 26:30, Agrabah 54:00, Castle 42:30), so a fast or practised run still
// counts but a state-skipping or scripted one does not. Wonderland is the Island run sent again.
export const MIN_SECONDS = { training: 60, island: 360, wonderland: 360, agrabah: 600, castle: 480 };
// One score per address every ten minutes. A world takes far longer than that to play, so a
// real player never meets this; it only blunts someone posting scores in a loop. A second
// post inside the window is NOT an error: the game is told the rank the score would have had
// and the score is simply not stored, so nobody can tell it was dropped.
const COOLDOWN = 600;

const OK = (body) => new Response(body, {
  status: 200,
  headers: { "content-type": "text/plain; charset=iso-8859-1", "cache-control": "no-store" },
});

/** The game stores field 2 up to the first "~" and sends it back as uid; it is
 *  the same constant for everyone, because there are no accounts here. */
export function reply(entries) {
  return entries.length ? `*r|ok|anon~|${entries.join("|")}` : "*r|ok|anon~";
}

/** A level name the game could actually have sent. Anything else is junk. */
export function validLevel(lid) {
  return WORLDS.includes(String(lid || "").toLowerCase()) ? String(lid).toLowerCase() : null;
}

export function validScore(s) {
  const n = Number(s);
  return Number.isInteger(n) && n >= 0 && n <= MAX_SCORE ? n : null;
}

/** The measured play time in seconds, or null if it is missing or outside what a real run takes. */
export function validPlayTime(raw, lid) {
  if (raw === null || raw === undefined || raw === "") return null;
  const n = Number(raw);
  return Number.isInteger(n) && n >= (MIN_SECONDS[lid] ?? 0) && n <= MAX_SECONDS ? n : null;
}

/**
 * The Munny, EXP and level behind a score, sent by newer clients as `mn`, `ex` and `lv` (read
 * from the game's Summary screen). The game's score is Munny + 100 x EXP, so numbers that do
 * not add up to the score are not a real run.
 *   null      nothing was sent (an older client): the score is accepted without them
 *   false     they were sent but are wrong: refused like any other bad post
 *   {munny, exp, level}
 */
export function validStats(q, score) {
  const mn = q.get("mn"), ex = q.get("ex"), lv = q.get("lv");
  const sent = (v) => v !== null && v !== undefined && v !== "";
  if (!sent(mn) && !sent(ex)) return null;
  const munny = Number(mn), exp = Number(ex);
  if (!sent(mn) || !sent(ex) || !Number.isInteger(munny) || !Number.isInteger(exp)) return false;
  if (munny < 0 || exp < 0 || munny + 100 * exp !== score) return false;
  let level = null;
  if (sent(lv)) {
    level = Number(lv);
    if (!Number.isInteger(level) || level < 0 || level > MAX_LEVEL) return false;
  }
  return { munny, exp, level };
}

// The columns for those numbers were added later (server/migrate_001_stats.sql). Until the
// database has them the worker carries on without, so deploying it and migrating the
// database can be done in either order. Once seen it is remembered for that database
// (columns never go away); until then it is checked again on each request.
const seenStatsColumns = new WeakSet();
async function hasStatsColumns(db) {
  if (seenStatsColumns.has(db)) return true;
  const info = await db.prepare("PRAGMA table_info(scores)").all();
  const found = (info.results || []).some((c) => c.name === "munny");
  if (found) seenStatsColumns.add(db);
  return found;
}

/** Equal scores are ordered by the faster time. Without a time (the game's Score screen only
 *  knows the score) a tie is not split, so ties share a place, as the local table does. */
async function rankOf(db, lid, score, secs = null) {
  const row = secs === null
    ? await db.prepare("SELECT COUNT(*) AS n FROM scores WHERE lid = ? AND score > ?").bind(lid, score).first()
    : await db.prepare(
        "SELECT COUNT(*) AS n FROM scores WHERE lid = ? AND (score > ? OR (score = ? AND secs IS NOT NULL AND secs < ?))")
        .bind(lid, score, score, secs).first();
  return (row?.n ?? 0) + 1;
}

async function hasScores(db, lid) {
  const row = await db.prepare("SELECT 1 FROM scores WHERE lid = ? LIMIT 1").bind(lid).first();
  return !!row;
}

/** A salted, truncated hash of the address, so posts can be rate-limited without
 *  keeping anything that identifies a visitor. */
async function ipKey(ip, salt) {
  const data = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest).slice(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** True if this address already had a score accepted in the last ten minutes. Only accepted
 *  posts start the clock, so repeating does not extend the wait. */
async function inCooldown(db, ip, salt, now) {
  const key = await ipKey(ip, salt);
  await db.prepare("DELETE FROM recent WHERE seen <= ?").bind(now - COOLDOWN).run();
  const row = await db.prepare("SELECT 1 FROM recent WHERE k = ? LIMIT 1").bind(key).first();
  if (row) return true;
  await db.prepare("INSERT INTO recent (k, seen) VALUES (?, ?)").bind(key, now).run();
  return false;
}

async function handleRank(db, q, ip, salt, now) {
  const lid = validLevel(q.get("lid"));
  const score = validScore(q.get("s"));
  if (!lid || score === null) return OK("*r|invalidentry");
  const secs = validPlayTime(q.get("pt"), lid);
  const stats = validStats(q, score);
  // Every refusal below is answered like a success: the rank the score would have had, and
  // nothing stored, so nobody can tell what was dropped or why.
  const answer = async () => OK(reply([`${lid}~${await rankOf(db, lid, score, secs)}`]));

  if (secs === null) return answer();                        // no time, or too short to be a run
  if (stats === false) return answer();                      // Munny and EXP that do not make the score
  // The same score with the same time is stored once; a different time is a different run.
  const dup = await db.prepare("SELECT 1 FROM scores WHERE lid = ? AND score = ? AND secs = ? LIMIT 1")
    .bind(lid, score, secs).first();
  if (dup) return answer();
  if (await inCooldown(db, ip, salt, now)) return answer();  // one score per address per ten minutes

  const aid = String(q.get("aid") || "KH").slice(0, 8);
  if (await hasStatsColumns(db)) {
    await db.prepare("INSERT INTO scores (posted, aid, lid, score, secs, munny, exp, level) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(now, aid, lid, score, secs, stats?.munny ?? null, stats?.exp ?? null, stats?.level ?? null).run();
  } else {
    await db.prepare("INSERT INTO scores (posted, aid, lid, score, secs) VALUES (?, ?, ?, ?, ?)")
      .bind(now, aid, lid, score, secs).run();
  }
  return answer();
}

/** "Update" on the HIGH SCORES screen: the game sends its own table as parallel
 *  comma-separated lists and wants a rank for each level that has any scores. */
async function handleRankex(db, q) {
  const levels = String(q.get("lid") || "").split(",");
  const scores = String(q.get("s") || "").split(",");
  const entries = [];
  for (let i = 0; i < levels.length && i < scores.length; i++) {
    const lid = validLevel(levels[i]);
    const score = validScore(scores[i]);
    if (lid && score !== null && await hasScores(db, lid)) {
      entries.push(`${lid}~${await rankOf(db, lid, score)}`);
    }
  }
  return OK(reply(entries));
}

/** The public board: the best scores per world (up to 100, or `?n=`) with their play times and
 *  the Munny, EXP and level they were made of (null for scores from older clients), and how
 *  many were posted. No address, nothing that says who. Cached for a minute so a busy page
 *  costs nothing. */
async function handleTop(db, now, q = new URLSearchParams()) {
  const asked = Number(q.get("n"));
  const limit = Number.isInteger(asked) && asked >= 1 ? Math.min(asked, TOP_N) : TOP_N;
  const stats = await hasStatsColumns(db);
  const columns = stats ? "score, secs, munny, exp, level" : "score, secs";
  const worlds = {};
  for (const lid of TOP_WORLDS) {
    const rows = await db.prepare(
      `SELECT ${columns} FROM scores WHERE lid = ? AND score <= ? ORDER BY score DESC, secs IS NULL, secs ASC LIMIT ?`)
      .bind(lid, MAX_SCORE, limit).all();
    const count = await db.prepare("SELECT COUNT(*) AS n FROM scores WHERE lid = ? AND score <= ?")
      .bind(lid, MAX_SCORE).first();
    worlds[lid] = {
      scores: (rows.results || []).map((r) => ({
        score: r.score, secs: r.secs ?? null, munny: r.munny ?? null, exp: r.exp ?? null, level: r.level ?? null,
      })),
      total: count?.n ?? 0,
    };
  }
  return new Response(JSON.stringify({ updated: now, max: MAX_SCORE, minSeconds: MIN_SECONDS, worlds }), {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "cache-control": "public, max-age=60",
    },
  });
}

// Anonymous website counters. The page (site/index.html, leaderboard.html) asks `GET /hit?e=<name>` when
// it is opened, when a section is scrolled to, or a button is clicked; the worker adds one to today's
// count for that name. Only the names below count (anything else is ignored), so nobody can fill the
// table. Nothing about the visitor is stored: no address, no cookie, no browser string. A browser that
// sends Do Not Track never asks. Read the totals with tools/site_stats.py (or its dashboard button).
//
// For each opening of the main page the worker also adds one to a few SEPARATE tallies (kept apart and never
// stored per visit, though on a very quiet day, a visit or two, the counts could still be matched up by eye): the hour of day, the country (Cloudflare's coarse location
// of the connection; the address itself is neither read nor kept), the kind of computer the page says it
// is (a short fixed list) and where the visitor came from (a short fixed list of sites, domain only).
// Each name has a daily ceiling. They bound the database writes the counters can cause (about 57,000 a
// day at most, against the free plan's daily allowance, which the scores share), so someone calling the
// address in a loop cannot use them up and stop scores being saved: past a ceiling a call changes nothing.
export const SITE_EVENTS = {
  "view:home": 8000, "view:leaderboard": 1500,
  "dl:win64": 600, "dl:win32": 600, "dl:macArm": 600, "dl:macIntel": 600, "dl:linux64": 600, "dl:linuxArm": 600,
  "dl:sums": 600, "click:repo": 600, "click:issues": 600, "click:soundtrack": 600, "click:email": 600,
  "sec:about": 1000, "sec:features": 1000, "sec:screens": 1000, "sec:launcher": 1000, "sec:composer": 1000,
  "sec:download": 1000, "sec:help": 1000, "sec:wonderland": 1000, "sec:credits": 1000,
};
export const SITE_OS = new Set(["windows", "mac", "linux", "android", "ios", "chromeos", "other"]);
export const SITE_REFS = new Set(["direct", "reddit", "google", "bing", "duckduckgo", "youtube", "x", "bluesky", "facebook",
  "discord", "khinsider", "kh13", "khwiki", "lostmedia", "archive", "github", "hackernews", "other"]);
const SITE_HOSTS = new Set(["khrecast.com", "www.khrecast.com"]);
const COUNT_UP = "INSERT INTO site_stats (day, name, n) VALUES (?, ?, 1) ON CONFLICT (day, name) DO UPDATE SET n = n + 1";

export async function handleHit(db, params, request, now) {
  const done = new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
  const name = params.get("e") || "";
  // a count only for the real thing: a GET (not a HEAD probe), a known name, and, when the browser says
  // which page it came from, one of ours
  if (request.method !== "GET" || !Object.hasOwn(SITE_EVENTS, name)) return done;
  const from = request.headers.get("referer");
  if (from) {
    try { if (!SITE_HOSTS.has(new URL(from).hostname)) return done; } catch { return done; }
  }
  try {
    const when = new Date(now * 1000);
    const day = when.toISOString().slice(0, 10);
    const r = await db.prepare(COUNT_UP + " WHERE n < ?").bind(day, name, SITE_EVENTS[name]).run();
    const changed = r?.meta?.changes ?? r?.changes ?? 0;       // 0: at its ceiling for today (and if the database says nothing, assume so: never skip the limit)
    if (name === "view:home" && changed) {
      const extra = [`hour:${String(when.getUTCHours()).padStart(2, "0")}`];
      const country = String(request.cf?.country || "").toUpperCase();
      if (/^[A-Z0-9]{2}$/.test(country)) extra.push(`country:${country}`);
      const os = params.get("o") || "";
      if (SITE_OS.has(os)) extra.push(`os:${os}`);
      const ref = params.get("r") || "";
      if (SITE_REFS.has(ref)) extra.push(`ref:${ref}`);
      for (const n of extra) await db.prepare(COUNT_UP).bind(day, n).run();   // bounded by the main name's ceiling
    }
  } catch (err) {
    console.error("site stats error:", err && err.message);   // e.g. the table is not there yet: never hurt the page
  }
  return done;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const script = url.pathname.split("/").pop().toLowerCase();
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405 });
    }
    const now = Math.floor(Date.now() / 1000);
    const ip = request.headers.get("cf-connecting-ip") || "0.0.0.0";
    const salt = env.IP_SALT || "khvcemu";
    try {
      if (script === "rank.php") return await handleRank(env.DB, url.searchParams, ip, salt, now);
      if (script === "rankex.php") return await handleRankex(env.DB, url.searchParams);
      if (script === "top") return await handleTop(env.DB, now, url.searchParams);
      if (script === "hit") return await handleHit(env.DB, url.searchParams, request, now);
    } catch (err) {
      console.error("leaderboard error:", err && err.message);   // shows in `wrangler tail`; nothing identifying
      // never hand the game a 500 it cannot parse: khvcemu falls back to its
      // own offline table when the reply is not a usable one
      return new Response("server error", { status: 503 });
    }
    return new Response("khvcemu leaderboard: /disney/rank.php, /disney/rankex.php, /top and /hit\n",
                        { status: 404, headers: { "content-type": "text/plain" } });
  },
};
