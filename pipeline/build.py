"""Build the static site into dist/ from data/.

    python3 -m pipeline.build                       # dist/ for the default URL
    SITE_URL=https://example.org python3 -m pipeline.build

Settings (environment variables; in Actions they come from repository variables):
  SITE_URL         the public base URL, no trailing slash. The ONE setting that moves the site to a
                   custom domain: canonical URLs, sitemap, feed, share cards and badges follow it.
  SUPPORT_URL      optional money slot: a "Support this project" link (hidden when empty)
  SUPPORT_LABEL    optional label for that link
  GOATCOUNTER_URL  optional cookieless page counts (https://<code>.goatcounter.com/count)
  GITHUB_REPOSITORY  owner/name, used for the correction and source links

Internal links are relative, so the same build works under any path. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import shutil
import sys
from email.utils import format_datetime
from urllib.parse import quote as urlquote

from . import store as S
from . import textutil as T

ROOT = S.ROOT
DEFAULT_SITE_URL = "https://theguysaccount.github.io/supermind-killers-site"
DEFAULT_REPO = "theguysaccount/supermind-killers-site"
BRAND = "Platform Defaults"
TAGLINE = "How social apps are set up for teens by default, in each platform's own words."

E = lambda s: html.escape(str(s), quote=True)  # noqa: E731


# ---------------------------------------------------------------------------------------------
# Dates

def parse_day(s: str):
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def fmt_day(s: str) -> str:
    d = parse_day(s)
    return f"{d.day} {d.strftime('%b')} {d.year}" if d else ""


def tday(s: str) -> str:
    d = parse_day(s)
    return f'<time datetime="{d.isoformat()}">{fmt_day(s)}</time>' if d else ""


def capture_day(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if stamp and len(stamp) >= 8 else ""


# ---------------------------------------------------------------------------------------------
# The view model: everything a page needs, computed once from the data files.

class Ctx:
    def __init__(self, data: str, site_url: str, repo: str, now: dt.datetime, env: dict):
        self.data = data
        self.site = site_url.rstrip("/")
        self.repo = repo
        self.repo_url = f"https://github.com/{repo}"
        self.now = now
        self.support_url = env.get("SUPPORT_URL", "").strip()
        self.support_label = env.get("SUPPORT_LABEL", "").strip() or "Support this project"
        self.goatcounter = env.get("GOATCOUNTER_URL", "").strip()
        self.rubric = S.rubric(data)
        self.state = S.state(data)
        self.changes = S.changes(data)
        self.corrections = S._read(os.path.join(data, "corrections.json"), [])
        self.not_covered = S._read(os.path.join(data, "not_covered.json"), [])
        self.crit = {c["id"]: c for c in self.rubric["criteria"]}
        self.facts = {f["id"]: f["label"] for f in self.rubric.get("facts", [])}
        self.apps = [self.app_view(a) for a in sorted(S.apps(data), key=lambda a: a["name"].lower())]
        self.last_check = self.state.get("checked", "")
        self.total_quotes = sum(v["quote_count"] for v in self.apps)

    def url(self, path: str) -> str:
        return f"{self.site}/{path}"

    def doc_view(self, app: dict, doc_id: str) -> dict:
        doc = app["documents"][doc_id]
        st = self.state["docs"].get(f"{app['slug']}/{doc_id}", {})
        v = {"id": doc_id, "title": doc["title"], "url": doc["url"], "status": st.get("status", ""),
             "via": st.get("via", ""), "capture": capture_day(st.get("capture", "")),
             "archive_url": st.get("archive_url", ""), "last_ok": (st.get("last_ok") or "")[:10],
             "checked": (st.get("checked") or "")[:10], "error": st.get("error", ""),
             "changed": st.get("changed", "")}
        v["asof"] = v["last_ok"] or app["reviewed"]
        return v

    def app_view(self, app: dict) -> dict:
        slug = app["slug"]
        docs = {d: self.doc_view(app, d) for d in app["documents"]}
        used = set()
        quotes = []

        def ev_view(ev):
            used.add(ev["doc"])
            q = self.state["quotes"].get(S.quote_id(slug, ev["doc"], ev["quote"]), {})
            item = {"doc": docs[ev["doc"]], "quote": ev["quote"], "found": q.get("found", True),
                    "missing_since": q.get("missing_since", "")}
            quotes.append(item)
            return item

        answers = []
        for c in self.rubric["criteria"]:
            a = (app.get("answers") or {}).get(c["id"], {})
            opt = next((o for o in c["answers"] if o["id"] == a.get("answer")), None)
            best = max(o["points"] for o in c["answers"])
            answers.append({"crit": c, "answer": opt, "points": opt["points"] if opt else 0, "max": best,
                            "summary": a.get("summary", ""), "note": a.get("note", ""),
                            "evidence": [ev_view(e) for e in a.get("evidence", [])],
                            "question": c.get("page_question", c["question"]).format(app=app["name"], maker=app["maker"])})
        facts = []
        for fid, f in (app.get("facts") or {}).items():
            facts.append({"id": fid, "label": self.facts.get(fid, fid.title()), "summary": f.get("summary", ""),
                          "evidence": [ev_view(e) for e in f.get("evidence", [])]})
        opt = app.get("opt_out") or {}
        opt_view = {"summary": opt.get("summary", ""), "steps": opt.get("steps", []), "caveats": opt.get("caveats", []),
                    "evidence": [ev_view(e) for e in opt.get("evidence", [])]}
        pts, mx = S.score(app, self.rubric)
        used_docs = [docs[d] for d in app["documents"] if d in used]
        asof = min((d["asof"] for d in used_docs), default=app["reviewed"])
        events = [c for c in self.changes if c.get("app") == slug]
        since = [c for c in events if c.get("date", "") > app["reviewed"]]
        missing = [q for q in quotes if not q["found"]]
        unread = [d for d in used_docs if d["status"] and d["status"] != "ok"]
        return {"app": app, "slug": slug, "name": app["name"], "maker": app["maker"], "docs": docs,
                "used_docs": used_docs, "answers": answers, "facts": facts, "opt_out": opt_view,
                "points": pts, "max": mx, "asof": asof, "events": sorted(events, key=lambda c: c["date"], reverse=True),
                "changed_since_review": since, "missing": missing, "unread": unread,
                "quote_count": len(quotes), "training": answers[0] if answers else None}


# ---------------------------------------------------------------------------------------------
# HTML pieces

CSS_VERSION = "1"


def tone(points: int, mx: int, answer) -> str:
    if answer is None or answer["id"] in ("not_stated", "none", "undated", "not_documented"):
        return "unknown" if points == 0 else "mid"
    if mx and points == mx:
        return "good"
    return "mid" if points > 0 else "low"


def pill(av: dict) -> str:
    a = av["answer"]
    label = a["label"] if a else "Not reviewed"
    return (f'<span class="pill {tone(av["points"], av["max"], a)}">{E(label)}'
            f'<span class="pts"> · {av["points"]} of {av["max"]}</span></span>')


def meter(points: int, mx: int, label: str = "") -> str:
    pct = round(100 * points / mx) if mx else 0
    return (f'<span class="meter" role="img" aria-label="{E(label or f"{points} of {mx} points")}">'
            f'<span style="width:{pct}%"></span></span>')


def text_link(url: str, quote: str) -> str:
    return url + T.text_fragment(quote)


def how_read(d: dict) -> str:
    if d["via"] == "wayback" and d["capture"]:
        return (f'Internet Archive copy of {tday(d["capture"])} '
                f'(<a href="{E(d["archive_url"])}" rel="nofollow noopener">open the copy</a>; '
                f'the live page refuses automated readers)')
    if d["last_ok"]:
        return f"read {tday(d['last_ok'])}"
    return "quoted from the reviewed version"


def render_quote(q: dict) -> str:
    d = q["doc"]
    missing = "" if q["found"] else (
        f'<p class="missing" role="note">Not found word for word in the latest text'
        f'{" (since " + tday(q["missing_since"]) + ")" if q["missing_since"] else ""}. '
        f'This answer is waiting for re-review.</p>')
    return (f'<blockquote class="q{"" if q["found"] else " q-missing"}" cite="{E(d["url"])}">'
            f'<p>“{E(q["quote"])}”</p>{missing}'
            f'<footer><a class="src" href="{E(text_link(d["url"], q["quote"]))}" rel="nofollow noopener">{E(d["title"])}</a>'
            f' · <span class="how">{how_read(d)}</span></footer></blockquote>')


def head(ctx: Ctx, title: str, desc: str, path: str, depth: int, og: str, jsonld: list, noindex: bool = False) -> str:
    pre = "../" * depth
    canon = ctx.url(path)
    ld = "".join('<script type="application/ld+json">' + json.dumps(j, ensure_ascii=False).replace("</", "<\\/")
                 + "</script>" for j in jsonld)
    gc = (f'<script data-goatcounter="{E(ctx.goatcounter)}" async src="//gc.zgo.at/count.js"></script>'
          if ctx.goatcounter else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(canon)}">
{'<meta name="robots" content="noindex">' if noindex else ''}
<meta property="og:type" content="website">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{E(canon)}">
<meta property="og:image" content="{E(ctx.url(og))}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{pre}favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{BRAND}: documentation changes" href="{E(ctx.url('feed.xml'))}">
<link rel="stylesheet" href="{pre}assets/site.css?v={CSS_VERSION}">
{ld}{gc}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap">
<a class="brand" href="{pre or './'}"><svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect x="3" y="3" width="26" height="26" rx="7" fill="#1f5f8b"/><path d="M9 11h14M9 16h10M9 21h7" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><circle cx="23" cy="21" r="3" fill="#7fd1ae"/></svg>{BRAND}</a>
<nav aria-label="Main"><a href="{pre or './'}">Platforms</a><a href="{pre}rubric/">Rubric</a><a href="{pre}changes/">Changes</a><a href="{pre}about/">About</a></nav>
</div></header>
<main id="main" class="wrap">
"""


