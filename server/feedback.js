// The public feedback board on khrecast.com ("Jiminy's Journal"), served by the leaderboard worker.
//
//   POST /feedback               a new post, from the website's form (x-www-form-urlencoded)
//   GET  /feedback?before=&n=    the public posts, newest first, with the owner's replies
//   GET  /feedback/admin         the owner's page (asks for the key; holds no data itself)
//   POST /feedback/admin/list    every post, hidden ones and email addresses included   (x-feedback-key)
//   POST /feedback/admin/act     hide, show, fix, unfix, reply, delete one post          (x-feedback-key)
//
// A post shows at once. What keeps junk out: posts only from the website (its Origin), a hidden field
// that people never fill in, a form sent too fast to have been typed, at most a few links, a few posts
// an hour per address (the same salted, shortened hash as scores, kept an hour), a daily ceiling, and,
// if TURNSTILE_SECRET is set, Cloudflare's Turnstile check. The owner can hide or delete any post.
//
// Each post is emailed to the owner when the MAIL binding exists (Cloudflare Email Routing, see
// wrangler.toml). The poster's email, if they gave one, is the Reply-To of that email, so answering it
// in the inbox answers them; it is stored only for that, never shown and never sent anywhere else.
// The admin key is the worker secret FEEDBACK_KEY (wrangler secret put FEEDBACK_KEY).

export const KINDS = {
  review: "Review", idea: "Idea", bug: "Bug report", complaint: "Complaint", rant: "Rant",
  wonderland: "Wonderland info", other: "Other",
};
export const DEVICES = { windows: "Windows", mac: "Mac", linux: "Linux", android: "Android", other: "Other" };
export const SITE_ORIGINS = new Set(["https://khrecast.com", "https://www.khrecast.com"]);
export const LIMITS = {
  nick: 40, version: 20, email: 120, messageMin: 10, messageMax: 3000, links: 3, body: 20000,
  perHour: 3,           // posts per address an hour
  perDay: 200,          // posts a day, everyone together
  minFillMs: 4000,      // a form sent sooner than this after it was shown was not typed by a person
  page: 20, pageMax: 50, adminList: 500,
};

const json = (data, status = 200, extra = {}) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
});

/** Text a person typed, without control characters (newlines and tabs kept), trimmed and cut to `max`. */
export function cleanText(raw, max, keepLines = false) {
  let s = String(raw ?? "").replace(/\r\n?/g, "\n");
  s = keepLines ? s.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "") : s.replace(/[\u0000-\u001f\u007f]/g, " ");
  s = s.trim();
  return s.length > max ? s.slice(0, max) : s;
}

