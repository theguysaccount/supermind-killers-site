import unittest

from pipeline import textutil as T


class TextTests(unittest.TestCase):
    def test_norm_folds_typography_only(self):
        self.assertEqual(T.norm("We don’t  “sell” data — ever…"), "We don't \"sell\" data - ever...")
        self.assertNotEqual(T.norm("Sell"), T.norm("sell"))  # case is kept: quotes are exact

    def test_html_to_text_keeps_document_text(self):
        html = ("<html><head><title>x</title><script>var a='hidden';</script></head><body>"
                "<nav>Menu Home</nav><main><h1>Privacy</h1><p>We keep chats\n for 30 days.</p>"
                "<button>Versions</button><details><summary>More</summary><p>Collapsed text.</p></details>"
                "<style>.x{}</style><footer>Copyright</footer></main></body></html>")
        text = T.html_to_text(html)
        self.assertIn("We keep chats for 30 days.", text)   # a line break inside a paragraph is a space
        self.assertIn("Versions", text)
        self.assertIn("Collapsed text.", text)
        for gone in ("hidden", "Menu Home", "Copyright", ".x{}"):
            self.assertNotIn(gone, text)

    def test_misnested_tags_do_not_swallow_the_page(self):
        text = T.html_to_text("<div><script>x</div></script><p>After the script.</p>")
        self.assertIn("After the script.", text)

    def test_contains_is_word_for_word(self):
        doc = "Once you choose to delete Personal Data, we will remove it within 30 days."
        self.assertTrue(T.contains(doc, "we will remove it within 30 days"))
        self.assertTrue(T.contains(doc.replace(" ", " "), "we will remove it within 30 days"))
        self.assertFalse(T.contains(doc, "we will remove it within 60 days"))
        self.assertFalse(T.contains(doc, ""))

    def test_signature_and_diff(self):
        old = "We collect account data for billing purposes only.\nWe keep chats until you delete them, always."
        new = ("We collect account data for billing purposes only.\nWe keep chats for eighteen months by default.\n"
               "Short line.")
        added, removed = T.diff(T.signature(old), new)
        self.assertEqual(added, ["We keep chats for eighteen months by default."])
        self.assertEqual(removed, 1)
        self.assertEqual(T.diff(T.signature(new), new), ([], 0))
        # Case and punctuation changes alone are not changes.
        self.assertEqual(T.diff(T.signature(old), old.upper().replace(",", "")), ([], 0))

    def test_clip_ignores_missing_markers(self):
        self.assertEqual(T.clip("a b c", "zzz", "yyy"), "a b c")
        self.assertEqual(T.clip("menu START body END foot", "START", "END"), "START body ")

    def test_text_fragment(self):
        short = T.text_fragment("Effective Sep 10, 2026")
        self.assertEqual(short, "#:~:text=Effective%20Sep%2010%2C%202026")
        long = T.text_fragment("one two three four five six seven eight nine ten eleven twelve thirteen")
        self.assertTrue(long.startswith("#:~:text=one%20two%20three%20four%20five,"))
        self.assertIn("%2D", T.text_fragment("opt-out now"))


if __name__ == "__main__":
    unittest.main()
