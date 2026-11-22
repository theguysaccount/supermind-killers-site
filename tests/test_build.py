"""Build the site from the real data and from fixture states, and check what visitors and crawlers rely on.

Expected values come from the data itself, never from launch-day numbers or dates.
"""
import datetime as dt
import html
import json
import os
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from pipeline import build as B
from pipeline import store as S

SITE = "https://theguysaccount.github.io/supermind-killers-site"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Built:
    def __init__(self, data=S.DATA, env=None, site=SITE):
        self.out = tempfile.mkdtemp()
        self.ctx = B.build(self.out, data=data, site_url=site, env=env or {})

    def page(self, rel):
        return read(os.path.join(self.out, rel))

    def close(self):
        shutil.rmtree(self.out)


class RealDataBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = Built()
        cls.apps = S.apps()

    @classmethod
    def tearDownClass(cls):
        cls.b.close()

    def test_every_page_exists(self):
        for rel in ["index.html", "rubric/index.html", "changes/index.html", "about/index.html", "404.html",
                    "feed.xml", "sitemap.xml", "robots.txt", "data/platforms.json", "favicon.svg",
                    "assets/site.css", "assets/site.js", "og/home.png"]:
            self.assertTrue(os.path.exists(os.path.join(self.b.out, rel)), rel)
        key = read(os.path.join(B.ROOT, "site", "indexnow-key.txt")).strip()
        self.assertEqual(self.b.page(f"{key}.txt").strip(), key)
        for app in self.apps:
            for rel in [f"platforms/{app['slug']}/index.html", f"embed/{app['slug']}.svg", f"og/{app['slug']}.png"]:
                self.assertTrue(os.path.exists(os.path.join(self.b.out, rel)), rel)

    def test_canonicals_and_sitemap_agree(self):
        locs = [el.text for el in ET.fromstring(self.b.page("sitemap.xml")).iter() if el.tag.endswith("loc")]
        self.assertEqual(len(locs), 4 + len(self.apps))
        for loc in locs:
            self.assertTrue(loc.startswith(SITE + "/"))
            rel = loc[len(SITE) + 1:] + "index.html"
            canon = re.search(r'<link rel="canonical" href="([^"]+)"', self.b.page(rel)).group(1)
            self.assertEqual(canon, loc)
        self.assertIn(f"Sitemap: {SITE}/sitemap.xml", self.b.page("robots.txt"))
        self.assertEqual(self.b.page("urls.txt").split(), locs)

    def test_internal_links_resolve(self):
        base = "http://local/"
        for root, _dirs, files in os.walk(self.b.out):
            for name in files:
                if not name.endswith(".html") or name == "404.html":
                    continue
                rel = os.path.relpath(os.path.join(root, name), self.b.out).replace(os.sep, "/")
                page_url = urljoin(base, rel)
                for href in re.findall(r'(?:href|src)="([^"#]+)', read(os.path.join(root, name))):
                    href = html.unescape(href)
                    if re.match(r"^(https?:|mailto:|//)", href):
                        continue
                    target = urlsplit(urljoin(page_url, href)).path.lstrip("/")
                    if target == "" or target.endswith("/"):
                        target += "index.html"
                    self.assertTrue(os.path.exists(os.path.join(self.b.out, target)), f"{rel} -> {href}")

    def test_scorecard_pages(self):
        rubric = S.rubric()
        for app in self.apps:
            with self.subTest(app=app["slug"]):
                p = self.b.page(f"platforms/{app['slug']}/index.html")
                self.assertIn(html.escape(app["name"]), p)
                self.assertIn('class="correction"', p)
                self.assertIn("issues/new?template=correction.yml", p)
                self.assertIn('class="asof"', p)
                for _where, _cid, ev in S.evidence(app):
                    self.assertIn(html.escape(ev["quote"]), p)                          # every quote is shown
                    self.assertIn(html.escape(app["documents"][ev["doc"]]["url"]), p)  # with its source
                pts, mx = S.score(app, rubric)
                self.assertIn(f"<strong>{pts}</strong><span> of {mx}</span>", p)
                for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', p, re.S):
                    json.loads(block)

    def test_home_lists_every_scorecard(self):
        p = self.b.page("index.html")
        self.assertIn(f'data-count="{len(self.apps)}"', p)
        self.assertEqual(p.count('<article class="card"'), len(self.apps))
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', p, re.S):
            json.loads(block)

    def test_feed_and_open_data(self):
        root = ET.fromstring(self.b.page("feed.xml"))
        items = root.findall("./channel/item")
        self.assertGreaterEqual(len(items), len(self.apps))  # at least one "published" item per scorecard
        guids = [i.findtext("guid") for i in items]
        self.assertEqual(len(guids), len(set(guids)))
        data = json.loads(self.b.page("data/platforms.json"))
        self.assertEqual(sorted(a["slug"] for a in data["apps"]), sorted(a["slug"] for a in self.apps))
        for a in data["apps"]:
            self.assertTrue(a["as_of"] and a["url"].startswith(SITE))

    def test_badges_are_svg(self):
        for app in self.apps:
            ET.fromstring(self.b.page(f"embed/{app['slug']}.svg"))