def foot(ctx: Ctx, depth: int) -> str:
    pre = "../" * depth
    support = (f'<a class="support" href="{E(ctx.support_url)}" rel="noopener">{E(ctx.support_label)}</a> · '
               if ctx.support_url else "")
    privacy = ("Page counts are cookieless (GoatCounter)." if ctx.goatcounter else "No cookies, no tracking.")
    return f"""</main>
<footer class="foot"><div class="wrap">
<p>{BRAND} reports what each platform's own documentation says about its default settings, with quotes and links. It does not test the apps and is not a safety rating.</p>
<p><a href="{ctx.repo_url}/issues/new/choose" rel="noopener">Report a correction</a> · <a href="{pre}feed.xml">Change feed (RSS)</a> · <a href="{pre}data/platforms.json">Open data</a> · <a href="{ctx.repo_url}" rel="noopener">Source code</a> · {support}{privacy}</p>
<p class="small">Page text CC BY 4.0. Quoted passages belong to their publishers. Built {tday(ctx.now.date().isoformat())}.</p>
</div></footer>
<pre id="selftest" hidden></pre>
<script src="{pre}assets/site.js?v={CSS_VERSION}" defer></script>
</body>
</html>
"""


def correction_url(ctx: Ctx, app: dict, what: str = "") -> str:
    title = f"Correction: {app['name']}" + (f" ({what})" if what else "")
    return (f"{ctx.repo_url}/issues/new?template=correction.yml&title={urlquote(title)}"
            f"&app={urlquote(app['slug'])}&page={urlquote(ctx.url('platforms/' + app['slug'] + '/'))}")


