"""Reviewer's tool: fetch a policy page the same way the weekly check does and print its text.

    python3 -m pipeline.grab URL [URL ...]            # print how each page was read
    python3 -m pipeline.grab --show URL               # print the extracted text
    python3 -m pipeline.grab --find "opt out" URL     # print the lines that mention a phrase

Pages are cached under .cache/ (not committed) for a day, so reviewing a document does not hit the
publisher's site again and again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

from . import fetch as F
from . import textutil as T

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")


def cached_fetch(url: str, max_age: float = 86400, refresh: bool = False) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    meta_path, body_path = os.path.join(CACHE, key + ".json"), os.path.join(CACHE, key + ".html")
    if not refresh and os.path.exists(meta_path) and time.time() - os.path.getmtime(meta_path) < max_age:
        meta = json.load(open(meta_path, encoding="utf-8"))
        meta["html"] = open(body_path, encoding="utf-8", errors="replace").read() if os.path.exists(body_path) else ""
        return meta
    res = F.fetch(url)
    meta = {"url": url, "status": res.status, "via": res.via, "capture": res.capture, "error": res.error,
            "final_url": res.final_url, "notes": res.notes, "archive_url": res.archive_url}
    json.dump(meta, open(meta_path, "w", encoding="utf-8"))
    with open(body_path, "w", encoding="utf-8") as f:
        f.write(res.text() if res.ok else "")
    meta["html"] = res.text() if res.ok else ""
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--find", action="append", default=[])
    ap.add_argument("--context", type=int, default=0, help="lines of context around a --find hit")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    for url in args.urls:
        m = cached_fetch(url, refresh=args.refresh)
        text = T.html_to_text(m["html"]) if m["html"] else ""
        words = len(text.split())
        how = m["via"] + (f" capture {m['capture']}" if m["capture"] else "")
        print(f"# {url}\n#   status={m['status']} via={how} words={words} sentences={len(T.signature(text))}"
              f"{' ERROR: ' + m['error'] if m['error'] else ''}")
        lines = text.split("\n")
        if args.show:
            print(text)
        for pat in args.find:
            rx = re.compile(pat, re.I)
            for i, line in enumerate(lines):
                if rx.search(line):
                    lo, hi = max(0, i - args.context), min(len(lines), i + args.context + 1)
                    for j in range(lo, hi):
                        print(f"{j:5d}{'>' if j == i else ' '} {lines[j]}")
                    if args.context:
                        print("      --")
    return 0


if __name__ == "__main__":
    sys.exit(main())