class StateDependentBuild(unittest.TestCase):
    """The same build with temporary check results: unread documents, missing quotes, detected changes."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        shutil.copytree(os.path.join(S.DATA, "platforms"), os.path.join(self.data, "platforms"))
        for name in ("rubric.json", "not_covered.json"):
            shutil.copy(os.path.join(S.DATA, name), self.data)
        self.app = S.apps(self.data)[0]

    def tearDown(self):
        shutil.rmtree(self.data)

    def test_no_check_results_yet(self):
        b = Built(self.data)
        try:
            p = b.page(f"platforms/{self.app['slug']}/index.html")
            self.assertIn("quoted from the reviewed version", p)
            self.assertNotIn('class="flag"', p)
        finally:
            b.close()

    def test_flags_for_changes_missing_quotes_and_unread_documents(self):
        slug = self.app["slug"]
        doc_ids = list(self.app["documents"])
        _w, _c, ev = next(S.evidence(self.app))
        later = (dt.date.fromisoformat(self.app["reviewed"]) + dt.timedelta(days=7)).isoformat()
        state = {"checked": later + "T07:30:00Z", "docs": {}, "quotes": {
            S.quote_id(slug, ev["doc"], ev["quote"]): {"found": False, "missing_since": later, "app": slug, "doc": ev["doc"]}}}
        for d in doc_ids:
            state["docs"][f"{slug}/{d}"] = {"status": "ok", "via": "direct", "last_ok": later + "T07:30:00Z",
                                            "checked": later + "T07:30:00Z"}
        state["docs"][f"{slug}/{doc_ids[-1]}"] = {"status": "unreachable", "error": "HTTP 503",
                                                   "checked": later + "T07:30:00Z", "last_ok": self.app["reviewed"] + "T00:00:00Z"}
        changes = [{"id": f"{later}-{slug}-{ev['doc']}", "date": later, "detected": later, "app": slug, "doc": ev["doc"],
                    "title": self.app["documents"][ev["doc"]]["title"], "url": self.app["documents"][ev["doc"]]["url"],
                    "via": "direct", "capture": "", "archive_url": "", "added": 3, "removed": 1,
                    "excerpts": ["A new sentence about <retention> & deletion."],
                    "quotes_missing": [{"criterion": "x", "quote": ev["quote"]}], "quotes_checked": 4}]
        S.save_state(state, self.data)
        S.save_changes(changes, self.data)
        b = Built(self.data)
        try:
            p = b.page(f"platforms/{slug}/index.html")
            self.assertIn("Documentation changed since this page was reviewed", p)
            self.assertIn("no longer ", p)
            self.assertIn("q-missing", p)
            self.assertIn("could not read", p)
            ch = b.page("changes/index.html")
            self.assertIn("A new sentence about &lt;retention&gt; &amp; deletion.", ch)  # excerpts are escaped
            items = ET.fromstring(b.page("feed.xml")).findall("./channel/item")
            self.assertTrue(any(i.findtext("guid") == changes[0]["id"] for i in items))
            data = json.loads(b.page("data/platforms.json"))
            mine = next(a for a in data["apps"] if a["slug"] == slug)
            self.assertTrue(mine["flags"]["changed_since_review"])
            self.assertEqual(mine["flags"]["quotes_missing"], 1)
        finally:
            b.close()


class Settings(unittest.TestCase):
    def test_custom_domain_is_one_setting(self):
        b = Built(env={"SITE_URL": "https://scorecard.example.org"}, site="")
        try:
            for rel in ["index.html", "rubric/index.html", f"platforms/{S.apps()[0]['slug']}/index.html"]:
                p = b.page(rel)
                canon = re.search(r'<link rel="canonical" href="([^"]+)"', p).group(1)
                self.assertTrue(canon.startswith("https://scorecard.example.org/"), canon)
                self.assertNotIn("theguysaccount.github.io/supermind", re.search(r'og:image" content="([^"]+)"', p).group(1))
            self.assertIn("Sitemap: https://scorecard.example.org/sitemap.xml", b.page("robots.txt"))
            self.assertNotIn("github.io", b.page("sitemap.xml"))
        finally:
            b.close()

    def test_money_and_analytics_slots_are_off_until_set(self):
        off = Built()
        on = Built(env={"SUPPORT_URL": "https://example.org/support", "GOATCOUNTER_URL": "https://x.goatcounter.com/count"})
        try:
            self.assertNotIn("example.org/support", off.page("index.html"))
            self.assertNotIn("goatcounter", off.page("index.html"))
            self.assertIn("No cookies, no tracking.", off.page("index.html"))
            self.assertIn('href="https://example.org/support"', on.page("index.html"))
            self.assertIn("gc.zgo.at/count.js", on.page("index.html"))
        finally:
            off.close()
            on.close()


if __name__ == "__main__":
    unittest.main()
