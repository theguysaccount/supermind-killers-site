"""Re-read every policy document, re-verify every quote, and record what changed.

    python3 -m pipeline.check                 # the weekly job
    python3 -m pipeline.check --only chatgpt  # one app
    python3 -m pipeline.check --review        # reviewer's gate: exit 1 if any quote is not found
    python3 -m pipeline.check --offline       # no network: re-verify quotes against .cache/ (reviewers)

What it does for each document on each scorecard:
  1. Fetches the page politely (pipeline/fetch.py). A page that cannot be read keeps its last
     good record and is marked with the reason; it never fails the run.
  2. Compares the page's sentences with the fingerprints stored at the last good read. Added and
     removed sentences are counted, and a few added sentences are kept as short excerpts.
  3. Looks for every quote attributed to the document. A quote that no longer appears word for
     word is marked "no longer found" with the date, and the scorecard is flagged for re-review.
  4. Appends one entry per changed document to data/changes.json, which feeds the change log,
     the RSS feed and the flags on each scorecard.

The run fails only on a bug in this code or a broken data file. Standard library only; Python 3.9+.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import fetch as F
from . import store as S
from . import textutil as T

GRACE_DAYS = 14         # a blocked page keeps its last good read this long before it is flagged
MIN_WORDS = 120          # fewer words than this is an error page or an empty shell, not a policy
SHRINK = 0.35            # a page that lost two thirds of its words is treated as unreadable, not as a change
MAX_EXCERPTS = 4
EXCERPT_CHARS = 280


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_since(iso: str) -> float:
    try:
        t = dt.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return 9999.0
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


def capture_iso(stamp: str) -> str:
    """Wayback timestamp (YYYYMMDDhhmmss) as an ISO time."""
    try:
        return dt.datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""


def doc_text(doc: dict, html: str) -> str:
    return T.clip(T.html_to_text(html), doc.get("start", ""), doc.get("end", ""))


def read_document(app: dict, doc_id: str, doc: dict, prev: dict, *, offline: bool = False):
    """Returns (record, text or None). `record` is the new state entry for the document."""
    rec = dict(prev)
    rec["url"] = doc["url"]
    rec["checked"] = now_iso()
    if offline:
        from .grab import cached_fetch
        m = cached_fetch(doc["url"], max_age=10 ** 9)
        res = F.Result(url=doc["url"], status=m["status"], via=m["via"], capture=m["capture"],
                       archive_url=m.get("archive_url", ""), error=m["error"], body=m["html"].encode("utf-8"))
    else:
        res = F.fetch(doc["url"])
        if prev.get("last_ok") and not res.ok and res.via == "wayback" or (
                res.via == "wayback" and res.ok and prev.get("last_ok") and capture_iso(res.capture) <= prev["last_ok"]):
            # The live page refused this reader and the archive holds nothing newer than the text
            # already read: no new information. The last good read stands, with its own date, for
            # GRACE_DAYS; after that the document is marked unreadable so the page says so. When that
            # read was itself an archive copy, it stays good while the copy is under the archive's
            # own age limit (the limit it was accepted under).
            age = days_since(prev["last_ok"])
            limit = F.MAX_ARCHIVE_DAYS if prev.get("via") == "wayback" else GRACE_DAYS
            stale = age > limit
            rec["status"] = "unreachable" if stale else "ok"
            rec["error"] = (f"{'; '.join(res.notes)}; no newer archived copy; last good read {age:.0f} days ago"
                            if stale else "")
            rec["note"] = "; ".join(res.notes) + "; showing the last good read"
            return rec, None
    if not res.ok:
        rec["status"] = "disallowed" if "robots.txt disallows" in res.error else "unreachable"
        rec["error"] = res.error
        return rec, None
    text = doc_text(doc, res.text())
    words = len(text.split())
    if words < doc.get("min_words", MIN_WORDS) or (prev.get("words") and words < prev["words"] * SHRINK):
        rec["status"] = "unreachable"
        rec["error"] = f"the page returned only {words} words of text (was {prev.get('words', 'unknown')})"
        return rec, None
    rec.update(status="ok", error="", via=res.via, capture=res.capture, archive_url=res.archive_url,
               words=words, note="; ".join(res.notes))
    # "As of": when the text that was read was true. For an archive copy that is the capture time.
    rec["last_ok"] = capture_iso(res.capture) if res.via == "wayback" else rec["checked"]
    return rec, text


def check_app(app: dict, state: dict, changes: list, *, offline: bool = False, data: str = S.DATA) -> list[dict]:
    """Check one app's documents and quotes. Returns the new change entries."""
    slug = app["slug"]
    new_events = []
    today = now_iso()[:10]
    by_doc: dict[str, list] = {}
    for where, cid, ev in S.evidence(app):
        by_doc.setdefault(ev["doc"], []).append((where, cid, ev))
    for doc_id, doc in app["documents"].items():
        key = f"{slug}/{doc_id}"
        prev = state["docs"].get(key, {})
        rec, text = read_document(app, doc_id, doc, prev, offline=offline)
        state["docs"][key] = rec
        print(f"  {key}: {rec['status']}" + (f" via {rec.get('via')}" if rec["status"] == "ok" else f" ({rec.get('error')})")
              + ("" if text is not None else " [no new text]"), flush=True)
        if text is None:
            continue
        old_sig = S.load_sig(slug, doc_id, data)
        new_sig = T.signature(text)
        added, removed = T.diff(old_sig, text) if old_sig else ([], 0)
        missing = []
        for where, cid, ev in by_doc.get(doc_id, []):
            qid = S.quote_id(slug, doc_id, ev["quote"])
            q = state["quotes"].get(qid, {})
            if T.contains(text, ev["quote"]):
                q.update(found=True, last_found=rec["last_ok"][:10])
                q.pop("missing_since", None)
            else:
                if q.get("found", True):
                    q["missing_since"] = rec["last_ok"][:10]
                    missing.append({"criterion": cid, "quote": ev["quote"]})
                q["found"] = False
            q.update(app=slug, doc=doc_id)
            state["quotes"][qid] = q
        if old_sig and (added or removed):
            rec["changed"] = rec["last_ok"][:10]
            event = {
                "id": f"{rec['last_ok'][:10]}-{slug}-{doc_id}",
                "date": rec["last_ok"][:10],        # as-of date of the text that showed the change
                "detected": today,
                "app": slug, "doc": doc_id, "title": doc["title"], "url": doc["url"],
                "via": rec.get("via", "direct"), "capture": rec.get("capture", ""),
                "archive_url": rec.get("archive_url", ""),
                "added": len(added), "removed": removed,
                "excerpts": [a if len(a) <= EXCERPT_CHARS else a[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
                             for a in added[:MAX_EXCERPTS]],
                "quotes_missing": missing,
                "quotes_checked": len(by_doc.get(doc_id, [])),
            }
            # One entry per document per as-of date, so a re-run never duplicates an entry.
            if not any(c["id"] == event["id"] for c in changes):
                changes.append(event)
                new_events.append(event)
        elif missing:
            what = "an unchanged document" if old_sig else "the document (first read, nothing to compare with)"
            print(f"  ! {key}: {len(missing)} quote(s) not found in {what}", flush=True)
        if not offline:
            S.save_sig(slug, doc_id, new_sig, data)
    return new_events


def prune(state: dict, apps: list[dict]) -> None:
    """Drop state for documents and quotes that no scorecard uses any more."""
    doc_keys = {f"{a['slug']}/{d}" for a in apps for d in a["documents"]}
    quote_ids = {S.quote_id(a["slug"], ev["doc"], ev["quote"]) for a in apps for _w, _c, ev in S.evidence(a)}
    state["docs"] = {k: v for k, v in state["docs"].items() if k in doc_keys}
    state["quotes"] = {k: v for k, v in state["quotes"].items() if k in quote_ids}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", default=[], help="check only this app (slug); repeatable")
    ap.add_argument("--review", action="store_true", help="exit 1 if any quote is not found (for reviewers)")
    ap.add_argument("--offline", action="store_true", help="use .cache/ instead of the network")
    ap.add_argument("--events-out", help="write this run's new change entries to a JSON file")
    ap.add_argument("--data", default=S.DATA)
    args = ap.parse_args(argv)

    apps = S.apps(args.data)
    state, changes = S.state(args.data), S.changes(args.data)
    new_events = []
    for app in apps:
        if args.only and app["slug"] not in args.only:
            continue
        print(app["slug"], flush=True)
        new_events += check_app(app, state, changes, offline=args.offline, data=args.data)
    if not args.only:
        prune(state, apps)
    docs = state["docs"].values()
    ok = sum(1 for d in docs if d.get("status") == "ok")
    if args.offline:
        # Offline runs verify quotes against cached copies for a reviewer. They change no data file:
        # the cache is not evidence that a page was read today.
        pass
    else:
        if not args.only:  # "checked" means every scorecard was checked
            state["checked"] = now_iso()
            if ok:
                state["last_run_ok"] = state["checked"]
        S.save_state(state, args.data)
        S.save_changes(changes, args.data)
    if args.events_out:
        with open(args.events_out, "w", encoding="utf-8") as f:
            json.dump(new_events, f, ensure_ascii=False, indent=1)
    missing = [q for q in state["quotes"].values() if not q.get("found") and (not args.only or q.get("app") in args.only)]
    print(f"documents: {ok} read, {len(state['docs']) - ok} not read; quotes: "
          f"{len(state['quotes']) - len(missing)} found, {len(missing)} not found; new changes: {len(new_events)}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Policy check\n\n- Documents read: {ok} of {len(state['docs'])}\n"
                    f"- Quotes found word for word: {len(state['quotes']) - len(missing)} of {len(state['quotes'])}\n"
                    f"- New changes recorded: {len(new_events)}\n\n")
            for d_key, d in sorted(state["docs"].items()):
                if d.get("status") != "ok":
                    f.write(f"- `{d_key}` not read: {d.get('error')}\n")
    if args.review and missing:
        for q in missing:
            print(f"NOT FOUND: {q.get('app')}/{q.get('doc')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