def reply_url(ctx: Ctx, app: dict) -> str:
    return (f"{ctx.repo_url}/issues/new?template=reply.yml&title={urlquote('Reply: ' + app['name'])}"
            f"&app={urlquote(app['slug'])}")


# ---------------------------------------------------------------------------------------------
# Pages

def flags_html(ctx: Ctx, v: dict, depth: int) -> str:
    out = []
    pre = "../" * depth
    if v["changed_since_review"]:
        docs = sorted({c["title"] for c in v["changed_since_review"]})
        newest = max(c["date"] for c in v["changed_since_review"])
        out.append(f'<p><strong>Documentation changed since this page was reviewed.</strong> '
                   f'{E(", ".join(docs))} changed (newest as of {tday(newest)}). The answers below describe the reviewed '
                   f'version; every quote is re-checked each week. <a href="{pre}changes/">See the change log</a>.</p>')
    if v["missing"]:
        out.append(f'<p><strong>{len(v["missing"])} quote{"s" if len(v["missing"]) != 1 else ""} no longer '
                   f'found word for word</strong> in the latest text. Those answers are marked below and are waiting '
                   f'for re-review.</p>')
    if v["unread"]:
        names = ", ".join(d["title"] for d in v["unread"])
        out.append(f'<p>The latest weekly check could not read: {E(names)}. The quotes shown are from the last good '
                   f'read, with its date.</p>')
    return f'<div class="flag" role="status">{"".join(out)}</div>' if out else ""


def card(ctx: Ctx, v: dict, pre: str) -> str:
    tr = v["training"]
    status = []
    if v["changed_since_review"]:
        status.append('<span class="chip warn">Documentation changed since review</span>')
    if v["missing"]:
        status.append('<span class="chip warn">Re-review pending</span>')
    return f"""<article class="card" data-training="{E(tr['answer']['id'] if tr and tr['answer'] else '')}">
<h3><a href="{pre}platforms/{v['slug']}/">{E(v['name'])}</a></h3>
<p class="maker">{E(v['maker'])} · {E(v['app'].get('kind', ''))}</p>
<p class="score"><strong>{v['points']}</strong> of {v['max']} {meter(v['points'], v['max'], f"{v['points']} of {v['max']} points")}</p><p class="small">defaults and controls documented</p>
<dl>{''.join(f'<dt>{E(a["crit"]["label"])}</dt><dd>{pill(a)}</dd>' for a in v["answers"][:4])}</dl>
<p class="asof">As of {tday(v['asof'])}{' · ' + ''.join(status) if status else ''}</p>
</article>"""


def page_home(ctx: Ctx) -> str:
    pre = ""
    cards = "\n".join(card(ctx, v, pre) for v in ctx.apps)
    crits = ctx.rubric["criteria"]
    rows = []
    for v in ctx.apps:
        cells = "".join(f'<td>{pill(a)}</td>' for a in v["answers"])
        rows.append(f'<tr><th scope="row"><a href="platforms/{v["slug"]}/">{E(v["name"])}</a></th>'
                    f'<td class="num">{v["points"]}/{v["max"]}</td>{cells}</tr>')
    heads = "".join(f'<th scope="col">{E(c["label"])}</th>' for c in crits)
    trains = {}
    for v in ctx.apps:
        a = v["training"]["answer"] if v["training"] else None
        trains.setdefault(a["id"] if a else "", []).append(v)
    filters = "".join(
        f'<button type="button" data-filter="{E(o["id"])}" aria-pressed="false">{E(o["label"])} ({len(trains.get(o["id"], []))})</button>'
        for o in ctx.rubric["criteria"][0]["answers"] if trains.get(o["id"]))
    nc = "".join(f'<li><a href="{E(n["url"])}" rel="nofollow noopener">{E(n["name"])}</a> ({E(n["maker"])}): {E(n["reason"])}</li>'
                 for n in ctx.not_covered)
    nc_html = (f'<section class="section"><h2>Not covered yet</h2><p>These platforms are popular but their documentation could '
               f'not be read in a way this project allows. Read it yourself at the links.</p><ul class="plain">{nc}</ul></section>'
               if nc else "")
    last = f" Last weekly check: {tday(ctx.last_check)}." if ctx.last_check else ""
    desc = ("How Instagram, TikTok, YouTube, Snapchat, Pinterest and X are set up for teens by default: private accounts, "
            "messages, time and bedtime reminders, sensitive content, parent tools and feed choices, quoted from each platform's own documentation.")
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": ctx.url(""), "description": desc},
          {"@context": "https://schema.org", "@type": "Dataset", "name": f"{BRAND} data", "description": desc,
           "url": ctx.url(""), "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
           "creator": {"@type": "Organization", "name": BRAND, "url": ctx.repo_url},
           "dateModified": (ctx.last_check or ctx.now.isoformat())[:10],
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                             "contentUrl": ctx.url("data/platforms.json")},
                            {"@type": "DataDownload", "encodingFormat": "application/rss+xml", "contentUrl": ctx.url("feed.xml")}]}]
    body = f"""<section class="hero">
<h1>How social apps are set up for teens, by default</h1>
<p class="lede">Seven questions for each platform, from private accounts to bedtime reminders and feed choices, answered with quotes from the platform's own help, safety and transparency pages. Every quote is re-checked word for word each week, and changes are logged.</p>
<p class="stats"><strong>{len(ctx.apps)}</strong> platforms · <strong>{ctx.total_quotes}</strong> quoted passages · counted on a <a href="rubric/">published rubric</a>.{last}</p>
<p><button type="button" class="share" data-share>Share this page</button></p>
</section>
<section class="section" aria-labelledby="h-cards">
<h2 id="h-cards">Platforms</h2>
<div class="filters" role="group" aria-label="Filter by the private-by-default answer"><button type="button" data-filter="" aria-pressed="true">All ({len(ctx.apps)})</button>{filters}</div>
<div class="cards" id="cards" data-count="{len(ctx.apps)}">
{cards}
</div>
</section>
<section class="section" aria-labelledby="h-matrix">
<h2 id="h-matrix">All answers side by side</h2>
<div class="scroll" tabindex="0" role="region" aria-label="Comparison table, scrolls sideways">
<table class="matrix"><thead><tr><th scope="col">Platform</th><th scope="col">Defaults</th>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div>
<p class="small">The count adds up the points in the <a href="rubric/">rubric</a>: what each platform's documentation says is on by default or available. It is not a safety rating and does not measure how well a setting works.</p>
</section>
{nc_html}
<section class="section"><h2>How it works</h2>
<ol class="how-list"><li><strong>Read the platform's own words.</strong> Help centers, safety centers and transparency pages, fetched politely and quoted exactly.</li>
<li><strong>Answer fixed questions.</strong> Seven questions, each answer defined in advance. <a href="rubric/">Read the rubric</a>.</li>
<li><strong>Watch for changes.</strong> A weekly job re-reads every document and flags changed text and missing quotes. <a href="changes/">Change log</a> · <a href="feed.xml">RSS</a>.</li></ol>
</section>"""
    return head(ctx, f"Social media default settings for teens, compared | {BRAND}", desc, "", 0, "og/home.png", ld) + body + foot(ctx, 0)


