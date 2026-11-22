"""Render the 1200x630 share cards (og/home.png and og/<slug>.png) into a built site with headless Chrome.

    python3 -m pipeline.og dist            # after pipeline.build
    python3 -m pipeline.og --default       # re-render site/og-default.png (committed fallback)

GitHub's Ubuntu runners ship Google Chrome. Without Chrome, the build's copies of site/og-default.png
stay in place, so no page ever points at a missing image. Standard library only.
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMES = [os.environ.get("CHROME", ""), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
E = html.escape

CSS = """*{box-sizing:border-box}html,body{margin:0;width:1200px;height:630px;overflow:hidden}
body{background:#f7f6f2;color:#1b232b;font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,"DejaVu Sans",sans-serif;padding:60px 70px;display:flex;flex-direction:column}
.top{display:flex;align-items:center;gap:16px;font-size:30px;font-weight:750;color:#1f5f8b}
h1{font-size:68px;line-height:1.05;letter-spacing:-1.5px;margin:40px 0 14px}
.sub{font-size:30px;color:#56626d;line-height:1.35}
.row{display:flex;gap:22px;margin-top:auto;align-items:flex-end}
.score{font-size:120px;font-weight:800;line-height:.9}.score small{font-size:40px;color:#56626d;font-weight:600}
.pill{font-size:30px;font-weight:700;border-radius:999px;padding:10px 24px;background:#e3f2ea;color:#2f7d5b}
.pill.mid{background:#fbf0d9;color:#8a5a0b}.pill.low{background:#f8e4e1;color:#8a3b3b}.pill.unknown{background:#e9ecee;color:#4f5b64}
.foot{font-size:24px;color:#56626d;margin-left:auto;text-align:right}"""
LOGO = ('<svg viewBox="0 0 32 32" width="52" height="52"><rect x="3" y="3" width="26" height="26" rx="7" fill="#1f5f8b"/>'
        '<path d="M9 11h14M9 16h10M9 21h7" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><circle cx="23" cy="21" r="3" fill="#7fd1ae"/></svg>')


def find_chrome():
    for c in CHROMES:
        if c and (os.path.exists(c) or shutil.which(c)):
            return shutil.which(c) or c
    return None


def render(chrome: str, body: str, out_png: str) -> bool:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "card.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--mute-audio",
               "--force-device-scale-factor=1", "--window-size=1200,630", f"--user-data-dir={os.path.join(d, 'profile')}",
               f"--screenshot={out_png}", "file://" + src]
        try:
            subprocess.run(cmd, check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError):
            return False
    return os.path.exists(out_png) and os.path.getsize(out_png) > 2000


def home_card(n_apps: int) -> str:
    return (f'<div class="top">{LOGO}Platform Defaults</div><h1>How are social apps set up for teens?</h1>'
            f'<div class="sub">{n_apps} platforms compared on what their own documentation says is on by default: private accounts, '
            f'messages, time and bedtime reminders, feeds. Every claim quoted and linked.</div>'
            f'<div class="row"><span class="pill">Quotes re-checked weekly</span><span class="foot">Free · open data · RSS change alerts</span></div>')


def app_card(a: dict) -> str:
    tr = a["answers"].get("teen_private", {})
    tone = "good" if tr.get("points") == 2 else "mid" if tr.get("points") else "unknown"
    return (f'<div class="top">{LOGO}Platform Defaults</div><h1>{E(a["name"])}: what\'s on by default for teens</h1>'
            f'<div class="sub">From {E(a["maker"])}\'s own documentation, quoted and linked. As of {E(a["as_of"])}.</div>'
            f'<div class="row"><span class="score">{a["score"]}<small> of {a["max"]}</small></span>'
            f'<span class="pill {tone}">Private by default: {E(tr.get("label") or "")}</span>'
            f'<span class="foot">defaults and controls documented</span></div>')


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    chrome = find_chrome()
    if not chrome:
        print("og: Chrome not found; keeping the default share cards")
        return 0
    if argv[:1] == ["--default"]:
        ok = render(chrome, home_card(6).replace("6 platforms", "Popular platforms"), os.path.join(ROOT, "site", "og-default.png"))
        print("og-default.png", "ok" if ok else "FAILED")
        return 0 if ok else 1
    dist = argv[0] if argv else os.path.join(ROOT, "dist")
    data = json.load(open(os.path.join(dist, "data", "platforms.json"), encoding="utf-8"))
    os.makedirs(os.path.join(dist, "og"), exist_ok=True)
    jobs = [("home", home_card(len(data["apps"])))] + [(a["slug"], app_card(a)) for a in data["apps"]]
    bad = 0
    for name, body in jobs:
        out = os.path.join(dist, "og", f"{name}.png")
        tmp = out + ".new.png"
        if render(chrome, body, tmp):
            os.replace(tmp, out)
        else:
            bad += 1
            if os.path.exists(tmp):
                os.remove(tmp)
            print(f"og: could not render {name}; the default card stays")
    print(f"og: rendered {len(jobs) - bad} of {len(jobs)} cards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
