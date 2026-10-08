// A temporary password gate in front of the Re:Cast website.
//
// Every request reaches this Worker first (wrangler.toml: run_worker_first). Without a valid
// cookie a visitor only gets the splash page below; the real pages and pictures are not sent.
// A correct password sets a signed cookie (30 days) and the site is served from the static
// assets as usual.
//
// The password is the Worker secret SITE_PASSWORD, never in the repository. Set it BEFORE (or
// right after) the first deploy; while wrangler.toml says GATE = "on" and the secret is missing,
// the Worker answers 503 to everybody, so a forgotten secret can never open the site:
//
//   cd site-deploy && npx --prefix ../server wrangler secret put SITE_PASSWORD --config wrangler.toml
//
// To open the site to everyone again: in wrangler.toml remove `main`, `binding` and
// `run_worker_first` (and the [vars] block), then deploy. That serves the static files directly.
// (Deleting the secret would NOT open it: it closes it, see above.)
//
// Needs Node 22.7+ to run test.js (ES modules without a package.json).
//
// The splash page is the only thing that is public, together with the two small logo pictures
// it shows. It asks search engines not to index it.

const COOKIE = "recast_gate";
const DAYS = 30;
const PUBLIC_FILES = new Set(["/assets/recast_icon.png", "/assets/recast_logo_lowres_hardpixels.png"]);

const enc = new TextEncoder();

async function hmac(secret, text) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(text));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Constant-time string comparison, so the password and the cookie cannot be guessed by timing. */
export function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const x = enc.encode(a), y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

/** "<expiry unix seconds>.<signature>"; the signature depends on the password, so changing the
 *  password signs everybody out. */
export async function makeToken(password, now = Math.floor(Date.now() / 1000)) {
  const exp = String(now + DAYS * 86400);
  return `${exp}.${await hmac(password, "gate:" + exp)}`;
}

export async function validToken(password, token, now = Math.floor(Date.now() / 1000)) {
  const [exp, sig] = String(token || "").split(".");
  if (!/^\d+$/.test(exp || "") || Number(exp) < now) return false;
  return same(sig || "", await hmac(password, "gate:" + exp));
}

function cookieValue(request) {
  const m = (request.headers.get("cookie") || "").match(new RegExp(`(?:^|;\\s*)${COOKIE}=([^;]+)`));
  return m ? m[1] : "";
}

export function splash(wrong = false) {
  const body = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Kingdom Hearts Re:Cast</title>
<link rel="icon" type="image/png" href="/assets/recast_icon.png">
<style>
  :root { color-scheme: dark; }
  :root:not([data-theme="light"]) { --bg: #0b1626; --panel: #13253c; --line: #1d3a5c; --text: #e9f0fa; --muted: #8ea4bf; --blue: #2f80ed; --warn: #f2c94c; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: radial-gradient(900px 500px at 50% 0%, #10304f 0%, var(--bg) 70%); color: var(--text); font: 16px/1.5 system-ui, "Segoe UI", sans-serif; }
  main { width: 100%; max-width: 440px; text-align: center; }
  img.logo { width: min(100%, 360px); height: auto; image-rendering: pixelated; }
  h1 { font-size: 22px; margin: 18px 0 6px; }
  p { color: var(--muted); margin: 6px 0; }
  form { margin: 22px 0 8px; display: flex; gap: 8px; }
  input { flex: 1; min-width: 0; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--line); background: var(--panel); color: var(--text); font: inherit; }
  input:focus-visible, button:focus-visible { outline: 3px solid #58c46b; outline-offset: 2px; }
  button { padding: 12px 20px; border-radius: 10px; border: 0; background: var(--blue); color: #fff; font: inherit; font-weight: 700; cursor: pointer; }
  button:hover { background: #4693ff; }
  .err { color: #ff8a8a; min-height: 1.4em; }
  .search { margin-top: 22px; padding: 12px 14px; border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 8px; background: var(--panel); font-size: 14px; text-align: left; }
  .search strong { color: var(--text); }
  .search a { color: #7db6ff; }
  .note { margin-top: 14px; padding: 12px 14px; border: 1px solid var(--line); border-left: 4px solid var(--warn); border-radius: 8px; background: var(--panel); font-size: 13px; text-align: left; }
</style></head><body><main>
<img class="logo" src="/assets/recast_logo_lowres_hardpixels.png" alt="Kingdom Hearts Re:Cast">
<h1>Coming soon</h1>
<p>The Re:Cast website is not open to the public yet.</p>
<form method="post" action="/" autocomplete="off">
  <input type="password" name="password" placeholder="Password" aria-label="Password" required autofocus>
  <button type="submit">Enter</button>
</form>
<p class="err" role="alert">${wrong ? "That is not the password." : ""}</p>
<p class="search"><strong>Looking for the lost Wonderland chapter.</strong> Re:Cast plays the 2005 Verizon V CAST Kingdom Hearts game, but its second chapter, Alice in Wonderland, has never been recovered. If you still have a Verizon phone from that era with the game on it, please don't reset it, and email <a href="mailto:khrecast@gmail.com">khrecast@gmail.com</a>.</p>
<p class="note">Unofficial, non-profit fan preservation project. Not affiliated with Disney, Square Enix, Superscape, Verizon or any other rights holder.</p>
</main></body></html>`;
  return new Response(body, {
    status: wrong ? 401 : 200,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex, nofollow" },
  });
}

export default {
  async fetch(request, env) {
    const password = env.SITE_PASSWORD;
    if (!password) {
      if (env.GATE === "on") return new Response("Not open yet", { status: 503, headers: { "cache-control": "no-store" } });
      return env.ASSETS.fetch(request);                              // the gate was not asked for
    }
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/") {
      let given = "";
      try { given = String((await request.formData()).get("password") || ""); } catch { /* not a form */ }
      if (!same(given, password)) {
        await new Promise((r) => setTimeout(r, 800));                // slows guessing down a little
        return splash(true);
      }
      const token = await makeToken(password);
      return new Response(null, {
        status: 303,
        headers: {
          location: "/",
          "set-cookie": `${COOKIE}=${token}; Max-Age=${DAYS * 86400}; Path=/; HttpOnly; Secure; SameSite=Lax`,
          "cache-control": "no-store",
        },
      });
    }

    if (await validToken(password, cookieValue(request))) {
      const res = await env.ASSETS.fetch(request);
      const out = new Response(res.body, res);
      out.headers.set("x-robots-tag", "noindex, nofollow");           // private for now, also once let in
      out.headers.set("cache-control", "private, no-cache");          // no shared cache may hand it to somebody else
      return out;
    }
    if (request.method === "GET" && PUBLIC_FILES.has(url.pathname)) return env.ASSETS.fetch(request);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname.endsWith(".html") || !url.pathname.includes("."))) {
      return splash(false);                                          // any page address shows the splash
    }
    return new Response("Not open yet", { status: 401, headers: { "cache-control": "no-store", "x-robots-tag": "noindex" } });
  },
};