def page_app(ctx: Ctx, v: dict) -> str:
    app, depth = v["app"], 2
    pre = "../" * depth
    path = f"platforms/{v['slug']}/"
    name, maker = v["name"], v["maker"]
    quick = "".join(f'<tr><th scope="row"><a href="#{a["crit"]["id"]}">{E(a["crit"]["label"])}</a></th><td>{pill(a)}</td></tr>'
                    for a in v["answers"])
    sections = []
    for a in v["answers"]:
        ev = "".join(render_quote(q) for q in a["evidence"])
        note = f'<p class="note">{E(a["note"])}</p>' if a["note"] else ""
        defin = f'<p class="def">Rubric: “{E(a["answer"]["label"])}” means: {E(a["answer"]["definition"])}</p>' if a["answer"] else ""
        sections.append(f"""<section class="crit" id="{a['crit']['id']}">
<h2>{E(a['question'])}</h2>
<p>{pill(a)}</p>
<p>{E(a['summary'])}</p>{note}
{ev}
{defin}
<p class="small"><a href="{E(correction_url(ctx, app, a['crit']['label']))}" rel="noopener">Report a correction to this answer</a></p>
</section>""")
    o = v["opt_out"]
    steps = "".join(f"<li>{E(s)}</li>" for s in o["steps"])
    cav = "".join(f"<li>{E(c)}</li>" for c in o["caveats"])
    opt_html = "" if not o["summary"] else f"""<section class="crit optout" id="opt-out">
<h2>{E(ctx.rubric.get('opt_out_question', 'How do you opt out?').format(app=name, maker=maker))}</h2>
<p>{E(o['summary'])}</p>
<ol class="steps">{steps}</ol>
{f'<p><strong>Keep in mind:</strong></p><ul>{cav}</ul>' if cav else ''}
{''.join(render_quote(q) for q in o['evidence'])}
<p><button type="button" data-copy="#steps-text">Copy these steps</button></p>
<textarea id="steps-text" class="visually-hidden" readonly aria-hidden="true" tabindex="-1">{E(name + ': ' + o['summary'] + chr(10) + chr(10).join(f'{i + 1}. {s}' for i, s in enumerate(o['steps'])) + chr(10) + 'Source: ' + ctx.url(path))}</textarea>
</section>"""
    facts = "".join(f'<section class="fact"><h3>{E(f["label"])}</h3><p>{E(f["summary"])}</p>{"".join(render_quote(q) for q in f["evidence"])}</section>'
                    for f in v["facts"])
    docs_rows = []
    for d in v["docs"].values():
        status = ("read" if d["status"] == "ok" else
                  f"not read in the latest check: {E(d['error'])}" if d["status"] else "not checked yet")
        docs_rows.append(f'<tr><td><a href="{E(d["url"])}" rel="nofollow noopener">{E(d["title"])}</a></td>'
                         f'<td>{how_read(d)}</td><td>{status}</td><td>{tday(d["changed"]) or "none seen"}</td></tr>')
    ev_rows = "".join(
        f'<li>{tday(c["date"])}: <strong>{E(c["title"])}</strong> changed ({c["added"]} sentence{"s" if c["added"] != 1 else ""} added, '
        f'{c["removed"]} removed{", " + str(len(c.get("quotes_missing", []))) + " quote(s) no longer found" if c.get("quotes_missing") else ""}).</li>'
        for c in v["events"][:20])
    badge = ctx.url(f"embed/{v['slug']}.svg")
    alt = f"{name}: {v['points']} of {v['max']} teen defaults documented ({BRAND})"
    snippet = f'<a href="{ctx.url(path)}"><img src="{badge}" alt="{alt}" height="20"></a>'
    title = f"{name} teen settings: what's on by default | {BRAND}"
    tr = v["training"]
    desc = (f"{name}'s default settings for teens, from {maker}'s own documentation: {tr['summary'] if tr else ''} "
            f"{v['points']} of {v['max']} defaults and controls documented.")[:300]
    faq = [{"@type": "Question", "name": a["question"], "acceptedAnswer": {"@type": "Answer", "text": a["summary"]}}
           for a in v["answers"] if a["summary"]]
    if o["summary"] and ctx.rubric.get("opt_out_question"):
        faq.append({"@type": "Question", "name": ctx.rubric.get("opt_out_question", "").format(app=name, maker=maker),
                    "acceptedAnswer": {"@type": "Answer", "text": o["summary"] + " " + " ".join(o["steps"])}})
    modified = max([app["reviewed"]] + [c["date"] for c in v["events"]])
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": f"{name} default settings for teens",
           "description": desc, "datePublished": app["reviewed"], "dateModified": modified,
           "mainEntityOfPage": ctx.url(path), "image": ctx.url(f"og/{v['slug']}.png"),
           "author": {"@type": "Organization", "name": BRAND, "url": ctx.url("")},
           "publisher": {"@type": "Organization", "name": BRAND, "url": ctx.url("")},
           "about": {"@type": "SoftwareApplication", "name": name, "applicationCategory": app.get("kind", ""),
                     "publisher": {"@type": "Organization", "name": maker}}},
          {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq},
          {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
              {"@type": "ListItem", "position": 1, "name": "Platforms", "item": ctx.url("")},
              {"@type": "ListItem", "position": 2, "name": name, "item": ctx.url(path)}]}]
    body = f"""<nav class="crumbs" aria-label="Breadcrumb"><a href="{pre}">Platforms</a> › {E(name)}</nav>
<header class="apphead">
<h1>{E(name)}</h1>
<p class="lede">What {E(maker)}'s own documentation says about {E(name)}'s default settings for teens and its feed. {E(app.get('scope', ''))}</p>
</header>
{flags_html(ctx, v, depth)}
<section class="scorebox" aria-label="Score">
<p class="big"><strong>{v['points']}</strong><span> of {v['max']}</span></p>
<p class="small">defaults and controls found in {E(maker)}'s documentation, counted on the <a href="{pre}rubric/">rubric</a></p>
{meter(v['points'], v['max'], f"{v['points']} of {v['max']} points")}
<p class="asof">As of {tday(v['asof'])}: the oldest date on which the quoted text was confirmed. Reviewed {tday(app['reviewed'])}; re-checked weekly{', last on ' + tday(ctx.last_check) if ctx.last_check else ''}.</p>
<p><button type="button" class="share" data-share>Share</button></p>
</section>
<section class="section"><h2 class="visually-hidden">Answers at a glance</h2>
<table class="quick"><tbody>{quick}</tbody></table></section>
{opt_html}
{''.join(sections)}
{f'<section class="section"><h2>Other facts from the documents</h2>{facts}</section>' if facts else ''}
<section class="section" id="documents"><h2>Documents read</h2>
<div class="scroll" tabindex="0" role="region" aria-label="Documents, scrolls sideways"><table class="docs"><thead><tr><th scope="col">Document</th><th scope="col">How it was read</th><th scope="col">Latest check</th><th scope="col">Last change seen</th></tr></thead>
<tbody>{''.join(docs_rows)}</tbody></table></div>
</section>
<section class="section" id="changes"><h2>Change history</h2>
{f'<ul>{ev_rows}</ul>' if ev_rows else '<p>No change to these documents has been detected since monitoring began.</p>'}
<p class="small">Page first published {tday(app['reviewed'])}. <a href="{pre}changes/">All changes</a> · <a href="{pre}feed.xml">RSS</a></p>
</section>
<section class="section" id="embed"><h2>Embed this summary</h2>
<p><img src="{pre}embed/{v['slug']}.svg" alt="{E(alt)}" height="20"></p>
<label for="embed-code">HTML</label>
<textarea id="embed-code" readonly rows="3">{E(snippet)}</textarea>
<p><button type="button" data-copy="#embed-code">Copy embed code</button></p>
</section>
<section class="section corr"><h2>Something wrong?</h2>
<p>Every answer should match {E(maker)}'s own documentation. If one doesn't, <a class="correction" href="{E(correction_url(ctx, app))}" rel="noopener">report a correction</a> with a link to the passage. If you represent {E(maker)}, you can publish a <a href="{E(reply_url(ctx, app))}" rel="noopener">right of reply</a>.</p>
<p class="small">This page reports what the platform's documentation says. It does not test the product, it is not a safety rating, and it says nothing about any person.</p>
</section>"""
    return head(ctx, title, desc, path, depth, f"og/{v['slug']}.png", ld) + body + foot(ctx, depth)


