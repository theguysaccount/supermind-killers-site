"""Load and save the project's data files.

  data/rubric.json        the published rubric: criteria, answers and points
  data/apps/<slug>.json   one reviewed scorecard per app: documents, answers, quotes
  data/state.json         machine-written: how each document was last read, and each quote's status
  data/sigs/<app>.<doc>   machine-written: sentence fingerprints of each document at its last good read
  data/changes.json       machine-written, append-only: every detected policy change

Standard library only; Python 3.9+.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Iterator

from . import textutil as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def rubric(data: str = DATA) -> dict:
    return _read(os.path.join(data, "rubric.json"), {})


def apps(data: str = DATA) -> list[dict]:
    folder = os.path.join(data, "platforms")
    out = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json"):
            app = _read(os.path.join(folder, name), None)
            if app:
                out.append(app)
    return out


def state(data: str = DATA) -> dict:
    s = _read(os.path.join(data, "state.json"), {})
    s.setdefault("docs", {})
    s.setdefault("quotes", {})
    return s


def save_state(s: dict, data: str = DATA) -> None:
    _write(os.path.join(data, "state.json"), s)


def changes(data: str = DATA) -> list[dict]:
    return _read(os.path.join(data, "changes.json"), [])


def save_changes(c: list[dict], data: str = DATA) -> None:
    _write(os.path.join(data, "changes.json"), c)


def sig_path(app: str, doc: str, data: str = DATA) -> str:
    return os.path.join(data, "sigs", f"{app}.{doc}")


def load_sig(app: str, doc: str, data: str = DATA) -> list[str]:
    try:
        with open(sig_path(app, doc, data), encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []


def sig_reader(app: str, doc: str, data: str = DATA) -> int:
    """Version of the reader that wrote the stored fingerprints (a file without a header: 1)."""
    try:
        with open(sig_path(app, doc, data), encoding="utf-8") as f:
            m = re.match(r"# reader (\d+)", f.readline())
    except FileNotFoundError:
        return 0
    return int(m.group(1)) if m else 1


def save_sig(app: str, doc: str, sig: list[str], data: str = DATA) -> None:
    path = sig_path(app, doc, data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# reader {T.READER}\n" + "\n".join(sig) + "\n")


def quote_id(app: str, doc: str, quote: str) -> str:
    return hashlib.sha1(f"{app}/{doc}/{T.norm(quote)}".encode("utf-8")).hexdigest()[:14]


def evidence(app: dict) -> Iterator[tuple[str, str, dict]]:
    """Every quoted passage on a scorecard: (where it is used, criterion or fact id, evidence item)."""
    for cid, ans in (app.get("answers") or {}).items():
        for ev in ans.get("evidence") or []:
            yield "answer", cid, ev
    for fid, fact in (app.get("facts") or {}).items():
        for ev in fact.get("evidence") or []:
            yield "fact", fid, ev
    opt = app.get("opt_out") or {}
    for ev in opt.get("evidence") or []:
        yield "opt_out", "opt_out", ev


def score(app: dict, rub: dict) -> tuple[int, int]:
    """(points, maximum) for a scorecard under the rubric."""
    pts = mx = 0
    for c in rub["criteria"]:
        best = max(a["points"] for a in c["answers"])
        mx += best
        ans = (app.get("answers") or {}).get(c["id"], {}).get("answer")
        pts += next((a["points"] for a in c["answers"] if a["id"] == ans), 0)
    return pts, mx
