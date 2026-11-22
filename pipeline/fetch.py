"""Polite fetching of public policy pages.

Rules this module enforces:
  * It says who it is: the User-Agent names the project and links to the repository.
  * It reads robots.txt for every host and never fetches a URL the host disallows.
  * It waits between requests to the same host and retries a failed request once or twice.
  * It never pretends to be a browser. When a host refuses automated readers (a bot challenge),
    it falls back to the newest copy the Internet Archive's Wayback Machine already holds, and
    says so: the result carries `via="wayback"` and the capture time, and the site prints both.

Standard library only; Python 3.9+.
"""
from __future__ import annotations

import datetime
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass, field

REPO_URL = "https://github.com/theguysaccount/supermind-killers-site"
UA = f"PlatformDefaultsBot/1.0 (+{REPO_URL})"
MAX_BYTES = 8_000_000
HOST_DELAY = 2.0            # seconds between requests to one host
MAX_ARCHIVE_DAYS = 180      # an archived copy older than this is too old to describe current practice
BLOCKED = {401, 403, 406, 409, 418, 429, 451, 503}   # answers that mean "not for automated readers"
_last_hit: dict[str, float] = {}
_robots: dict[str, "urllib.robotparser.RobotFileParser | None"] = {}


@dataclass
class Result:
    url: str
    status: int = 0                 # HTTP status of the final answer; 0 = no answer
    final_url: str = ""
    body: bytes = b""
    via: str = "direct"             # "direct" or "wayback"
    capture: str = ""               # Wayback capture time, YYYYMMDDhhmmss
    archive_url: str = ""           # the Wayback page a person can open
    error: str = ""                 # empty when the body is usable
    notes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.body)

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _pace(host: str, delay: float = HOST_DELAY) -> None:
    wait = _last_hit.get(host, 0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def _decode(body: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    try:
        if "gzip" in enc or body[:2] == b"\x1f\x8b":
            return gzip.decompress(body)
        if "deflate" in enc:
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except (OSError, EOFError, zlib.error):
        pass
    return body


def http_get(url: str, *, timeout: int = 40, tries: int = 3, delay: float = HOST_DELAY,
             accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8") -> tuple[int, str, bytes, str]:
    """GET with manual redirects (so 308 works on every Python). Returns (status, final_url, body, error)."""
    last = (0, url, b"", "no attempt")
    for attempt in range(tries):
        if attempt:
            time.sleep(6 * attempt)
        current = url
        try:
            for _hop in range(8):
                host = urllib.parse.urlsplit(current).netloc
                _pace(host, delay)
                req = urllib.request.Request(current, headers={
                    "User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.8",
                    "Accept-Encoding": "gzip"})
                try:
                    with _opener.open(req, timeout=timeout) as r:
                        body = _decode(r.read(MAX_BYTES), r.headers.get("Content-Encoding", ""))
                        return r.status, current, body, ""
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                        current = urllib.parse.urljoin(current, e.headers["Location"])
                        continue
                    try:
                        body = _decode(e.read(MAX_BYTES), e.headers.get("Content-Encoding", ""))
                    except Exception:
                        body = b""
                    last = (e.code, current, body, f"HTTP {e.code}")
                    break
            else:
                last = (0, current, b"", "too many redirects")
            if last[0] and last[0] < 500 and last[0] != 429:
                return last  # a client error will not change on retry
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            last = (0, current, b"", f"{type(reason).__name__}: {reason}")
    return last


def robots_allows(url: str) -> tuple[bool, str]:
    """(allowed, detail). An unreadable robots.txt (5xx, timeout) counts as "do not fetch today"."""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        status, _final, body, err = http_get(origin + "/robots.txt", tries=2, accept="text/plain,*/*;q=0.5")
        rp = urllib.robotparser.RobotFileParser()
        if status == 200:
            rp.parse(body.decode("utf-8", "replace").splitlines())
            _robots[origin] = rp
        elif status in (404, 410) or (400 <= status < 500 and status not in BLOCKED):
            rp.parse([])            # no robots.txt: nothing is disallowed
            _robots[origin] = rp
        elif status in BLOCKED:
            # The host will not show its robots.txt to a script. Treat the host as closed to direct
            # fetching; the caller may still read the Internet Archive's copy.
            _robots[origin] = None
        else:
            _robots[origin] = None
    rp = _robots[origin]
    if rp is None:
        return False, "robots.txt unreadable"
    ok = rp.can_fetch(UA, url)
    return ok, "allowed by robots.txt" if ok else "disallowed by robots.txt"


def robots_disallows(url: str) -> bool:
    """True only when robots.txt was read and it disallows this URL for this reader."""
    ok, detail = robots_allows(url)
    return (not ok) and detail == "disallowed by robots.txt"


def looks_like_challenge(body: bytes) -> bool:
    head = body[:6000].lower()
    return (b"just a moment" in head and b"cloudflare" in body[:20000].lower()) or b"cf-chl" in head \
        or b"enable javascript and cookies to continue" in head or b"attention required" in head


CDX = "https://web.archive.org/cdx/search/cdx"


def wayback_latest(url: str, newer_than: str = "") -> tuple[str, str]:
    """(timestamp, error) of the newest good Wayback capture of `url`, optionally newer than a timestamp."""
    q = {"url": url, "output": "json", "fl": "timestamp,statuscode,mimetype", "filter": "statuscode:200", "limit": "-4"}
    if newer_than:
        q["from"] = newer_than
    status, _f, body, err = http_get(CDX + "?" + urllib.parse.urlencode(q), timeout=75, tries=3, delay=4.0,
                                     accept="application/json")
    if status != 200:
        return "", f"Wayback index: {err or status}"
    try:
        rows = json.loads(body.decode("utf-8", "replace") or "[]")
    except ValueError:
        return "", "Wayback index: unreadable answer"
    stamps = [r[0] for r in rows[1:] if len(r) >= 2 and r[1] == "200"]
    if not stamps:
        return "", "Wayback has no capture" + (" newer than the last check" if newer_than else "")
    return max(stamps), ""


def wayback_get(url: str, newer_than: str = "", max_age_days: int = MAX_ARCHIVE_DAYS) -> Result:
    res = Result(url=url, via="wayback")
    stamp, err = wayback_latest(url, newer_than)
    if not stamp:
        res.error = err
        return res
    try:
        age = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)).days
    except ValueError:
        age = 0
    if age > max_age_days:
        res.error = f"the newest Internet Archive copy ({stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}) is older than {max_age_days} days"
        res.capture = stamp
        return res
    raw = f"https://web.archive.org/web/{stamp}id_/{url}"     # id_ = the page as captured, no toolbar
    status, final, body, err = http_get(raw, timeout=75, tries=3, delay=4.0)
    res.status, res.final_url, res.capture = status, url, stamp
    res.archive_url = f"https://web.archive.org/web/{stamp}/{url}"
    if status != 200 or not body:
        res.error = f"Wayback capture {stamp}: {err or status}"
        return res
    if looks_like_challenge(body):
        res.error = f"Wayback capture {stamp} holds a bot challenge, not the page"
        return res
    res.body = body
    return res


def fetch(url: str, *, allow_wayback: bool = True, wayback_newer_than: str = "") -> Result:
    """Fetch a public page politely. See the module docstring for the rules."""
    res = Result(url=url)
    allowed, detail = robots_allows(url)
    if not allowed and detail == "disallowed by robots.txt":
        res.error = "robots.txt disallows automated readers"
        res.notes.append(detail)
        return res  # the publisher said no: no archive fallback either
    blocked_reason = ""
    if allowed:
        status, final, body, err = http_get(url)
        res.status, res.final_url = status, final
        if status == 200 and body and not looks_like_challenge(body):
            res.body = body
            return res
        if status in BLOCKED or (status == 200 and looks_like_challenge(body)):
            blocked_reason = f"the live page refuses automated readers (HTTP {status})"
        else:
            res.error = err or f"HTTP {status}"
            if status in (404, 410):
                return res  # gone is gone; an old archive copy would hide that
            blocked_reason = res.error
    else:
        blocked_reason = "the host does not show robots.txt to automated readers"
    res.notes.append(blocked_reason)
    if not allow_wayback:
        res.error = blocked_reason
        return res
    wb = wayback_get(url, wayback_newer_than)
    wb.notes = res.notes + wb.notes
    if not wb.ok:
        wb.error = f"{blocked_reason}; {wb.error}"
        wb.status = wb.status or res.status
    return wb
