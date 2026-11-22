"""The reviewed data files are well formed. These rules hold for any number of apps and any state."""
import datetime as dt
import json
import os
import re
import unittest

from pipeline import store as S

# Words our own prose must not use. Quotes are exempt: they are the companies' words.
LOADED = re.compile(r"\b(spy|spies|spying|creepy|shady|illegal|unlawful|violat\w*|lies|lying|liar|deceptive|scam\w*|"
                    r"steal\w*|stole|exploit\w*|harvest\w*|abus(e|es|ive)|predat\w*|evil|sinister|sneak\w*|addict\w*|"
                    r"manipulat\w*|toxic|dangerous|unsafe|harmful|killer\w*|destroy\w*)\b", re.I)
EMPTY_OK = {"not_documented"}


class RubricTests(unittest.TestCase):
    def setUp(self):
        self.rubric = S.rubric()

    def test_criteria_and_answers(self):
        ids = [c["id"] for c in self.rubric["criteria"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in self.rubric["criteria"]:
            for key in ("label", "question", "why", "page_question"):
                self.assertTrue(c.get(key), f"{c['id']} needs {key}")
            answer_ids = [a["id"] for a in c["answers"]]
            self.assertEqual(len(answer_ids), len(set(answer_ids)), c["id"])
            for a in c["answers"]:
                self.assertIsInstance(a["points"], int)
                self.assertGreaterEqual(a["points"], 0)
                self.assertTrue(a["label"] and a["definition"])
                self.assertIsNone(LOADED.search(a["label"] + " " + a["definition"]), a["id"])
            self.assertGreater(max(a["points"] for a in c["answers"]), 0)
        dt.date.fromisoformat(self.rubric["published"])


class AppTests(unittest.TestCase):
    def setUp(self):
        self.rubric = S.rubric()
        self.apps = S.apps()

    def test_there_are_scorecards(self):
        self.assertGreater(len(self.apps), 0)
        slugs = [a["slug"] for a in self.apps]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_each_scorecard(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        facts = {f["id"] for f in self.rubric.get("facts", [])}
        for app in self.apps:
            with self.subTest(app=app["slug"]):
                self.assertRegex(app["slug"], r"^[a-z0-9-]+$")
                self.assertTrue(os.path.exists(os.path.join(S.DATA, "platforms", app["slug"] + ".json")))
                for key in ("name", "maker", "kind", "scope", "reviewed", "documents", "answers"):
                    self.assertTrue(app.get(key), f"needs {key}")
                self.assertLessEqual(dt.date.fromisoformat(app["reviewed"]), today)
                for doc_id, doc in app["documents"].items():
                    self.assertRegex(doc_id, r"^[a-z0-9-]+$")
                    self.assertTrue(doc["url"].startswith("https://"), doc_id)
                    self.assertTrue(doc["title"])
                for c in self.rubric["criteria"]:
                    a = app["answers"].get(c["id"])
                    self.assertIsNotNone(a, f"answers {c['id']}")
                    self.assertIn(a["answer"], [o["id"] for o in c["answers"]], c["id"])
                    self.assertTrue(a.get("summary"), c["id"])
                    if a["answer"] not in EMPTY_OK:
                        self.assertTrue(a.get("evidence"), f"{c['id']}: an answer other than 'not documented' cites a passage")
                self.assertFalse(set(app["answers"]) - {c["id"] for c in self.rubric["criteria"]}, "unknown criteria")
                self.assertFalse(set(app.get("facts", {})) - facts, "unknown facts")
                used = set()
                for where, cid, ev in S.evidence(app):
                    self.assertIn(ev["doc"], app["documents"], f"{where}/{cid}")
                    self.assertTrue(ev["quote"].strip(), f"{where}/{cid}")
                    self.assertEqual(ev["quote"], ev["quote"].strip())
                    used.add(ev["doc"])
                self.assertFalse(set(app["documents"]) - used, "every document listed is quoted somewhere")

    def test_our_prose_is_neutral(self):
        for app in self.apps:
            prose = [app["scope"]]
            for a in list(app["answers"].values()) + list(app.get("facts", {}).values()):
                prose += [a.get("summary", ""), a.get("note", "")]
            for text in prose:
                self.assertIsNone(LOADED.search(text), f"{app['slug']}: {text}")

    def test_not_covered_list(self):
        with open(os.path.join(S.DATA, "not_covered.json"), encoding="utf-8") as f:
            items = json.load(f)
        slugs = {a["name"].lower() for a in self.apps}
        for n in items:
            self.assertTrue(n["name"] and n["maker"] and n["reason"])
            self.assertTrue(n["url"].startswith("https://"))
            self.assertNotIn(n["name"].lower(), slugs, "an app is either covered or not")


if __name__ == "__main__":
    unittest.main()
