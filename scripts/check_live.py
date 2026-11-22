"""Health check of the live site, run weekly by selftest.yml.

    python3 scripts/check_live.py https://theguysaccount.github.io/supermind-killers-site

Checks: every sitemap URL answers 200 with its own canonical URL; the feed and the open data parse;
the IndexNow key file is published; the weekly policy check ran in the last 9 days and the site was
rebuilt after it. Exit codes: 0 healthy, 1 broken, 3 stale (the workflow then starts a policy check).
Standard library only.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

UA = "PlatformDefaultsBot/1.0 (+https://github.com/theguysaccount/supermind-killers-site)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_AGE_DAYS = 9    # older than this: start a documentation check (exit 3)
HARD_MAX_DAYS = 16  # older than this: two weekly checks were missed; report a failure (exit 1)


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url + ("&" if "?" in url else "?") + f"health={int(time.time())}",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = (e.code, "")
            if e.code < 500:
                return last
        except OSError as e:
            last = (0, str(e))
        time.sleep(5 * (i + 1))
    return last


def age_days(iso):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


def main(base):
    base = base.rstrip("/")
    problems, stale = [], []
    status, body = get(f"{base}/sitemap.xml")
    locs = [el.text for el in ET.fromstring(body).iter() if el.tag.endswith("loc")] if status == 200 else []
    if not locs:
        problems.append(f"sitemap: HTTP {status}, no URLs")
    for loc in locs:
        status, page = get(loc)
        canon = re.search(r'<link rel="canonical" href="([^"]+)"', page or "")
        if status != 200 or not canon or canon.group(1) != loc:
            problems.append(f"{loc}: HTTP {status}, canonical {canon.group(1) if canon else None}")
    status, feed = get(f"{base}/feed.xml")
    try:
        if status != 200 or not ET.fromstring(feed).findall("./channel/item"):
            problems.append("feed.xml has no items")
    except ET.ParseError as e:
        problems.append(f"feed.xml does not parse: {e}")
    status, raw = get(f"{base}/data/platforms.json")
    try:
        data = json.loads(raw)
        if not data["apps"]:
            problems.append("open data lists no apps")
        for what, when in (("the weekly documentation check last ran", data.get("checked")), ("the site was last rebuilt", data["built"])):
            age = age_days(when) if when else 999
            if age > HARD_MAX_DAYS:
                problems.append(f"{what} {when or 'never'} ({age:.0f} days ago)")
            elif age > MAX_AGE_DAYS:
                stale.append(f"{what} {when} ({age:.0f} days ago)")
        for a in data["apps"]:
            unread = a["flags"]["documents_unread"]
            if unread:
                print(f"::warning::{a['name']}: {unread} document(s) could not be read in the latest check")
            if a["flags"]["quotes_missing"]:
                print(f"::warning::{a['name']}: {a['flags']['quotes_missing']} quote(s) need re-review")
    except (ValueError, KeyError, TypeError) as e:
        problems.append(f"data/platforms.json: {e}")
    key = open(os.path.join(ROOT, "site", "indexnow-key.txt"), encoding="utf-8").read().strip()
    status, body = get(f"{base}/{key}.txt")
    if status != 200 or body.strip() != key:
        problems.append(f"IndexNow key file: HTTP {status}")
    print(f"checked {len(locs)} pages on {base}")
    for p in problems:
        print(f"::error::{p}")
    for s in stale:
        print(f"::warning::stale: {s}")
    return 1 if problems else 3 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