def page_rubric(ctx: Ctx) -> str:
    depth, pre = 1, "../"
    parts = []
    for c in ctx.rubric["criteria"]:
        rows = "".join(f'<tr><td><span class="pill {tone(o["points"], max(x["points"] for x in c["answers"]), o)}">{E(o["label"])}</span></td>'
                       f'<td class="num">{o["points"]}</td><td>{E(o["definition"])}</td></tr>' for o in c["answers"])
        parts.append(f"""<section class="crit" id="{c['id']}"><h2>{E(c['label'])}</h2>
<p><strong>{E(c['question'])}</strong> {E(c['why'])}</p>
<div class="scroll" tabindex="0" role="region" aria-label="{E(c['label'])} answers"><table class="rub"><thead><tr><th scope="col">Answer</th><th scope="col">Points</th><th scope="col">When it applies</th></tr></thead><tbody>{rows}</tbody></table></div></section>""")
    mx = sum(max(o["points"] for o in c["answers"]) for c in ctx.rubric["criteria"])
    desc = "The published rubric behind Platform Defaults: seven questions about social platforms' default settings for teens and feed choices, every answer defined in advance, and how documents are read and re-checked."
    body = f"""<h1>The rubric</h1>
<p class="lede">Version {E(ctx.rubric['version'])}, published {tday(ctx.rubric['published'])}. Seven questions, {mx} points in all. Every answer is defined before any platform is reviewed, and every answer cites the passage it rests on.</p>
<section class="section"><h2>Scope</h2><p>{E(ctx.rubric['scope'])}</p></section>
<section class="section"><h2>How documents are read</h2>
<ul><li>Each platform page lists the documents it quotes: help-center articles, safety and parent centers, transparency pages and the platform's own announcements.</li>
<li>A reader identifies itself with a link to this project, follows each site's robots.txt, and waits between requests.</li>
<li>When a platform's site refuses automated readers, the reader uses the newest copy saved by the Internet Archive's Wayback Machine, if one is less than 180 days old, and the page says so with the capture date. It never disguises itself as a browser.</li>
<li>Quotes must appear word for word in the document's text. Typographic quotes, dashes and spacing are treated as equal; nothing else is.</li></ul></section>
<section class="section"><h2>How changes are detected</h2>
<ul><li>Every week each document is read again and split into sentences. Sentences that appear or disappear are counted, and a few new ones are kept as excerpts on the <a href="{pre}changes/">change log</a>.</li>
<li>Every quote is looked up again. A quote that is no longer found is marked on its page, and the answer waits for re-review.</li>
<li>A page that cannot be read keeps its last good version, with that version's date.</li></ul></section>
{''.join(parts)}
<section class="section"><h2>Not scored</h2>
<p>How each feed ranks content, autoplay defaults and minimum ages are listed as facts on each page where the platform documents them, because platforms document them unevenly. Infinite scrolling is not listed because none of the documents read describes it as a setting.</p></section>
<section class="section"><h2>What the count is not</h2>
<p>The count adds up what the documentation says under this rubric. It does not measure how well a setting works, whether it is enforced, or whether an app suits a particular child. It describes products, never people. Facts and quotes only.</p></section>"""
    return head(ctx, f"The rubric | {BRAND}", desc, "rubric/", depth, "og/home.png", []) + body + foot(ctx, depth)


