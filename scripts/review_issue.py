"""After a policy check: open (or add to) one "needs-review" issue listing changed documents and
quotes that are no longer found, so the review routine or a person knows what to re-read.

    python3 scripts/review_issue.py events.json

Uses the GitHub CLI with the workflow's token. Never fails the run.
"""
import json
import os
import subprocess
import sys

SITE_URL = (os.environ.get("SITE_URL") or "https://theguysaccount.github.io/supermind-killers-site").rstrip("/")


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def main(path):
    try:
        with open(path, encoding="utf-8") as f:
            events = json.load(f)
    except (OSError, ValueError):
        print("no events file; nothing to report")
        return 0
    if not events:
        print("no changes detected")
        return 0
    lines = []
    for e in events:
        lines.append(f"- **{e['app']}**: [{e['title']}]({e['url']}) changed as of {e['date']} "
                     f"({e['added']} sentences added, {e['removed']} removed). Scorecard: {SITE_URL}/platforms/{e['app']}/")
        for q in e.get("quotes_missing", []):
            lines.append(f"  - quote no longer found ({q['criterion']}): \"{q['quote'][:200]}\"")
    body = ("The weekly documentation check found these changes. Re-read each document, update `data/platforms/<platform>.json` "
            "(answers, quotes and the `reviewed` date) where the text changed, and run the tests.\n\n" + "\n".join(lines))
    gh("label", "create", "needs-review", "--color", "D4A72C", "--description", "Documentation changed; re-review the page")
    found = gh("issue", "list", "--label", "needs-review", "--state", "open", "--json", "number", "--jq", ".[0].number")
    number = found.stdout.strip()
    if number:
        r = gh("issue", "comment", number, "--body", body)
    else:
        r = gh("issue", "create", "--label", "needs-review", "--title", "Platform documentation changed: pages to re-review", "--body", body)
    print(r.stdout or r.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
