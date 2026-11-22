"""The weekly check, run against fake pages: first read, change, missing quote, unreadable page, re-run."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from pipeline import check as C
from pipeline import fetch as F
from pipeline import store as S

POLICY_V1 = """<html><body><nav>Menu</nav><main><h1>Example Privacy Policy</h1>
<p>Effective January 1, 2026.</p>
<p>We may use your conversations to train our models unless you turn off the training setting.</p>
<p>You can delete a conversation at any time, and it is removed from our systems within 30 days.</p>
<p>We do not sell personal information to anyone, and we do not show advertising in the app.</p>
<p>{filler}</p></main></body></html>"""
FILLER = " ".join(f"This sentence number {i} explains a routine part of how the example service works." for i in range(14))


def page(**changes):
    html = POLICY_V1.format(filler=FILLER)
    for old, new in changes.items():
        html = html.replace(old.replace("_", " "), new)
    return html


APP = {
    "slug": "example", "name": "Example Chat", "maker": "Example Inc", "kind": "Chat assistant", "scope": "Test.",
    "reviewed": "2026-01-01",
    "documents": {"privacy": {"title": "Example Privacy Policy", "url": "https://example.test/privacy"}},
    "answers": {"training": {"answer": "on_with_setting", "summary": "Example Inc says...", "evidence": [
        {"doc": "privacy", "quote": "We may use your conversations to train our models unless you turn off the training setting."}]},
        "deletion": {"answer": "self_serve_timed", "summary": "Example Inc says...", "evidence": [
            {"doc": "privacy", "quote": "it is removed from our systems within 30 days"}]}},
    "opt_out": {"summary": "Turn it off.", "steps": ["Turn it off."], "evidence": []},
}


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.data, "platforms"))
        with open(os.path.join(self.data, "platforms", "example.json"), "w") as f:
            json.dump(APP, f)
        self.html = page()
        self.status = 200

    def tearDown(self):
        shutil.rmtree(self.data)

    def fake_fetch(self, url, **kw):
        if self.status != 200:
            return F.Result(url=url, status=self.status, error=f"HTTP {self.status}")
        return F.Result(url=url, status=200, final_url=url, body=self.html.encode())

    def run_check(self):
        with mock.patch.object(F, "fetch", self.fake_fetch):
            C.main(["--data", self.data, "--events-out", os.path.join(self.data, "ev.json")])
        with open(os.path.join(self.data, "ev.json")) as f:
            return json.load(f)

    def test_first_read_records_and_finds_quotes(self):
        self.assertEqual(self.run_check(), [])  # nothing to compare with yet
        st = S.state(self.data)
        doc = st["docs"]["example/privacy"]
        self.assertEqual(doc["status"], "ok")
        self.assertTrue(doc["last_ok"])
        self.assertTrue(all(q["found"] for q in st["quotes"].values()))
        self.assertEqual(len(st["quotes"]), 2)
        self.assertTrue(S.load_sig("example", "privacy", self.data))

    def test_changed_text_and_missing_quote(self):
        self.run_check()
        self.html = page(within_30_days="within 90 days")
        self.html = self.html.replace("<p>{}</p>".format(FILLER), "<p>" + FILLER + "</p><p>We now keep backups of deleted conversations for one year.</p>")
        events = self.run_check()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["app"], "example")
        self.assertEqual(ev["added"], 2)       # the edited sentence and the new one
        self.assertEqual(ev["removed"], 1)
        self.assertEqual(len(ev["quotes_missing"]), 1)
        self.assertIn("within 30 days", ev["quotes_missing"][0]["quote"])
        st = S.state(self.data)
        missing = [q for q in st["quotes"].values() if not q["found"]]
        self.assertEqual(len(missing), 1)
        self.assertTrue(missing[0]["missing_since"])
        # Running again on the same text adds nothing: the change log has one entry per document version.
        self.assertEqual(self.run_check(), [])
        self.assertEqual(len(S.changes(self.data)), 1)

    def test_quote_comes_back(self):
        self.run_check()
        self.html = page(within_30_days="within 90 days")
        self.run_check()
        self.html = page()
        self.run_check()
        st = S.state(self.data)
        self.assertTrue(all(q["found"] for q in st["quotes"].values()))
        self.assertFalse(any("missing_since" in q for q in st["quotes"].values()))

    def test_unreadable_page_keeps_last_good_read(self):
        self.run_check()
        before = S.state(self.data)["docs"]["example/privacy"]
        sig = S.load_sig("example", "privacy", self.data)
        self.status = 503
        self.assertEqual(self.run_check(), [])
        after = S.state(self.data)["docs"]["example/privacy"]
        self.assertEqual(after["status"], "unreachable")
        self.assertEqual(after["last_ok"], before["last_ok"])
        self.assertEqual(S.load_sig("example", "privacy", self.data), sig)
        self.assertTrue(all(q["found"] for q in S.state(self.data)["quotes"].values()))

    def test_a_gutted_page_is_not_a_change(self):
        self.run_check()
        self.html = "<html><body><p>Something went wrong. Please try again later.</p></body></html>"
        self.assertEqual(self.run_check(), [])
        self.assertEqual(S.state(self.data)["docs"]["example/privacy"]["status"], "unreachable")
        self.assertTrue(all(q["found"] for q in S.state(self.data)["quotes"].values()))

    def test_removed_quotes_and_documents_are_pruned(self):
        self.run_check()
        app = dict(APP, answers={"training": APP["answers"]["training"]})
        with open(os.path.join(self.data, "platforms", "example.json"), "w") as f:
            json.dump(app, f)
        self.run_check()
        self.assertEqual(len(S.state(self.data)["quotes"]), 1)


if __name__ == "__main__":
    unittest.main()
