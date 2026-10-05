"""IWeb / IWebResp / ISource: just enough of BREW's HTTP stack for the game.

The game asks IWeb for a URL (IWEB_GetResponse), waits on an AEECallback, then
reads WebRespInfo { int nCode; ISource *pisMessage; int32 lContentLength; }
and drains the body 1 KB at a time. Nothing leaves the machine: requests go to
the offline leaderboard (leaderboard.py). Any other URL, such as the old
episode download, gets a 404 and the game shows its own error.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlsplit

from .hle import EFAILED, ISOURCE_END, SUCCESS, HleObject

if TYPE_CHECKING:
    from .runtime import Emulator

REPLY_DELAY_MS = 150      # the game shows "Sending..."; don't answer in the same breath
REMOTE_TIMEOUT = 4.0      # the game is sitting on "Sending..."; give up quickly
MAX_REPLY = 4096          # a real reply is a few dozen bytes


def wonderland_post(url: str):
    """(score, the same request as an Island score) if the game is posting a Wonderland
    score, else None. Wonderland is lost, so its screen only repeats the Island run's
    stats; the game offers to post them a second time under "wonderland"."""
    from urllib.parse import parse_qs, urlencode, urlunsplit
    parts = urlsplit(url)
    if not parts.path.lower().endswith("/rank.php"):
        return None
    q = parse_qs(parts.query, keep_blank_values=True)
    if q.get("lid", [""])[0].lower() != "wonderland":
        return None
    try:
        score = int(q["s"][0])
    except (KeyError, ValueError, IndexError):
        return None
    q["lid"] = ["island"]
    return score, urlunsplit(parts._replace(query=urlencode(q, doseq=True)))


def with_play_time(url: str, seconds) -> str:
    """The same rank.php request with the measured play time added as `pt`. The shared
    leaderboard ignores the game's own `t` (a running clock) and only accepts a score that
    comes with a believable time, so a run that was not measured is sent without one."""
    from urllib.parse import parse_qs, urlencode, urlunsplit
    parts = urlsplit(url)
    if seconds is None or not parts.path.lower().endswith("/rank.php"):
        return url
    q = parse_qs(parts.query, keep_blank_values=True)
    q["pt"] = [str(int(seconds))]
    return urlunsplit(parts._replace(query=urlencode(q, doseq=True)))


def with_stats(url: str, stats) -> str:
    """The same rank.php request with the Munny, EXP and level behind the score added (`mn`,
    `ex`, `lv`), for the shared leaderboard to show. No stats, or not a score post: unchanged."""
    from urllib.parse import parse_qs, urlencode, urlunsplit
    parts = urlsplit(url)
    if not stats or not parts.path.lower().endswith("/rank.php"):
        return url
    q = parse_qs(parts.query, keep_blank_values=True)
    q["mn"] = [str(int(stats["munny"]))]
    q["ex"] = [str(int(stats["exp"]))]
    if stats.get("level") is not None:
        q["lv"] = [str(int(stats["level"]))]
    return urlunsplit(parts._replace(query=urlencode(q, doseq=True)))


def share_scores(url: str, base: str, timeout: float = REMOTE_TIMEOUT) -> Optional[bytes]:
    """Ask a shared leaderboard (server/worker.js) the question the game asked, by
    putting the game's own path and query on `base`. Returns the reply, or None if
    anything at all went wrong, in which case the caller answers offline instead.

    Only the score itself is sent: the level, the number, how long the run took, and the
    Munny, EXP and level behind it. There is no account and nothing identifying is added to
    the request."""
    parts = urlsplit(url)
    target = base.rstrip("/") + parts.path + (("?" + parts.query) if parts.query else "")
    if urlsplit(target).scheme not in ("http", "https"):
        return None               # a typo in the address must not reach the opener
    try:
        req = urllib.request.Request(target, headers={"User-Agent": "khvcemu"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            body = r.read(MAX_REPLY)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    # a captive portal or an error page must never reach the game's parser
    return body if body.startswith(b"*r|") else None


class BodySource(HleObject):
    """ISource over the response body."""

    IFACE = "ISource"
    SLOTS = ("AddRef", "Release", "QueryInterface", "Read", "Readable")

    def __init__(self, emu: "Emulator", body: bytes):
        super().__init__(emu)
        self.body = body
        self.pos = 0

    def Read(self, c):
        buf, n = c.arg(1), c.sarg(2)
        chunk = self.body[self.pos:self.pos + max(0, n)]
        if not chunk:
            return ISOURCE_END
        self.cpu.write(buf, chunk)
        self.pos += len(chunk)
        return len(chunk)

    def Readable(self, c):
        # everything is already here: tell the reader to try again straight away
        self.emu.resume_callback(c.arg(1))


class WebResp(HleObject):
    """IWebResp: GetInfo hands back the WebRespInfo block."""

    IFACE = "IWebResp"
    SLOTS = ("AddRef", "Release", "QueryInterface", "AddOpt", "RemoveOpt", "GetOpt", "GetInfo")

    def __init__(self, emu: "Emulator", code: int, body: bytes):
        super().__init__(emu)
        self.source = BodySource(emu, body)
        self.info = emu.cpu.hle_alloc(32, 8)
        emu.cpu.write(self.info, b"\0" * 32)
        emu.cpu.w32(self.info, code)
        emu.cpu.w32(self.info + 4, self.source.ptr)
        emu.cpu.w32(self.info + 8, len(body))

    def GetInfo(self, c):
        return self.info

    def AddOpt(self, c):
        return SUCCESS

    def RemoveOpt(self, c):
        return SUCCESS

    def GetOpt(self, c):
        return EFAILED


class Web(HleObject):
    """IWeb (AEECLSID_WEB)."""

    IFACE = "IWeb"
    SLOTS = ("AddRef", "Release", "QueryInterface", "AddOpt", "RemoveOpt", "GetResponseV",
             "GetResponse")

    def AddOpt(self, c):
        return SUCCESS

    def RemoveOpt(self, c):
        return SUCCESS

    def GetResponse(self, c):
        # IWEB_GetResponse(pme, ppiwresp, pcb, url, <option id, value>..., WEBOPT_END);
        # the options (a status handler and an X-Method header) don't matter here
        ppresp, pcb, url = c.arg(1), c.arg(2), self.cpu.cstr(c.arg(3))
        code, body = self.emu.web_request(url)
        resp = WebResp(self.emu, code, body)
        if ppresp:
            self.cpu.w32(ppresp, resp.ptr)
        self.emu.resume_callback(pcb, REPLY_DELAY_MS)
        return None

    GetResponseV = GetResponse


def default_leaderboard_path(emu: "Emulator") -> str:
    return os.path.join(emu.data_dir, "leaderboard.db")
