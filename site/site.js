// Shared by every page of khrecast.com: the download links, the menu button, Help answers opened from a link, and
// the anonymous counters. Each page says which it is with <body data-page="...">.

// ---------------------------------------------------------------------------
// The download URLs are NOT written here: the public repository must not carry direct
// links to the installers. They live in site/links.js, which is kept out of git and
// deployed with the site; it sets window.KH_LINKS. A button whose link is empty shows
// "link coming soon" and cannot be clicked, so nothing on the page is ever a dead link.
var LINKS = {
  win64:    "",   // KH-ReCast-Windows-x64.exe
  win32:    "",   // KH-ReCast-Windows-x86.exe
  macArm:   "",   // KH-ReCast-macOS-arm64.zip
  macIntel: "",   // KH-ReCast-macOS-x86_64.zip
  linux64:  "",   // KH-ReCast-Linux-x86_64.run
  linuxArm: "",   // KH-ReCast-Linux-aarch64.run
  android:  "",   // KH-ReCast-Android.zip (the app and the game files, for phones)
  androidX64: "", // KH-ReCast-Android-x86_64.zip (the same, for Chromebooks and emulators)
  sources:  "",   // KH-ReCast-sources.zip (the source code of the bundled GPL and LGPL programs)
  repo:     "https://github.com/khrecast/khvcemu",
  issues:   "https://github.com/khrecast/khvcemu/issues",
};
Object.assign(LINKS, window.KH_LINKS || {});
// ---------------------------------------------------------------------------

document.querySelectorAll("[data-link]").forEach(function (a) {
  var url = LINKS[a.dataset.link];
  if (a.dataset.link === "email") return;            // the mailto: in the HTML stays
  if (url) { a.href = url; return; }
  a.setAttribute("aria-disabled", "true");
  a.removeAttribute("href");
  a.title = "This link isn't available yet";
  if (a.classList.contains("btn")) a.dataset.label = a.textContent, a.textContent = "Link coming soon";
});

// Highlight the download that fits this computer (download page) and point the big button (home page) at it.
(function () {
  var ua = navigator.userAgent || "";
  var os = null;
  if (/Android/i.test(ua)) os = "android";
  else if (/Windows/i.test(ua)) os = /Win64|x64|WOW64|ARM64/i.test(ua) ? "win64" : "win32";
  else if (/Macintosh|Mac OS X/i.test(ua) && !/iPhone|iPad|iPod/i.test(ua)) os = "mac";
  else if (/Linux|X11/i.test(ua) && !/Android|CrOS/i.test(ua)) os = /aarch64|arm/i.test(ua) ? "linuxArm" : "linux64";
  var hero = document.getElementById("hero-dl"), note = document.getElementById("hero-note");
  function recommend(selector) { document.querySelectorAll(selector).forEach(function (c) { c.classList.add("recommended"); }); }
  function say(text, href, small) {
    if (!hero) return;
    hero.textContent = text; hero.href = href;
    if (note) note.textContent = small;
  }
  if (os === "android") {                            // on a phone the big button is the Android app
    recommend('[data-os="android"]');
    say("Download for Android", LINKS.android || "download.html", "Free and open source. Android 7 or newer, 64-bit phones.");
  } else if (os === "mac") {
    recommend('[data-os^="mac"]');
    say("Download for Mac", "download.html", "Free and open source. Pick Apple Silicon or Intel on the download page.");
  } else if (os) {
    recommend('[data-os="' + os + '"]');
    var linux = os.indexOf("linux") === 0;
    say(linux ? "Download for Linux" : "Download for Windows", LINKS[os] || "download.html",
      linux ? "Free and open source. Needs a glibc 2.28+ desktop Linux." : "Free and open source. Windows 10 or 11.");
  } else if (hero) {
    hero.textContent = "See downloads";
  }
})();

