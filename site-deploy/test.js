// node site-deploy/test.js : the password gate, with a stand-in for the static assets.
import assert from "node:assert";
import gate, { makeToken, same, validToken } from "./gate.js";

const assets = { fetch: async (req) => new Response("REAL SITE " + new URL(req.url).pathname, { status: 200 }) };
const env = { SITE_PASSWORD: "pw-for-tests", ASSETS: assets };
const get = (path, cookie, e = env) => gate.fetch(new Request("https://khrecast.com" + path, { headers: cookie ? { cookie } : {} }), e);
const post = (password, e = env) => gate.fetch(new Request("https://khrecast.com/", {
  method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "password=" + encodeURIComponent(password) }), e);

let failures = 0;
async function check(name, fn) {
  try { await fn(); console.log("  ok   " + name); } catch (err) { failures++; console.log("  FAIL " + name + "\n       " + err.message); }
}

console.log("gate:");
await check("a visitor without the cookie only gets the splash page", async () => {
  for (const path of ["/", "/index.html", "/leaderboard", "/leaderboard.html", "/anything/else"]) {
    const r = await get(path);
    const body = await r.text();
    assert.strictEqual(r.status, 200, path);
    assert.ok(body.includes("Coming soon") && !body.includes("REAL SITE"), path);
    assert.match(r.headers.get("x-robots-tag"), /noindex/);
  }
  const asset = await get("/assets/boot_sequence.png");
  assert.strictEqual(asset.status, 401, "other files are not served");
  assert.ok(!(await asset.text()).includes("REAL SITE"));
});

await check("the splash page asks for the lost Wonderland chapter and gives a way to reply", async () => {
  const body = await (await get("/")).text();
  assert.ok(body.includes("lost Wonderland chapter") && body.includes("mailto:khrecast@gmail.com"));
  assert.ok(!body.includes("REAL SITE"));
});

await check("only the two splash-page logos are public", async () => {
  assert.ok((await (await get("/assets/recast_icon.png")).text()).includes("REAL SITE"));
  assert.ok((await (await get("/assets/recast_logo_lowres_hardpixels.png")).text()).includes("REAL SITE"));
});

await check("a wrong password shows the splash page again, with a message", async () => {
  const r = await post("nope");
  assert.strictEqual(r.status, 401);
  assert.ok((await r.text()).includes("not the password"));
  assert.ok(!r.headers.get("set-cookie"));
});

await check("the right password sets a cookie that lets the site through", async () => {
  const r = await post("pw-for-tests");
  assert.strictEqual(r.status, 303);
  const cookie = r.headers.get("set-cookie");
  assert.match(cookie, /recast_gate=\d+\.[0-9a-f]{64}/);
  assert.match(cookie, /HttpOnly/);
  assert.match(cookie, /Secure/);
  const pair = cookie.split(";")[0];
  const page = await get("/leaderboard.html", pair);
  assert.ok((await page.text()).includes("REAL SITE /leaderboard.html"));
  assert.match(page.headers.get("x-robots-tag"), /noindex/, "still not indexed once let in");
});

await check("forged, expired and other-password cookies are refused", async () => {
  const now = Math.floor(Date.now() / 1000);
  const good = await makeToken("pw-for-tests", now);
  assert.ok(await validToken("pw-for-tests", good, now));
  assert.ok(!(await validToken("pw-for-tests", good, now + 31 * 86400)), "after 30 days");
  assert.ok(!(await validToken("another-password", good, now)), "a changed password signs everyone out");
  assert.ok(!(await validToken("pw-for-tests", "9999999999." + "0".repeat(64), now)), "forged");
  assert.ok(!(await validToken("pw-for-tests", "garbage", now)));
  assert.ok(!(await validToken("pw-for-tests", "", now)));
  assert.ok((await (await get("/", "recast_gate=garbage")).text()).includes("Coming soon"));
});

await check("with GATE on and no password secret the site is closed, never open", async () => {
  const r = await get("/index.html", "", { ASSETS: assets, GATE: "on" });
  assert.strictEqual(r.status, 503);
  assert.ok(!(await r.text()).includes("REAL SITE"));
  const ok = await get("/index.html", "", { ASSETS: assets });
  assert.ok((await ok.text()).includes("REAL SITE"), "the gate is only on when asked for");
});

await check("odd requests never reach the site", async () => {
  for (const path of ["/index.html%2e", "//index.html", "/%2e%2e/index.html", "/?x=/assets/recast_icon.png", "/robots.txt", "/favicon.ico", "/assets/recast_icon.png/..%2findex.html"]) {
    const body = await (await get(path)).text();
    assert.ok(!body.includes("REAL SITE"), path);
  }
  for (const method of ["HEAD", "OPTIONS", "PUT", "DELETE"]) {
    const r = await gate.fetch(new Request("https://khrecast.com/index.html", { method }), env);
    assert.ok(!(await r.text()).includes("REAL SITE"), method);
  }
  const wrongPost = await gate.fetch(new Request("https://khrecast.com/other", { method: "POST", body: "password=pw-for-tests" }), env);
  assert.strictEqual(wrongPost.status, 401, "a password posted anywhere but / is ignored");
  const empty = await gate.fetch(new Request("https://khrecast.com/", { method: "POST" }), env);
  assert.strictEqual(empty.status, 401, "a post with no form is just a wrong password");
});

await check("the cookie's details; it works among other cookies; an expired one is the splash", async () => {
  const r = await post("pw-for-tests");
  const cookie = r.headers.get("set-cookie");
  assert.match(cookie, /Max-Age=2592000/);
  assert.match(cookie, /SameSite=Lax/);
  assert.match(cookie, /Path=\//);
  assert.strictEqual(r.headers.get("location"), "/");
  assert.match(r.headers.get("cache-control"), /no-store/);
  const page = await get("/", "a=1; " + cookie.split(";")[0] + "; b=2");
  assert.ok((await page.text()).includes("REAL SITE"));
  assert.match(page.headers.get("cache-control"), /private/, "no shared cache may hand it to somebody else");
  const expired = "recast_gate=" + await makeToken("pw-for-tests", 1000);
  assert.ok((await (await get("/", expired)).text()).includes("Coming soon"));
});

await check("same() compares whole strings", () => {
  assert.ok(same("abc", "abc"));
  assert.ok(!same("abc", "abd") && !same("abc", "abcd") && !same("", "a") && !same("a", undefined));
});

console.log(failures ? `\n${failures} FAILED` : "\nall gate tests passed");
process.exit(failures ? 1 : 0);
