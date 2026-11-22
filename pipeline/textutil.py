"""Turn a policy page into plain text, and compare texts and quotes.

Standard library only; Python 3.9+.

The whole site rests on one mechanical check: a quote on a scorecard must appear, word for word,
in the text of the document it is attributed to. `norm()` defines "word for word": the same
characters after folding typographic quotes, dashes and whitespace, and nothing looser than that.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from html.parser import HTMLParser

# Tags whose text is never part of the document a person reads.
# (Buttons stay in: accordion headings and "Versions" menus are buttons, and they are document text.)
SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head", "nav", "footer", "form",
        "select", "option", "textarea", "canvas", "object", "math"}
# Tags that end a line of text.
BLOCK = {"p", "div", "section", "article", "main", "header", "aside", "li", "ul", "ol", "dl", "dt", "dd", "table",
         "tr", "td", "th", "thead", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "br", "hr",
         "details", "summary", "figure", "figcaption", "address", "body", "html", "title", "button", "label"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "⁠": "", "﻿": "", "­": "",
    "…": "...",
}
_FOLD_RE = re.compile("|".join(re.escape(k) for k in _FOLD))
_WS_RE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Fold typographic variants and whitespace. Case and wording are kept."""
    text = unicodedata.normalize("NFC", text)
    text = _FOLD_RE.sub(lambda m: _FOLD[m.group(0)], text)
    return _WS_RE.sub(" ", text).strip()


_BREAK = "\x00"   # marks the end of a block while parsing


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip: list[str] = []

    # Collapsed sections (accordions, "read more") stay in: a reader can open them, so their text
    # is part of the document. Only tags that never hold document text are dropped.
    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in SKIP and tag not in VOID:
                self.skip.append(tag)  # nested skip tags are counted so the outer one closes correctly
            return
        if tag in SKIP and tag not in VOID:
            self.skip.append(tag)
            return
        if tag in BLOCK:
            self.parts.append(_BREAK)

    def handle_startendtag(self, tag, attrs):
        if not self.skip and tag in BLOCK:
            self.parts.append(_BREAK)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in self.skip:
                # Unwind to the matching open tag, so a mis-nested close cannot swallow the page.
                while self.skip and self.skip.pop() != tag:
                    pass
            return
        if tag in BLOCK:
            self.parts.append(_BREAK)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data.replace(_BREAK, " "))


def html_to_text(html: str) -> str:
    """Readable text of an HTML page: one block per line, navigation and scripts dropped."""
    p = _Extractor()
    try:
        p.feed(html)
        p.close()
    except Exception:  # a broken page still yields whatever was parsed so far
        pass
    lines = []
    # Line ends inside a paragraph are just spaces; only block tags end a line of text.
    for raw in "".join(p.parts).split(_BREAK):
        line = _WS_RE.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def clip(text: str, start: str = "", end: str = "") -> str:
    """Keep the part of `text` after the first `start` marker and before the last `end` marker.

    Used to drop site chrome that the tag filter cannot see. A marker that is not found is ignored,
    so a redesign of the page never empties the document; it only lets some chrome back in.
    """
    if start:
        i = text.find(start)
        if i >= 0:
            text = text[i:]
    if end:
        j = text.rfind(end)
        if j > 0:
            text = text[:j]
    return text


def contains(text: str, quote: str) -> bool:
    """True when `quote` appears word for word in `text` (after `norm` on both sides)."""
    q = norm(quote)
    return bool(q) and q in norm(text)


_SENT_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9])")


def sentences(text: str) -> list[str]:
    """Split text into sentence-sized pieces (also split at line ends)."""
    out = []
    for line in text.split("\n"):
        line = norm(line)
        if not line:
            continue
        for s in _SENT_RE.split(line):
            s = s.strip()
            if s:
                out.append(s)
    return out


def fingerprint(sentence: str) -> str:
    """A short, stable id for a sentence: case, punctuation and spacing do not change it."""
    key = re.sub(r"[^a-z0-9]+", " ", norm(sentence).lower()).strip()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


MIN_SENTENCE = 30  # shorter pieces are menus, labels and dates, which churn without meaning

# Sentences that change on every request or every day without the policy changing: request and trace
# ids, long hex tokens, relative "updated N days ago" stamps, view counters.
VOLATILE = re.compile(
    r"\b(trace|request|correlation|ray|session|reference) id\b|\b[0-9a-f]{16,}\b|"
    r"\bupdated:? (\d+|a|an|one) (second|minute|hour|day|week|month|year)s? ago\b|"
    r"\bupdated (today|yesterday|this week|last week)\b|\b\d[\d,]* (views|people found this helpful)\b", re.I)


def substantial(s: str) -> bool:
    return len(s) >= MIN_SENTENCE and not VOLATILE.search(s)


def signature(text: str) -> list[str]:
    """Sorted fingerprints of the document's substantial sentences."""
    return sorted({fingerprint(s) for s in sentences(text) if substantial(s)})


def diff(old_sig: list[str], new_text: str) -> tuple[list[str], int]:
    """Compare a stored signature with new text. Returns (added sentences, number removed)."""
    old = set(old_sig)
    seen, added = set(), []
    for s in sentences(new_text):
        if not substantial(s):
            continue
        fp = fingerprint(s)
        if fp in seen:
            continue
        seen.add(fp)
        if fp not in old:
            added.append(s)
    return added, len(old - seen)


def text_fragment(quote: str, words: int = 5) -> str:
    """A `#:~:text=` URL fragment that makes browsers scroll to and highlight the quote."""
    from urllib.parse import quote as q

    toks = norm(quote).split(" ")
    enc = lambda s: q(s, safe="").replace("-", "%2D")  # noqa: E731  ('-' separates fragment parts)
    if len(toks) <= words * 2 + 1:
        return "#:~:text=" + enc(" ".join(toks))
    return "#:~:text=" + enc(" ".join(toks[:words])) + "," + enc(" ".join(toks[-words:]))