// a link to a Help answer (#android-help) opens it, on arrival or on click
(function () {
  function openFromHash() {
    var el = location.hash && document.getElementById(location.hash.slice(1));
    if (el && el.tagName === "DETAILS") el.open = true;
  }
  window.addEventListener("hashchange", openFromHash);
  openFromHash();
})();

// the menu button opens the links as a drop-down on narrow screens
(function () {
  var btn = document.getElementById("menu-btn"), nav = document.getElementById("site-nav");
  if (!btn || !nav) return;
  function set(open) { nav.classList.toggle("open", open); btn.setAttribute("aria-expanded", open ? "true" : "false"); }
  btn.addEventListener("click", function (e) { e.stopPropagation(); set(!nav.classList.contains("open")); });
  nav.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("a")) set(false); });
  document.addEventListener("click", function (e) { if (!nav.contains(e.target)) set(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") set(false); });
})();

// Main Menu: its list of the home page's parts opens on click (on a phone, inside the menu)
(function () {
  var btn = document.getElementById("mm-btn"), list = document.getElementById("mm-list");
  if (!btn || !list) return;
  function set(open) { list.hidden = !open; btn.setAttribute("aria-expanded", open ? "true" : "false"); }
  btn.addEventListener("click", function (e) { e.stopPropagation(); set(list.hidden); });
  document.addEventListener("click", function (e) { if (!btn.parentNode.contains(e.target) || (e.target.closest && e.target.closest("a"))) set(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !list.hidden) { set(false); btn.focus(); } });
})();

// Find Wonderland wobbles while the page scrolls, each letter a little out of step, and settles back when it stops
// (not for visitors who ask for less motion)
(function () {
  var letters = document.querySelectorAll(".wl i:not(.sp)");
  if (!letters.length || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
  var queued = false, settle = null;
  function set(el, w, b) { el.style.setProperty("--w", w + "deg"); el.style.setProperty("--b", b + "px"); }
  function wobble() {
    queued = false;
    var phase = window.scrollY / 30;
    letters.forEach(function (el, i) { set(el, (7 * Math.sin(phase + i * 0.8)).toFixed(1), (2 * Math.cos(phase + i * 0.8)).toFixed(1)); });
  }
  window.addEventListener("scroll", function () {
    if (!queued) { queued = true; requestAnimationFrame(wobble); }
    clearTimeout(settle);
    settle = setTimeout(function () { letters.forEach(function (el) { set(el, 0, 0); }); }, 250);
  }, { passive: true });
})();

// a picture link marked "zoom" opens the picture large over the page; a click or Escape closes it
(function () {
  var links = document.querySelectorAll("a.zoom"), box = document.createElement("dialog");
  if (!links.length || !box.showModal) return;          // without dialogs, the link simply opens the picture
  var img = document.createElement("img");
  box.className = "zoombox"; box.appendChild(img); document.body.appendChild(box);
  links.forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var small = a.querySelector("img");
      img.src = a.href; img.alt = small ? small.alt : "";
      box.showModal();
    });
  });
  box.addEventListener("click", function () { box.close(); });
})();