def events_list(ctx: Ctx, pre: str) -> list:
    """Every dated event shown on the change log and in the feed, newest first."""
    names = {v["slug"]: v["name"] for v in ctx.apps}
    out = []
    for c in ctx.changes:
        if c.get("app") not in names:
            continue
        miss = c.get("quotes_missing") or []
        exc = "".join(f"<li>{E(x)}</li>" for x in c.get("excerpts", []))
        via = (f' Read from the Internet Archive copy of {fmt_day(capture_day(c.get("capture", "")))}.'
               if c.get("via") == "wayback" else "")
        html_body = (f'<p><a href="{E(c["url"])}" rel="nofollow noopener">{E(c["title"])}</a>: {c["added"]} sentence'
                     f'{"s" if c["added"] != 1 else ""} added, {c["removed"]} removed.{via}'
                     f'{" " + str(len(miss)) + " quoted passage(s) no longer found; the page is waiting for re-review." if miss else ""}</p>'
                     + (f'<p>New text includes:</p><ul class="excerpts">{exc}</ul>' if exc else ""))
        out.append({"date": c["date"], "id": c["id"], "kind": "change", "app": c["app"],
                    "title": f"{names[c['app']]}: “{c['title']}” changed",
                    "link": f"platforms/{c['app']}/#changes", "html": html_body})
    for v in ctx.apps:
        out.append({"date": v["app"]["reviewed"], "id": f"published-{v['slug']}-{v['app']['reviewed']}", "kind": "published",
                    "app": v["slug"], "title": f"Page published: {v['name']}", "link": f"platforms/{v['slug']}/",
                    "html": f"<p>{E(v['name'])} ({E(v['maker'])}): {v['points']} of {v['max']} defaults and controls documented, "
                            f"with {v['quote_count']} quoted passages.</p>"})
    for k in ctx.corrections:
        out.append({"date": k["date"], "id": f"correction-{k['date']}-{k.get('app', '')}", "kind": "correction",
                    "app": k.get("app", ""), "title": f"Correction: {names.get(k.get('app'), k.get('app', ''))}",
                    "link": f"platforms/{k.get('app', '')}/", "html": f"<p>{E(k.get('text', ''))}</p>"})
    return sorted(out, key=lambda e: (e["date"], e["id"]), reverse=True)