const EMAIL_RE = /^[^\s@<>()",;:\\[\]]+@[^\s@<>()",;:\\[\]]+\.[^\s@<>()",;:\\[\]]{2,}$/;
const LINK_RE = /https?:\/\/|www\./gi;

/**
 * The post a form carries, or {error} with a message for the poster, or {silent: true} for a robot
 * (answered as if it worked, so it learns nothing).
 */
export function validPost(form, nowMs) {
  if (cleanText(form.get("website"), 200)) return { silent: true };                 // the hidden field
  // how long the form was open, both ends from the visitor's own clock (`t` when it was shown, `s` when it was sent),
  // so a clock that is set wrong does not matter
  const shown = Number(form.get("t")), sent = Number(form.get("s"));
  const open = sent - shown;
  if (!(shown > 0) || !Number.isFinite(open) || open < LIMITS.minFillMs) return { silent: true };   // no clock, or too fast for a person
  if (open > 2 * 86400 * 1000) return { error: "This page has been open a long time. Copy your text, reload the page and send it again." };
  const kind = String(form.get("kind") || "");
  if (!Object.hasOwn(KINDS, kind)) return { error: "Pick what kind of entry this is." };
  const message = cleanText(form.get("message"), LIMITS.messageMax + 1, true);
  if (message.length < LIMITS.messageMin) return { error: "Write a little more (at least 10 characters)." };
  if (message.length > LIMITS.messageMax) return { error: `That is too long: ${LIMITS.messageMax} characters at most.` };
  if ((message.match(LINK_RE) || []).length > LIMITS.links) return { error: `At most ${LIMITS.links} links, please.` };
  const nick = cleanText(form.get("nick"), LIMITS.nick) || null;
  const deviceRaw = String(form.get("device") || "");
  const device = Object.hasOwn(DEVICES, deviceRaw) ? deviceRaw : null;
  const versionRaw = cleanText(form.get("version"), LIMITS.version);
  const version = /^[\w.\- ]+$/.test(versionRaw) ? versionRaw : null;
  const emailRaw = cleanText(form.get("email"), LIMITS.email + 1);
  if (emailRaw && (emailRaw.length > LIMITS.email || !EMAIL_RE.test(emailRaw))) return { error: "That email address doesn't look right." };
  return { post: { kind, message, nick, device, version, email: emailRaw || null } };
}

async function addressKey(ip, salt) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${salt}:fb:${ip}`));
  return [...new Uint8Array(digest).slice(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function turnstileOk(env, form, ip) {
  if (!env.TURNSTILE_SECRET) return true;
  const body = new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: String(form.get("cf-turnstile-response") || ""), remoteip: ip });
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body });
    return !!(await r.json()).success;
  } catch {
    return false;
  }
}

function publicRow(r) {
  return {
    id: r.id, posted: r.posted, kind: r.kind, nick: r.nick ?? null, device: r.device ?? null, version: r.version ?? null,
    message: r.message, fixed: !!r.fixed, reply: r.reply ?? null, replied: r.replied ?? null,
  };
}

// ------------------------------------------------------------------ email to the owner
function b64utf8(s) {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}
const header = (s) => (/^[\x20-\x7e]*$/.test(s) ? s : `=?UTF-8?B?${b64utf8(s)}?=`);

/** The raw email (RFC 5322) that tells the owner about post `id`. */
export function ownerEmail(post, id, now, from, to) {
  const who = post.nick || "A player";
  const where = [post.device ? DEVICES[post.device] : null, post.version].filter(Boolean).join(" ");
  const subject = cleanText(`[Re:Cast] ${post.kind === "wonderland" ? "WONDERLAND INFO" : KINDS[post.kind]} from ${who}`, 150);
  const text = [
    `New entry in the Re:Cast journal (#${id}): ${KINDS[post.kind]}`,
    `From: ${who}${where ? `, on ${where}` : ""}`,
    post.email ? `Email: ${post.email} (replying to this email answers them directly)` : "No email left: reply on the admin page so it shows under the post.",
    "",
    post.message,
    "",
    `On the site: https://khrecast.com/journal#feedback-${id}`,
    `Reply in public, hide, delete or mark fixed: https://scores.khrecast.com/feedback/admin#${id}`,
  ].join("\r\n");
  const lines = [
    `From: "Re:Cast journal" <${from}>`,
    `To: <${to}>`,
    ...(post.email ? [`Reply-To: <${post.email}>`] : []),
    `Subject: ${header(subject)}`,
    `Date: ${new Date(now * 1000).toUTCString()}`,
    `Message-ID: <feedback-${id}-${now}@khrecast.com>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: base64",
    "",
    b64utf8(text).replace(/.{76}/g, "$&\r\n"),
  ];
  return lines.join("\r\n");
}

async function notifyOwner(env, post, id, now) {
  if (!env.MAIL) return;
  try {
    const from = env.FEEDBACK_FROM || "feedback@khrecast.com";
    const to = env.FEEDBACK_TO || "khrecast@gmail.com";
    const { EmailMessage } = await import("cloudflare:email");
    await env.MAIL.send(new EmailMessage(from, to, ownerEmail(post, id, now, from, to)));
  } catch (err) {
    console.error("feedback email error:", err && err.message);   // the post is stored either way
  }
}

// ------------------------------------------------------------------ public
async function newPost(request, env, ctx, now, ip, salt) {
  const origin = request.headers.get("origin") || "";
  if (!SITE_ORIGINS.has(origin)) return json({ ok: false, error: "Post from khrecast.com." }, 403);
  const cors = { "access-control-allow-origin": origin, vary: "Origin" };
  const raw = await request.text();
  if (raw.length > LIMITS.body) return json({ ok: false, error: "That is too long." }, 413, cors);
  const form = new URLSearchParams(raw);
  const v = validPost(form, now * 1000);
  if (v.silent) return json({ ok: true, id: null }, 200, cors);
  if (v.error) return json({ ok: false, error: v.error }, 400, cors);
  if (!(await turnstileOk(env, form, ip))) return json({ ok: false, error: "The check that you're a person didn't pass. Try again." }, 400, cors);
  const db = env.DB;
  try {
    const key = await addressKey(ip, salt);
    await db.prepare("DELETE FROM feedback_recent WHERE seen <= ?").bind(now - 3600).run();
    const mine = await db.prepare("SELECT COUNT(*) AS n FROM feedback_recent WHERE k = ?").bind(key).first();
    if ((mine?.n ?? 0) >= LIMITS.perHour) return json({ ok: false, error: "That's a lot of entries for one hour. Try again a bit later." }, 429, cors);
    const today = await db.prepare("SELECT COUNT(*) AS n FROM feedback WHERE posted > ?").bind(now - 86400).first();
    if ((today?.n ?? 0) >= LIMITS.perDay) return json({ ok: false, error: "The journal is full for today. Try again tomorrow." }, 429, cors);
    const p = v.post;
    const r = await db.prepare("INSERT INTO feedback (posted, kind, nick, device, version, message, email) VALUES (?, ?, ?, ?, ?, ?, ?)")
      .bind(now, p.kind, p.nick, p.device, p.version, p.message, p.email).run();
    const id = Number(r?.meta?.last_row_id ?? r?.lastInsertRowid);
    await db.prepare("INSERT INTO feedback_recent (k, seen) VALUES (?, ?)").bind(key, now).run();
    const mail = notifyOwner(env, p, id, now);
    if (ctx && ctx.waitUntil) ctx.waitUntil(mail); else await mail;
    return json({ ok: true, id }, 200, cors);
  } catch (err) {
    console.error("feedback error:", err && err.message);           // e.g. the tables are not there yet
    return json({ ok: false, error: "The journal can't take entries right now. Please try again later." }, 503, cors);
  }
}

async function listPosts(db, q) {
  const asked = Number(q.get("n"));
  const n = Number.isInteger(asked) && asked >= 1 ? Math.min(asked, LIMITS.pageMax) : LIMITS.page;
  const before = Number(q.get("before"));
  const rows = Number.isInteger(before) && before > 0
    ? await db.prepare("SELECT * FROM feedback WHERE hidden = 0 AND id < ? ORDER BY id DESC LIMIT ?").bind(before, n + 1).all()
    : await db.prepare("SELECT * FROM feedback WHERE hidden = 0 ORDER BY id DESC LIMIT ?").bind(n + 1).all();
  const list = rows.results || [];
  const counts = await db.prepare("SELECT COUNT(*) AS total, SUM(fixed) AS squashed FROM feedback WHERE hidden = 0").first();
  return json({ posts: list.slice(0, n).map(publicRow), more: list.length > n, total: counts?.total ?? 0, squashed: counts?.squashed ?? 0 },
    200, { "access-control-allow-origin": "*", "cache-control": "public, max-age=15" });
}

// ------------------------------------------------------------------ the owner
function sameText(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function adminAllowed(request, env) {
  if (!env.FEEDBACK_KEY) return json({ ok: false, error: "Set the FEEDBACK_KEY secret first." }, 503);
  if (!sameText(request.headers.get("x-feedback-key") || "", env.FEEDBACK_KEY)) return json({ ok: false, error: "Wrong key." }, 403);
  return null;
}

async function adminList(db) {
  const rows = await db.prepare("SELECT * FROM feedback ORDER BY id DESC LIMIT ?").bind(LIMITS.adminList).all();
  return json({ posts: (rows.results || []).map((r) => ({ ...publicRow(r), email: r.email ?? null, hidden: !!r.hidden })) });
}

async function adminAct(db, form, now) {
  const id = Number(form.get("id"));
  const action = String(form.get("action") || "");
  if (!Number.isInteger(id) || id < 1) return json({ ok: false, error: "No such post." }, 400);
  const run = (sql, ...args) => db.prepare(sql).bind(...args, id).run();
  if (action === "hide") await run("UPDATE feedback SET hidden = 1 WHERE id = ?");
  else if (action === "show") await run("UPDATE feedback SET hidden = 0 WHERE id = ?");
  else if (action === "fix") await run("UPDATE feedback SET fixed = 1 WHERE id = ?");
  else if (action === "unfix") await run("UPDATE feedback SET fixed = 0 WHERE id = ?");
  else if (action === "delete") await run("DELETE FROM feedback WHERE id = ?");
  else if (action === "reply") {
    const text = cleanText(form.get("text"), LIMITS.messageMax, true);
    await run("UPDATE feedback SET reply = ?, replied = ? WHERE id = ?", text || null, text ? now : null);
  } else return json({ ok: false, error: "Unknown action." }, 400);
  return json({ ok: true });
}

export async function handleFeedback(request, env, ctx, now, ip, salt) {
  const path = new URL(request.url).pathname.replace(/\/+$/, "").toLowerCase();
  if (path === "/feedback") {
    if (request.method === "POST") return newPost(request, env, ctx, now, ip, salt);
    if (request.method === "GET" || request.method === "HEAD") {
      try { return await listPosts(env.DB, new URL(request.url).searchParams); }
      catch { return json({ posts: [], more: false, total: 0, squashed: 0 }, 200, { "access-control-allow-origin": "*" }); }
    }
  }
  if (path === "/feedback/admin" && (request.method === "GET" || request.method === "HEAD")) {
    return new Response(ADMIN_PAGE, { headers: {
      "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-frame-options": "DENY",
      "x-robots-tag": "noindex", "referrer-policy": "no-referrer",
      "content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
        + "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    } });
  }
  if ((path === "/feedback/admin/list" || path === "/feedback/admin/act") && request.method === "POST") {
    const refused = adminAllowed(request, env);
    if (refused) return refused;
    if (path.endsWith("/list")) return adminList(env.DB);
    return adminAct(env.DB, new URLSearchParams(await request.text()), now);
  }
  return null;
}

// The owner's page. It holds no data: it asks for the key, keeps it in this tab only, and fetches.
const ADMIN_PAGE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Re:Cast journal admin</title>
<style>
:root { color-scheme: dark; --bg:#0b1626; --panel:#13253c; --line:#1d3a5c; --text:#e9f0fa; --muted:#8ea4bf; --blue:#2f80ed; --amber:#f2c94c; --red:#e5645b; --green:#58c46b; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 "Segoe UI", system-ui, sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 20px 16px 60px; }
h1 { font-size: 22px; margin: 0 0 12px; }
.bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom: 14px; }
input, textarea, select { background:#0f1d31; color:var(--text); border:1px solid var(--line); border-radius:8px; padding:8px 10px; font:inherit; }
textarea { width:100%; min-height: 80px; }
button, a.btn { background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:6px 12px; font:inherit; cursor:pointer; text-decoration:none; display:inline-block; }
button:hover, a.btn:hover { border-color: var(--blue); }
.post { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin: 12px 0; }
.post.hidden { opacity:.55; border-style:dashed; }
.post:target { border-color: var(--amber); }
.meta { color:var(--muted); font-size: 13px; }
.msg { white-space: pre-wrap; overflow-wrap:anywhere; margin: 8px 0; }
.tag { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background:#2f80ed33; color:#9cc4ff; margin-right: 6px; }
.tag.fixed { background:#58c46b33; color:var(--green); } .tag.hid { background:#e5645b33; color:var(--red); }
.acts { display:flex; gap:6px; flex-wrap:wrap; margin-top: 8px; }
#status { color: var(--amber); }
</style></head><body><main>
<h1>Re:Cast journal: admin</h1>
<div class="bar"><input id="key" type="password" placeholder="Admin key" autocomplete="current-password" size="30">
<button id="load">Show posts</button><select id="filter"><option value="all">All</option><option value="open">No reply yet</option><option value="hidden">Hidden</option><option value="bug">Bug reports</option><option value="wonderland">Wonderland info</option></select>
<span id="status"></span></div>
<div id="list"></div>
<script>
const KINDS = ${JSON.stringify(KINDS)};
const DEVICES = ${JSON.stringify(DEVICES)};
const $ = (id) => document.getElementById(id);
let posts = [];
try { $("key").value = sessionStorage.getItem("fbkey") || ""; } catch (e) {}
function key() { return $("key").value.trim(); }
async function call(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "x-feedback-key": key(), "content-type": "application/x-www-form-urlencoded" }, body: body ? new URLSearchParams(body) : "" });
  const data = await r.json().catch(() => ({ ok: false, error: "Bad answer from the server." }));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function when(s) { return new Date(s * 1000).toLocaleString(); }
function render() {
  const f = $("filter").value, list = $("list");
  list.textContent = "";
  for (const p of posts) {
    if (f === "open" && (p.reply || p.hidden)) continue;
    if (f === "hidden" && !p.hidden) continue;
    if ((f === "bug" || f === "wonderland") && p.kind !== f) continue;
    const box = el("div", "post" + (p.hidden ? " hidden" : "")); box.id = String(p.id);
    const meta = el("div", "meta");
    meta.append(el("span", "tag", KINDS[p.kind] || p.kind));
    if (p.fixed) meta.append(el("span", "tag fixed", "Squashed"));
    if (p.hidden) meta.append(el("span", "tag hid", "Hidden"));
    meta.append("#" + p.id + " · " + (p.nick || "A player") + (p.device ? " · " + (DEVICES[p.device] || p.device) : "") + (p.version ? " " + p.version : "") + " · " + when(p.posted));
    if (p.email) meta.append(" · " + p.email);
    box.append(meta, el("div", "msg", p.message));
    const reply = el("textarea"); reply.value = p.reply || ""; reply.placeholder = "Public reply (shows under the post on the site)";
    box.append(reply);
    const acts = el("div", "acts");
    const btn = (label, fn) => { const b = el("button", null, label); b.onclick = fn; acts.append(b); return b; };
    const act = (action, extra) => async () => {
      try { await call("/feedback/admin/act", { id: p.id, action, ...(extra || {}) }); $("status").textContent = "Saved."; await load(); }
      catch (e) { $("status").textContent = e.message; }
    };
    btn("Save reply", () => act("reply", { text: reply.value })());
    if (p.email) {
      const a = el("a", "btn", "Email this reply");
      a.onclick = () => { a.href = "mailto:" + encodeURIComponent(p.email) + "?subject=" + encodeURIComponent("Re: your Re:Cast " + (KINDS[p.kind] || "entry").toLowerCase())
        + "&body=" + encodeURIComponent(reply.value + "\\n\\n> " + p.message.split("\\n").join("\\n> ")); };
      acts.append(a);
    }
    btn(p.fixed ? "Not fixed" : "Mark fixed", act(p.fixed ? "unfix" : "fix"));
    btn(p.hidden ? "Show" : "Hide", act(p.hidden ? "show" : "hide"));
    btn("Delete", () => { if (confirm("Delete post #" + p.id + " for good?")) act("delete")(); });
    box.append(acts);
    list.append(box);
  }
  if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
}
async function load() {
  try { sessionStorage.setItem("fbkey", key()); } catch (e) {}
  try { posts = (await call("/feedback/admin/list")).posts; $("status").textContent = posts.length + " posts"; render(); }
  catch (e) { $("status").textContent = e.message; }
}
$("load").onclick = load;
$("filter").onchange = render;
if (key()) load();
</script></main></body></html>`;