// Anonymous counters: how often each page is opened, which parts of the home page are scrolled to and which buttons
// are clicked, so the author can tell whether anyone uses this. No cookie, and the server stores only a day, a name
// and a count (server/worker.js). Besides the opening of the home page itself, only two short labels are sent, from
// fixed lists: the kind of computer (windows, mac, linux, android, ios...) and where the visitor came from (reddit,
// google, direct...; the website's name only, never the address). Nothing is sent if the browser says Do Not Track.
(function () {
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl) return;
  if (window.KH_LEAVING) return;                     // an old link on its way to the page that now holds it
  var URL_ = "https://scores.khrecast.com/hit?e=";
  function hit(name, extra) {
    try { fetch(URL_ + encodeURIComponent(name) + (extra || ""), { mode: "no-cors", keepalive: true, credentials: "omit" }); } catch (e) { /* never matters */ }
  }
  function kindOfComputer() {
    var ua = navigator.userAgent || "";
    if (/Android/i.test(ua)) return "android";
    if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
    if (/CrOS/.test(ua)) return "chromeos";
    if (/Windows/i.test(ua)) return "windows";
    if (/Macintosh|Mac OS X/i.test(ua)) return "mac";
    if (/Linux|X11/i.test(ua)) return "linux";
    return "other";
  }
  function whereFrom() {
    var r = document.referrer, h = "";
    if (!r) return "direct";
    try { h = new URL(r).hostname.toLowerCase().replace(/^www\./, ""); } catch (e) { return "other"; }
    var known = [["direct", /^khrecast\.com$/], ["reddit", /(^|\.)reddit\.com$|^redd\.it$/], ["google", /(^|\.)google\.[a-z.]+$/],
      ["bing", /(^|\.)bing\.com$/], ["duckduckgo", /(^|\.)duckduckgo\.com$/], ["youtube", /(^|\.)youtube\.com$|^youtu\.be$/],
      ["x", /^(t\.co|x\.com|twitter\.com)$|\.(x|twitter)\.com$/], ["bluesky", /(^|\.)bsky\.app$/], ["facebook", /(^|\.)(facebook|fb)\.com$/],
      ["discord", /(^|\.)discord(app)?\.com$|^discord\.gg$/], ["khinsider", /(^|\.)khinsider\.com$/], ["kh13", /(^|\.)kh13\.com$/],
      ["khwiki", /(^|\.)(khwiki|khdatabase)\.com$/], ["lostmedia", /(^|\.)lostmediawiki\.com$/], ["archive", /(^|\.)archive\.org$/],
      ["github", /(^|\.)github\.com$/], ["hackernews", /^news\.ycombinator\.com$/]];
    for (var i = 0; i < known.length; i++) if (known[i][1].test(h)) return known[i][0];
    return "other";
  }
  var page = document.body.getAttribute("data-page") || "home";
  hit("view:" + page, page === "home" ? "&o=" + kindOfComputer() + "&r=" + whereFrom() : "");

  // which parts of the home page are read: a section counts once, when it is in the middle part of the window
  var sectionEls = page !== "home" ? [] : ["about", "features", "screens", "launcher", "composer", "help", "credits"]
    .map(function (id) { return document.getElementById(id); }).filter(Boolean);
  var sectionSeen = {}, sectionTimer = null;
  function checkSections() {
    sectionTimer = null;
    var h = window.innerHeight;
    sectionEls.forEach(function (el) {
      if (sectionSeen[el.id]) return;
      var r = el.getBoundingClientRect();
      if (r.top <= h * 0.7 && r.bottom >= h * 0.3) { sectionSeen[el.id] = 1; hit("sec:" + el.id); }   // overlaps the middle 40% of the window
    });
  }
  if (sectionEls.length) {
    window.addEventListener("scroll", function () { if (!sectionTimer) sectionTimer = setTimeout(checkSections, 150); }, { passive: true });
    setTimeout(checkSections, 600);                    // what is already in view when the page has opened (a link to #help)
  }
  document.addEventListener("click", function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest("a") : null;
    if (!a || !a.getAttribute("href") || a.getAttribute("aria-disabled") === "true") return;
    var key = a.getAttribute("data-link") || "", href = a.getAttribute("href"), links = window.KH_LINKS || {}, dl = "";
    for (var k in links) if (/^(win64|win32|macArm|macIntel|linux64|linuxArm|android|androidX64)$/.test(k) && links[k] && links[k] === href) dl = k;     // any button that goes to an installer, the big Download one too
    if (dl) hit("dl:" + dl);
    else if (/^(win64|win32|macArm|macIntel|linux64|linuxArm|android|androidX64)$/.test(key)) hit("dl:" + key);
    else if (/^(repo|issues|email)$/.test(key)) hit("click:" + key);
    else if (/SHA256SUMS\.txt$/.test(href)) hit("dl:sums");
    else if (href.indexOf("khinsider.com") >= 0) hit("click:soundtrack");
  });
})();