def page_changes(ctx: Ctx) -> str:
    depth, pre = 1, "../"
    evs = events_list(ctx, pre)
    items = "".join(f'<li class="ev ev-{e["kind"]}"><p class="when">{tday(e["date"])}</p><h2><a href="{pre}{E(e["link"])}">{E(e["title"])}</a></h2>{e["html"]}</li>'
                    for e in evs)
    desc = "Every detected change to the help, safety and transparency pages behind Platform Defaults, with dates and excerpts. Also as an RSS feed."
    body = f"""<h1>Change log</h1>
<p class="lede">Each week every document is read again. Changed text, quotes that no longer appear, newly published pages and corrections are listed here, newest first. <a href="{pre}feed.xml">Subscribe by RSS</a>.</p>
<p class="small">{'Last weekly check: ' + tday(ctx.last_check) + '.' if ctx.last_check else ''} A change is dated by the version of the document that showed it.</p>
<ol class="events">{items}</ol>"""
    return head(ctx, f"Documentation change log | {BRAND}", desc, "changes/", depth, "og/home.png", []) + body + foot(ctx, depth)


def page_about(ctx: Ctx) -> str:
    depth, pre = 1, "../"
    support = (f'<p><a href="{E(ctx.support_url)}" rel="noopener">{E(ctx.support_label)}</a>.</p>' if ctx.support_url else
               "<p>It is free to use and carries no advertising.</p>")
    desc = "Who runs Platform Defaults, how it stays independent, how corrections and right of reply work, and what this site collects about you."
    body = f"""<h1>About</h1>
<p class="lede">{BRAND} is an open, automated project for parents, researchers and journalists. It reads what social platforms publish about their default settings and feeds, quotes it, answers <a href="{pre}rubric/">fixed questions</a> and watches the documents for changes.</p>
<section class="section"><h2>Facts and quotes, not accusations</h2>
<p>Every answer rests on a passage from the platform's own documentation, linked to its source. Summaries say what a platform says ("Instagram says…"), not what it does. The project describes product design only: it profiles no executives or other individuals, does not test the apps, and gives no medical, legal or safety advice.</p></section>
<section class="section"><h2>Independence</h2>
<p>The project is not affiliated with, paid by or endorsed by any platform it covers. Its code, data and full history are public at <a href="{ctx.repo_url}" rel="noopener">{E(ctx.repo)}</a>.</p></section>
<section class="section" id="corrections"><h2>Corrections and right of reply</h2>
<p>Corrections are public GitHub issues: <a href="{ctx.repo_url}/issues/new?template=correction.yml" rel="noopener">report one</a> with a link to the passage. Each report is checked against the platform's document before anything changes, and accepted corrections appear on the <a href="{pre}changes/">change log</a>. Platforms can publish a response with the <a href="{ctx.repo_url}/issues/new?template=reply.yml" rel="noopener">right-of-reply form</a>; responses are linked as filed.</p></section>
<section class="section"><h2>Open data</h2>
<p>All platform pages, quotes and check results are in <a href="{pre}data/platforms.json">platforms.json</a> (CC BY 4.0). Changes are in the <a href="{pre}feed.xml">RSS feed</a>.</p></section>
<section class="section"><h2>This site's own privacy</h2>
<p>{'Page counts are collected without cookies by GoatCounter; no personal data is stored.' if ctx.goatcounter else 'This site sets no cookies and runs no tracking or analytics.'} It is hosted on GitHub Pages, which keeps standard server logs.</p></section>
<section class="section"><h2>Funding</h2>{support}</section>"""
    return head(ctx, f"About | {BRAND}", desc, "about/", depth, "og/home.png", []) + body + foot(ctx, depth)


def page_404(ctx: Ctx) -> str:
    # Served from any path, so links here are absolute.
    body = f"""<h1>Page not found</h1><p>That page does not exist. <a href="{E(ctx.url(''))}">See all platforms</a>.</p>"""
    h = head(ctx, f"Not found | {BRAND}", "Page not found.", "404.html", 0, "og/home.png", [], noindex=True)
    h = h.replace('href="assets/', f'href="{E(ctx.url("assets/"))}').replace('href="favicon.svg"', f'href="{E(ctx.url("favicon.svg"))}"')
    h = h.replace('href="./"', f'href="{E(ctx.url(""))}"').replace('href="rubric/"', f'href="{E(ctx.url("rubric/"))}"')
    h = h.replace('href="changes/"', f'href="{E(ctx.url("changes/"))}"').replace('href="about/"', f'href="{E(ctx.url("about/"))}"')
    f = foot(ctx, 0).replace('src="assets/', f'src="{E(ctx.url("assets/"))}').replace('href="feed.xml"', f'href="{E(ctx.url("feed.xml"))}"')
    f = f.replace('href="data/', f'href="{E(ctx.url("data/"))}')
    return h + body + f


# ---------------------------------------------------------------------------------------------
# Feeds, data, badges, sitemap

def feed_xml(ctx: Ctx) -> str:
    items = []
    for e in events_list(ctx, "")[:100]:
        d = parse_day(e["date"]) or ctx.now.date()
        pub = format_datetime(dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone.utc))
        items.append(f"<item><title>{E(e['title'])}</title><link>{E(ctx.url(e['link']))}</link>"
                     f"<guid isPermaLink=\"false\">{E(e['id'])}</guid><pubDate>{pub}</pubDate>"
                     f"<description>{E(e['html'])}</description></item>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>
<title>{BRAND}: documentation changes</title><link>{E(ctx.url('changes/'))}</link>
<description>Changes to social platforms' help, safety and transparency pages about default settings, detected weekly, plus new pages and corrections.</description>
<language>en</language><lastBuildDate>{format_datetime(ctx.now)}</lastBuildDate>
<atom:link href="{E(ctx.url('feed.xml'))}" rel="self" type="application/rss+xml"/>
{''.join(items)}
</channel></rss>
"""


def open_data(ctx: Ctx) -> dict:
    apps = []
    for v in ctx.apps:
        apps.append({
            "slug": v["slug"], "name": v["name"], "maker": v["maker"], "kind": v["app"].get("kind", ""),
            "scope": v["app"].get("scope", ""), "reviewed": v["app"]["reviewed"], "as_of": v["asof"],
            "url": ctx.url(f"platforms/{v['slug']}/"), "score": v["points"], "max": v["max"],
            "flags": {"changed_since_review": bool(v["changed_since_review"]), "quotes_missing": len(v["missing"]),
                      "documents_unread": len(v["unread"])},
            "answers": {a["crit"]["id"]: {"answer": a["answer"]["id"] if a["answer"] else None,
                                          "label": a["answer"]["label"] if a["answer"] else None,
                                          "points": a["points"], "summary": a["summary"],
                                          "evidence": [{"document": q["doc"]["id"], "quote": q["quote"], "found": q["found"]}
                                                       for q in a["evidence"]]} for a in v["answers"]},
            "documents": {d["id"]: {"title": d["title"], "url": d["url"], "read_via": d["via"] or None,
                                    "archive_copy": d["capture"] or None, "last_confirmed": d["last_ok"] or None,
                                    "status": d["status"] or None} for d in v["docs"].values()},
        })
    return {"name": BRAND, "url": ctx.url(""), "license": "CC BY 4.0 (page text); quotes belong to their publishers",
            "rubric_version": ctx.rubric["version"], "built": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "checked": ctx.last_check or None, "apps": apps}


def badge_svg(label: str, value: str, color: str) -> str:
    w1 = 10 + int(len(label) * 6.4)
    w2 = 10 + int(len(value) * 6.6)
    w = w1 + w2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{E(label)}: {E(value)}">
<title>{E(label)}: {E(value)}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{w1}" height="20" fill="#3b4a57"/><rect x="{w1}" width="{w2}" height="20" fill="{color}"/><rect width="{w}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{w1 / 2:.1f}" y="14">{E(label)}</text><text x="{w1 + w2 / 2:.1f}" y="14">{E(value)}</text></g>
</svg>
"""


def sitemap(ctx: Ctx, pages: list) -> str:
    urls = "".join(f"<url><loc>{E(ctx.url(p))}</loc><lastmod>{m}</lastmod></url>" for p, m in pages)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


# ---------------------------------------------------------------------------------------------

def write(out: str, rel: str, text: str) -> None:
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(out: str, *, data: str = S.DATA, site_url: str = "", repo: str = "", now: dt.datetime = None,
          env: dict = None) -> Ctx:
    env = dict(os.environ if env is None else env)
    site_url = (site_url or env.get("SITE_URL") or DEFAULT_SITE_URL).rstrip("/")
    repo = repo or env.get("GITHUB_REPOSITORY") or DEFAULT_REPO
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ctx = Ctx(data, site_url, repo, now, env)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    static = os.path.join(ROOT, "site")
    for name in os.listdir(static):
        src = os.path.join(static, name)
        if name == "indexnow-key.txt":
            with open(src, encoding="utf-8") as f:
                key = f.read().strip()
            write(out, f"{key}.txt", key + "\n")
        elif os.path.isdir(src):
            shutil.copytree(src, os.path.join(out, name))
        elif not name.startswith(".") and name != "og-default.png":
            shutil.copy2(src, os.path.join(out, name))
    pages = [("", max([v["app"]["reviewed"] for v in ctx.apps] + [c["date"] for c in ctx.changes] or [ctx.rubric["published"]]))]
    write(out, "index.html", page_home(ctx))
    og_default = os.path.join(static, "og-default.png")
    os.makedirs(os.path.join(out, "og"), exist_ok=True)
    for v in ctx.apps:
        write(out, f"platforms/{v['slug']}/index.html", page_app(ctx, v))
        pages.append((f"platforms/{v['slug']}/", max([v["app"]["reviewed"]] + [c["date"] for c in v["events"]])))
        color = {"good": "#2f7d5b", "mid": "#a46a12", "low": "#8a3b3b", "unknown": "#5b6770"}[
            "good" if v["points"] >= 0.75 * v["max"] else "mid" if v["points"] >= 0.4 * v["max"] else "low"]
        write(out, f"embed/{v['slug']}.svg", badge_svg(BRAND, f"{v['name']} {v['points']}/{v['max']}", color))
        if os.path.exists(og_default):
            shutil.copy2(og_default, os.path.join(out, "og", f"{v['slug']}.png"))
    if os.path.exists(og_default):
        shutil.copy2(og_default, os.path.join(out, "og", "home.png"))
    write(out, "rubric/index.html", page_rubric(ctx))
    pages.append(("rubric/", ctx.rubric["published"]))
    write(out, "changes/index.html", page_changes(ctx))
    pages.append(("changes/", max([e["date"] for e in events_list(ctx, "")] or [ctx.rubric["published"]])))
    write(out, "about/index.html", page_about(ctx))
    pages.append(("about/", ctx.rubric["published"]))
    write(out, "404.html", page_404(ctx))
    write(out, "feed.xml", feed_xml(ctx))
    write(out, "data/platforms.json", json.dumps(open_data(ctx), ensure_ascii=False, indent=1) + "\n")
    write(out, "sitemap.xml", sitemap(ctx, pages))
    write(out, "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {ctx.url('sitemap.xml')}\n")
    write(out, "urls.txt", "\n".join(ctx.url(p) for p, _ in pages) + "\n")
    write(out, ".nojekyll", "")
    return ctx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--data", default=S.DATA)
    args = ap.parse_args(argv)
    ctx = build(args.out, data=args.data)
    print(f"built {len(ctx.apps)} platform pages into {args.out} for {ctx.site}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
